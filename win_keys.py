# -*- coding: utf-8 -*-
"""底层键盘注入：SendInput + 前台窗口激活。
比 pyautogui 更可控，对游戏更友好。

用法:
    from win_keys import send_key, send_hotkey, send_text, bring_to_front

    bring_to_front(game_hwnd)   # 先把游戏拉到前台
    send_key("enter")            # 发送 Enter
    send_hotkey("ctrl", "v")     # Ctrl+V
    send_text("克劳德")          # 中文走剪贴板粘贴
"""
import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# -----------------------------------------------------------
# SendInput 结构体 (ctypes)
# -----------------------------------------------------------

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004

# 虚拟键码
VK = {
    "enter":    0x0D,
    "return":   0x0D,
    "tab":      0x09,
    "esc":      0x1B,
    "escape":   0x1B,
    "space":    0x20,
    "backspace":0x08,
    "delete":   0x2E,
    "ctrl":     0x11,
    "control":  0x11,
    "alt":      0x12,
    "shift":    0x10,
    "win":      0x5B,
    "windows":  0x5B,
    "up":       0x26,
    "down":     0x28,
    "left":     0x25,
    "right":    0x27,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("U",)
    _fields_ = [("type", wintypes.DWORD), ("U", INPUT_UNION)]


INPUT_KEYBOARD = 1

# 扫描码表 (Set 1) - FFXIV Raw Input 能读这个
SCANCODE = {
    "enter": 0x1C, "return": 0x1C,
    "space": 0x39,
    "esc": 0x01, "escape": 0x01,
    "tab": 0x0F,
    "backspace": 0x0E,
    "ctrl": 0x1D, "control": 0x1D,
    "alt": 0x38,
    "shift": 0x2A,
    "a": 0x1E, "b": 0x30, "c": 0x2E, "d": 0x20, "e": 0x12,
    "f": 0x21, "g": 0x22, "h": 0x23, "i": 0x17, "j": 0x24,
    "k": 0x25, "l": 0x26, "m": 0x32, "n": 0x31, "o": 0x18,
    "p": 0x19, "q": 0x10, "r": 0x13, "s": 0x1F, "t": 0x14,
    "u": 0x16, "v": 0x2F, "w": 0x11, "x": 0x2D, "y": 0x15, "z": 0x2C,
}


def _make_keyboard_input(vk_or_scan, flags=0, use_scancode=False):
    if use_scancode:
        ki = KEYBDINPUT(wVk=0, wScan=vk_or_scan, dwFlags=flags | KEYEVENTF_SCANCODE, time=0, dwExtraInfo=0)
    else:
        ki = KEYBDINPUT(wVk=vk_or_scan, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = ki
    return inp


def _send_input_list(inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))


def send_key(name, use_scancode=True):
    """发送一个按键的按下+抬起
    use_scancode=True 默认用扫描码模式 (FFXIV Raw Input 能识别)
    """
    name_lower = name.lower()
    if use_scancode:
        code = SCANCODE.get(name_lower)
        if code is None:
            raise ValueError(f"未知按键(扫描码): {name}")
    else:
        code = VK.get(name_lower)
        if code is None:
            raise ValueError(f"未知按键(VK): {name}")
    _send_input_list([
        _make_keyboard_input(code, 0, use_scancode),
        _make_keyboard_input(code, KEYEVENTF_KEYUP, use_scancode),
    ])


def send_hotkey(*keys, hold_time=0.03, use_scancode=True):
    """组合键: send_hotkey('ctrl', 'v')"""
    codes = []
    table = SCANCODE if use_scancode else VK
    for k in keys:
        k_lower = k.lower()
        code = table.get(k_lower)
        if code is None:
            raise ValueError(f"未知按键: {k}")
        codes.append(code)
    inputs = []
    for code in codes:
        inputs.append(_make_keyboard_input(code, 0, use_scancode))
    _send_input_list(inputs)
    time.sleep(hold_time)
    inputs = []
    for code in reversed(codes):
        inputs.append(_make_keyboard_input(code, KEYEVENTF_KEYUP, use_scancode))
    _send_input_list(inputs)


def send_text(text, char_delay=0.01, method="unicode"):
    """
    发送文本。
    method: "unicode"    → SendInput KEYEVENTF_UNICODE（直接灌 Unicode 字符）
            "clipboard"  → 剪贴板 Ctrl+V（但 FFXIV 聊天框不支持粘贴，通常不用）
    """
    if method == "clipboard":
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.05)
        send_hotkey("ctrl", "v")
        return

    # KEYEVENTF_UNICODE 模式
    inputs = []
    for ch in text:
        code = ord(ch)
        ki_down = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=0)
        ki_up = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
        inp_down = INPUT(type=INPUT_KEYBOARD); inp_down.ki = ki_down
        inp_up = INPUT(type=INPUT_KEYBOARD); inp_up.ki = ki_up
        inputs.append(inp_down)
        inputs.append(inp_up)
        if char_delay > 0:
            _send_input_list([inp_down])
            time.sleep(char_delay)
            _send_input_list([inp_up])

    if char_delay <= 0 and inputs:
        n = len(inputs)
        arr = (INPUT * n)(*inputs)
        user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))


# -----------------------------------------------------------
# 窗口激活
# -----------------------------------------------------------

def bring_to_front(hwnd):
    """把指定 HWND 拉到前台，不抢用户焦点太久"""
    if not hwnd:
        return False
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # 尝试激活（Windows 可能拒绝，但尽力而为）
    try:
        # 方法 1: SetForegroundWindow
        user32.SetForegroundWindow(hwnd)
        # 方法 2: AttachThreadInput + SetForegroundWindow
        fore_hwnd = user32.GetForegroundWindow()
        fore_tid = user32.GetWindowThreadProcessId(fore_hwnd, None)
        cur_tid = kernel32.GetCurrentThreadId()
        if fore_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fore_tid, True)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(cur_tid, fore_tid, False)
    except Exception:
        pass
    return True
