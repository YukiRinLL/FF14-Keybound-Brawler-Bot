# -*- coding: utf-8 -*-
"""
FFXIV OCR 悬浮窗 - 屏幕文字识别 + 自动回车粘贴发送

界面:
  - 半透明置顶悬浮窗，可拖动
  - 实时显示: 运行状态 / 循环次数 / 识别到的文字 / 耗时 / 最近操作日志
  - 自带 开始 / 停止 按钮

热键:
  Alt+V   开始 / 继续 循环
  Shift+V 停止循环
  F8      切换悬浮窗半透明 / 完全不透明

声音:
  开始: 两声短高音 (880Hz x 2)
  停止: 一声长低音 (440Hz)
"""

import os
import sys
import threading
import time
import traceback
from collections import deque
from difflib import SequenceMatcher

import ctypes
import numpy as np
import pyautogui
import pyperclip
import pygetwindow as gw
import tkinter as tk
import winsound
from PIL import ImageGrab, Image, ImageTk
from win_keys import send_key, send_hotkey, send_text, bring_to_front

# pyautogui 安全设置
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02

# ================================================================
#  Interception 驱动初始化 (全局)
# ================================================================
INTERCEPTION_AVAILABLE = False
try:
    from win_driver import init as _drv_init, shutdown as _drv_shutdown
    INTERCEPTION_AVAILABLE = _drv_init()
except Exception as e:
    print(f"[Driver] Interception 加载失败: {e}")
    INTERCEPTION_AVAILABLE = False


# ================================================================
#  声音提示
# ================================================================

def beep_start():
    winsound.Beep(880, 120)
    winsound.Beep(880, 120)


def beep_stop():
    winsound.Beep(440, 350)


# ================================================================
#  词表模糊匹配
# ================================================================

def load_wordlist(path):
    """加载 words.txt，每行一个词，忽略空行和 # 注释"""
    words = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                w = line.strip()
                if w and not w.startswith("#"):
                    words.append(w)
    except FileNotFoundError:
        return []
    return words


def fuzzy_match_best(ocr_text, wordlist, threshold=0.55):
    """
    在 wordlist 中找与 ocr_text 最相似的词。
    返回 (best_word, score) 或 (None, 0.0)。
    threshold 控制最低相似度，低于此值视为不匹配。
    """
    if not wordlist or not ocr_text:
        return None, 0.0
    best_word = None
    best_score = 0.0
    # 先做完全包含/被包含检查（权重给得更高）
    for w in wordlist:
        if not w:
            continue
        if ocr_text in w or w in ocr_text:
            score = max(len(ocr_text), len(w)) / max(len(ocr_text), len(w), 1)
            # 完全相等得 1.0，部分包含按长度比例给分
            ratio = SequenceMatcher(None, ocr_text, w).ratio()
            score = max(score, ratio)
            if score > best_score:
                best_score = score
                best_word = w
    if best_word is None:
        # 再做通用模糊匹配
        for w in wordlist:
            if not w:
                continue
            ratio = SequenceMatcher(None, ocr_text, w).ratio()
            if ratio > best_score:
                best_score = ratio
                best_word = w
    if best_score < threshold:
        return None, best_score
    return best_word, best_score


# ================================================================
#  共享状态 (后台线程写, UI线程读)
# ================================================================

class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.iteration = 0
        self.last_text = ""           # 最近匹配到的词
        self.last_ocr_raw = ""        # 最近 OCR 原始识别
        self.last_match_score = 0.0   # 最近匹配度 (0~1)
        self.last_pos = (0, 0)
        self.last_elapsed = 0.0
        self.last_action = "等待开始"
        self.log = deque(maxlen=30)     # 操作日志 (最近30条)
        self.region = None              # OCR 区域 (left, top, right, bottom)
        self.ocr_count = 0              # 累计 OCR 次数
        self.send_count = 0             # 累计发送次数
        self.no_text_count = 0          # 连续未识别到文字次数

    def snapshot(self):
        with self.lock:
            return dict(
                running=self.running,
                iteration=self.iteration,
                last_text=self.last_text,
                last_ocr_raw=self.last_ocr_raw,
                last_match_score=self.last_match_score,
                last_pos=self.last_pos,
                last_elapsed=self.last_elapsed,
                last_action=self.last_action,
                log=list(self.log),
                region=self.region,
                ocr_count=self.ocr_count,
                send_count=self.send_count,
                no_text_count=self.no_text_count,
            )

    def set_running(self, running):
        with self.lock:
            self.running = running

    def add_log(self, text, throttle=False):
        """throttle=True 时, 同一文本 3 秒内只打一次"""
        ts = time.strftime("%H:%M:%S")
        with self.lock:
            if throttle and self.log:
                last = self.log[0]
                if text in last:
                    return
            self.log.appendleft(f"[{ts}] {text}")


# ================================================================
#  OCR + 动作核心
# ================================================================

def find_target_window(keyword):
    for w in gw.getAllWindows():
        if w.title and keyword.lower() in w.title.lower():
            return w
    return None


def compute_region(win, ratio):
    w, h = win.width, win.height
    mx = int(w * (1 - ratio) / 2)
    my = int(h * (1 - ratio) / 2)
    return (win.left + mx, win.top + my,
            win.left + w - mx, win.top + h - my)


def screenshot_region(region):
    img = ImageGrab.grab(bbox=region)
    return np.array(img)[:, :, ::-1].copy()


def pick_word_in_region(ocr_result, region):
    if not ocr_result:
        return None

    rx0, ry0, rx1, ry1 = region
    cx_region = (rx0 + rx1) / 2
    cy_region = (ry0 + ry1) / 2

    best = None
    best_dist = float("inf")
    for item in ocr_result:
        box, text, conf = item
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        ax = sum(xs) / len(xs) + rx0
        ay = sum(ys) / len(ys) + ry0
        if rx0 <= ax <= rx1 and ry0 <= ay <= ry1:
            d = (ax - cx_region) ** 2 + (ay - cy_region) ** 2
            if d < best_dist:
                best_dist = d
                best = (ax, ay, text)
    return best


def is_admin():
    """检测当前进程是否管理员"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def do_action(text, pause_between, state, game_hwnd):
    """先激活游戏 → 回车 → 输入 → 回车
    
    方案: SendInput (管理员身份运行时 UIPI 不拦截)
      - Enter: KEYEVENTF_SCANCODE (Set 1, FFXIV Raw Input 兼容)
      - 中文:  KEYEVENTF_UNICODE (直接灌 Unicode 字符)
    参考: https://gitee.com/changmenc/ff14_dzt (FF14打字通)
    """
    bring_to_front(game_hwnd)
    time.sleep(0.02)

    # Enter: 默认 KEYEVENTF_SCANCODE, FFXIV 兼容
    send_key("enter", use_scancode=True)
    time.sleep(pause_between)

    # 中文: KEYEVENTF_UNICODE
    send_text(text, char_delay=0.015, method="unicode")
    time.sleep(pause_between)

    send_key("enter", use_scancode=True)

    with state.lock:
        state.send_count += 1
    state.add_log(f"发送: {text}")


def run_worker(ocr, region, stop_event, state, pause_between, interval, max_iterations, wordlist, game_hwnd):
    """后台循环线程"""
    state.set_running(True)
    state.add_log(f"循环开始 (词表 {len(wordlist)} 条)")
    iteration = 0

    try:
        while not stop_event.is_set():
            iteration += 1
            with state.lock:
                state.iteration = iteration

            if max_iterations > 0 and iteration > max_iterations:
                state.add_log(f"达到上限 {max_iterations}，停止")
                break

            t0 = time.time()
            frame = screenshot_region(region)
            ocr_result, _ = ocr(frame)

            # 先让 OCR 选出最靠近中心的候选，再用词表做模糊匹配
            raw_pick = pick_word_in_region(ocr_result, region)

            match_text = None
            match_score = 0.0
            ocr_raw = ""

            if raw_pick is not None:
                raw_cx, raw_cy, ocr_raw = raw_pick
                matched, score = fuzzy_match_best(ocr_raw, wordlist)
                if matched is not None:
                    match_text = matched
                    match_score = score
                else:
                    # 没匹配上词表，退回 OCR 原文
                    match_text = ocr_raw
                    match_score = score  # 记录实际相似度（< threshold）

            elapsed = time.time() - t0

            with state.lock:
                state.last_elapsed = elapsed
                state.ocr_count += 1
                state.last_ocr_raw = ocr_raw or "(空)"
                state.last_match_score = match_score

            if stop_event.is_set():
                break

            if match_text is None:
                with state.lock:
                    state.no_text_count += 1
                    state.last_text = "(无文字)"
                    state.last_action = "未识别"
                state.add_log(f"#{iteration} OCR空 ({elapsed:.2f}s)")
            else:
                cx, cy, _ = raw_pick
                with state.lock:
                    state.no_text_count = 0
                    state.last_text = match_text
                    state.last_pos = (int(cx), int(cy))
                    state.last_action = "准备发送"
                state.add_log(
                    f"#{iteration} '{match_text}' "
                    f"(OCR='{ocr_raw}' 匹配={match_score:.2f}) ({elapsed:.2f}s)"
                )
                try:
                    do_action(match_text, pause_between, state, game_hwnd)
                    with state.lock:
                        state.last_action = "已发送"
                except pyautogui.FailSafeException:
                    state.add_log("触发 FailSafe（鼠标到左上角）")
                    break

            if stop_event.is_set():
                break
            if interval > 0:
                time.sleep(interval)

    except Exception as e:
        state.add_log(f"异常: {e}")
        traceback.print_exc()
    finally:
        state.set_running(False)
        state.add_log("循环停止")


# ================================================================
#  悬浮窗 UI
# ================================================================

class FloatingOverlay:
    # Win32 常量
    HWND_TOPMOST = -1
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOACTIVATE = 0x0010
    GWL_EXSTYLE = -20
    WS_EX_TOPMOST = 0x00000008
    WS_EX_LAYERED = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080      # 任务栏不显示
    WS_EX_TRANSPARENT_CLICK = 0x00000020  # 鼠标穿透（暂不用）

    def __init__(self, state):
        self.state = state
        self.root = tk.Tk()
        self.root.title("FFXIV OCR")
        self.root.overrideredirect(True)        # 去掉边框
        self.root.attributes("-topmost", True)  # Tk 层置顶（基础保障）
        self.root.attributes("-alpha", 0.88)    # 半透明
        self._alpha_high = True
        self._last_force_topmost = 0.0          # 上次强制置顶的时间

        # 窗口大小：窄长条形
        w, h = 360, 260
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # 默认放到屏幕右侧居中
        x = sw - w - 20
        y = sh // 2 - h // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        # 先让 Tk 真正创建原生窗口，再取 HWND
        self.root.update_idletasks()
        self._hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
        # 如果 GetParent 返回 0，winfo_id() 本身就是 HWND
        if not self._hwnd:
            self._hwnd = int(self.root.winfo_id())

        # 强制 Win32 置顶：扩展样式 + SetWindowPos
        self._force_topmost_win32()
        # 启动后台置顶守护线程（每 600ms 重新 apply 一次，防止全屏游戏抢走）
        self._stop_topmost_thread = threading.Event()
        threading.Thread(target=self._topmost_guard, daemon=True).start()

        # 配色：深色半透明背景
        bg = "#1a1a2e"
        fg = "#e0e0e0"
        accent = "#e94560"
        dim = "#888888"

        self.bg = bg
        self.fg = fg
        self.accent = accent
        self.dim = dim

        container = tk.Frame(self.root, bg=bg, bd=1, relief="solid")
        container.pack(fill="both", expand=True)

        # ---- 标题栏（可拖动） ----
        title_bar = tk.Frame(container, bg="#16213e", height=24)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)

        self.lbl_title = tk.Label(
            title_bar, text=" FFXIV OCR 悬浮窗",
            bg="#16213e", fg=fg, font=("Microsoft YaHei UI", 9, "bold"),
        )
        self.lbl_title.pack(side="left", padx=4)

        self.lbl_status = tk.Label(
            title_bar, text="● 就绪",
            bg="#16213e", fg=dim, font=("Microsoft YaHei UI", 9),
        )
        self.lbl_status.pack(side="left", padx=6)

        # 标题栏上的关闭 & 透明切换按钮
        btn_close = tk.Label(title_bar, text="✕", bg="#16213e", fg="#e94560",
                             font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2")
        btn_close.pack(side="right", padx=(0, 6))
        btn_close.bind("<Button-1>", lambda e: self.quit())

        btn_alpha = tk.Label(title_bar, text="◐", bg="#16213e", fg=dim,
                             font=("Microsoft YaHei UI", 9), cursor="hand2")
        btn_alpha.pack(side="right", padx=(0, 8))
        btn_alpha.bind("<Button-1>", lambda e: self.toggle_alpha())

        # 拖动绑定
        for w_ in (title_bar, self.lbl_title, self.lbl_status):
            w_.bind("<Button-1>", self._start_drag)
            w_.bind("<B1-Motion>", self._do_drag)

        # ---- 主内容区 ----
        body = tk.Frame(container, bg=bg)
        body.pack(fill="both", expand=True, padx=8, pady=(6, 6))

        # 信息行
        self.lbl_iter = tk.Label(body, text="次数: 0 / 累计 OCR: 0 / 发送: 0",
                                 bg=bg, fg=fg, font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_iter.pack(fill="x")

        self.lbl_region = tk.Label(body, text="区域: 未确定",
                                   bg=bg, fg=dim, font=("Microsoft YaHei UI", 8), anchor="w")
        self.lbl_region.pack(fill="x", pady=(1, 4))

        # 最近识别
        row_text = tk.Frame(body, bg=bg)
        row_text.pack(fill="x")
        tk.Label(row_text, text="识别:", bg=bg, fg=dim,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.lbl_text = tk.Label(row_text, text="(等待中)", bg=bg, fg=accent,
                                 font=("Microsoft YaHei UI", 10, "bold"),
                                 anchor="w")
        self.lbl_text.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # 坐标 & 耗时
        self.lbl_pos_time = tk.Label(body, text="坐标: -- ,  耗时: --s",
                                     bg=bg, fg=dim, font=("Microsoft YaHei UI", 8), anchor="w")
        self.lbl_pos_time.pack(fill="x", pady=(0, 4))

        # 日志区
        tk.Label(body, text="最近日志:", bg=bg, fg=dim,
                 font=("Microsoft YaHei UI", 8)).pack(anchor="w")

        log_frame = tk.Frame(body, bg="#0f0f1a")
        log_frame.pack(fill="both", expand=True, pady=(2, 0))

        self.txt_log = tk.Text(
            log_frame, bg="#0f0f1a", fg="#a0d0a0",
            font=("Consolas", 8), height=8,
            relief="flat", bd=0, padx=4, pady=2,
            state="disabled", wrap="word",
        )
        self.txt_log.pack(fill="both", expand=True)

        # ---- 按钮区 ----
        btn_row = tk.Frame(container, bg=bg)
        btn_row.pack(fill="x", padx=8, pady=(0, 6))

        self.btn_start = tk.Button(
            btn_row, text="开始 (Alt+V)", command=self.on_start_click,
            bg="#2d6a4f", fg="white", activebackground="#40916c",
            font=("Microsoft YaHei UI", 9), relief="flat", height=1, cursor="hand2",
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_stop = tk.Button(
            btn_row, text="停止 (Shift+V)", command=self.on_stop_click,
            bg="#6a2d2d", fg="white", activebackground="#914040",
            font=("Microsoft YaHei UI", 9), relief="flat", height=1, cursor="hand2",
        )
        self.btn_stop.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # ---- 内部状态 ----
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._ocr = None
        self._region = None
        self._pause_between = 0.08
        self._interval = 0.0
        self._max_iterations = 0
        self._wordlist = []
        self._game_hwnd = None

        # 热键
        import keyboard
        keyboard.add_hotkey("alt+v", self.on_start_click)
        keyboard.add_hotkey("shift+v", self.on_stop_click)

        # 定时刷新 UI
        self.root.after(100, self._refresh)

    # ---- 拖动 ----
    def _start_drag(self, ev):
        self._drag_x = ev.x_root - self.root.winfo_x()
        self._drag_y = ev.y_root - self.root.winfo_y()

    def _do_drag(self, ev):
        self.root.geometry(f"+{ev.x_root - self._drag_x}+{ev.y_root - self._drag_y}")

    # ---- 透明度切换 ----
    def toggle_alpha(self):
        if self._alpha_high:
            self.root.attributes("-alpha", 0.55)
            self._alpha_high = False
        else:
            self.root.attributes("-alpha", 0.88)
            self._alpha_high = True

    # ---- Win32 强制置顶（对抗全屏游戏） ----
    def _force_topmost_win32(self):
        """用 Win32 API 强制把悬浮窗压到最顶层"""
        try:
            user32 = ctypes.windll.user32
            # 1) 设置扩展样式：TOPMOST + LAYERED + TOOLWINDOW（任务栏不显示）
            ex_style = user32.GetWindowLongW(self._hwnd, self.GWL_EXSTYLE)
            ex_style |= self.WS_EX_TOPMOST | self.WS_EX_LAYERED | self.WS_EX_TOOLWINDOW
            user32.SetWindowLongW(self._hwnd, self.GWL_EXSTYLE, ex_style)
            # 2) SetWindowPos: HWND_TOPMOST, 不抢焦点
            user32.SetWindowPos(
                self._hwnd,
                self.HWND_TOPMOST,
                0, 0, 0, 0,
                self.SWP_NOSIZE | self.SWP_NOMOVE | self.SWP_NOACTIVATE,
            )
        except Exception:
            pass  # Tk fallback 已经开了，Win32 失败也不致命

    def _topmost_guard(self):
        """后台线程：每 600ms 重新 apply 置顶，防止游戏抢走层级"""
        while not self._stop_topmost_thread.is_set():
            try:
                self._force_topmost_win32()
            except Exception:
                pass
            self._stop_topmost_thread.wait(0.6)

    # ---- 初始化 OCR ----
    def setup(self, region, pause_between=0.08, interval=0.0, max_iterations=0, wordlist_path=None, game_hwnd=None):
        from rapidocr_onnxruntime import RapidOCR
        self._ocr = RapidOCR()
        self._region = region
        self._pause_between = pause_between
        self._interval = interval
        self._max_iterations = max_iterations
        self._game_hwnd = game_hwnd

        # 加载词表
        self._wordlist = load_wordlist(wordlist_path) if wordlist_path else []

        self.state.region = region
        rx0, ry0, rx1, ry1 = region
        self.lbl_region.config(
            text=f"区域: {rx0},{ry0} → {rx1},{ry1}  ({rx1-rx0}x{ry1-ry0})"
        )
        self.state.add_log("OCR 模型加载完成")
        if self._game_hwnd:
            self.state.add_log(f"游戏窗口已绑定 (HWND={self._game_hwnd})")
        else:
            self.state.add_log("警告: 未绑定游戏 HWND，按键可能进不去游戏")
        if self._wordlist:
            self.state.add_log(f"词表加载: {len(self._wordlist)} 条")
        else:
            self.state.add_log("未加载词表")

    # ---- 热键/按钮回调 ----
    def on_start_click(self):
        if self._worker_thread and self._worker_thread.is_alive():
            return  # 已在运行
        if self._ocr is None:
            self.state.add_log("错误: OCR 未初始化")
            return
        beep_start()
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=run_worker,
            args=(self._ocr, self._region, self._stop_event, self.state,
                  self._pause_between, self._interval, self._max_iterations,
                  self._wordlist, self._game_hwnd),
            daemon=True,
        )
        self._worker_thread.start()

    def on_stop_click(self):
        if not (self._worker_thread and self._worker_thread.is_alive()):
            return
        beep_stop()
        self._stop_event.set()

    # ---- 定时刷新 ----
    def _refresh(self):
        snap = self.state.snapshot()

        # 状态栏
        if snap["running"]:
            self.lbl_status.config(text="● 运行中", fg="#40c080")
            self.btn_start.config(bg="#333333", text="运行中")
            self.btn_stop.config(bg="#914040")
        else:
            if snap["iteration"] > 0:
                self.lbl_status.config(text="● 已停止", fg="#c0a040")
            else:
                self.lbl_status.config(text="● 就绪", fg=self.dim)
            self.btn_start.config(bg="#2d6a4f", text="开始 (Alt+V)")
            self.btn_stop.config(bg="#333333", text="已停止")

        # 计数
        self.lbl_iter.config(
            text=f"次数: {snap['iteration']}  OCR: {snap['ocr_count']}  发送: {snap['send_count']}"
        )

        # 识别文字 (显示匹配度)
        text = snap["last_text"] or "(等待中)"
        score = snap["last_match_score"]
        raw = snap["last_ocr_raw"] or ""
        if raw and raw != text:
            self.lbl_text.config(text=f"{text}  匹配={score:.2f}  (OCR={raw})")
        else:
            self.lbl_text.config(text=f"{text}  匹配={score:.2f}")

        # 坐标 & 耗时
        cx, cy = snap["last_pos"]
        self.lbl_pos_time.config(
            text=f"坐标: ({cx},{cy})   耗时: {snap['last_elapsed']:.2f}s   连续空: {snap['no_text_count']}"
        )

        # 日志 (最多 15 行显示)
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        for line in snap["log"][:15]:
            self.txt_log.insert("end", line + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

        self.root.after(100, self._refresh)

    # ---- 启动/退出 ----
    def run(self):
        self.root.mainloop()

    def quit(self):
        self._stop_topmost_thread.set()
        self._stop_event.set()
        self.root.destroy()


# ================================================================
#  main
# ================================================================

def main():
    # 参数（保留命令行但简化）
    import argparse
    parser = argparse.ArgumentParser(description="FFXIV OCR 悬浮窗")
    parser.add_argument("--region", type=int, nargs=4, default=None)
    parser.add_argument("--window-title", default="最终幻想XIV")
    parser.add_argument("--center-ratio", type=float, default=0.3)
    parser.add_argument("--interval", type=float, default=0.0)
    parser.add_argument("--pause-between", type=float, default=0.08)
    parser.add_argument("--max-iterations", type=int, default=0)
    parser.add_argument("--autostart", action="store_true", default=False)
    args = parser.parse_args()

    # 1. 找窗口 + 确定区域
    if args.region:
        region = tuple(args.region)
        source = "手动指定"
    else:
        win = find_target_window(args.window_title)
        if win is None:
            # 没有目标窗口也能启动悬浮窗，只是不能开始
            print(f"提示: 未找到 '{args.window_title}' 窗口。可以用 --region 指定区域后再启动。")
            region = None
            source = "未找到窗口"
        else:
            region = compute_region(win, args.center_ratio)
            source = f"窗口 '{win.title}' ({win.width}x{win.height})"
            
            # 保存调试截图 - 启动时先存一张
            try:
                _dbg = ImageGrab.grab(bbox=region)
                _dbg.save(r'e:\魔光键影\_debug_ocr_region.png')
                print(f"[调试截图] OCR 区域 → _debug_ocr_region.png ({_dbg.size})")
                print(f"[调试] region = {region}")
            except Exception as _e:
                print(f"[调试] 截图失败: {_e}")

    # 2. 创建状态 + 悬浮窗
    state = SharedState()
    overlay = FloatingOverlay(state)

    # 记录游戏窗口 HWND（按键注入用）
    game_hwnd = int(win._hWnd) if win else 0

    if region is not None:
        try:
            wordlist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "words.txt")
            overlay.setup(region, args.pause_between, args.interval, args.max_iterations,
                          wordlist_path, game_hwnd)
            print(f"[OK] {source}  HWND={game_hwnd}")
            print(f"[OK] 区域: {region}")
            if args.autostart:
                overlay.on_start_click()
        except Exception as e:
            state.add_log(f"OCR 初始化失败: {e}")
            print(f"[ERROR] {e}")
    else:
        state.add_log("未找到目标窗口，请先启动游戏或用 --region 指定")

    admin_ok = is_admin()
    driver_info = "SendInput KEYEVENTF_UNICODE"
    perm_info = "✅ 管理员模式" if admin_ok else "⚠️ 非管理员 (右键启动_管理员.bat)"
    print(f"\n输入方案: {driver_info}")
    print(f"权限状态: {perm_info}")
    print("悬浮窗已启动，按 Alt+V 开始 / Shift+V 停止 / F8 切换透明度")
    try:
        overlay.run()
    finally:
        if INTERCEPTION_AVAILABLE:
            try:
                _drv_shutdown()
                print("[Driver] Interception 已释放")
            except Exception:
                pass


if __name__ == "__main__":
    main()
