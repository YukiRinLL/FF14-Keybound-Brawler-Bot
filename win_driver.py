# -*- coding: utf-8 -*-
"""
Interception 驱动级键盘注入
=====================================
原理: 注册成 HID 键盘设备, 游戏从 Raw Input 读到我们发的扫描码
      和真实键盘按键游戏分不出来
前置: 运行 interception_driver/install.bat (管理员) 装好内核驱动, 重启
"""
import ctypes, time
from interception import ffi, lib

# =============================================
# 扫描码表 (Set 1, FFXIV 使用的)
# =============================================
SCANCODES = {
    "enter":     0x1C,
    "return":    0x1C,
    "space":     0x39,
    "esc":       0x01,
    "escape":    0x01,
    "tab":       0x0F,
    "backspace": 0x0E,
    "ctrl":      0x1D,
    "control":   0x1D,
    "alt":       0x38,
    "shift":     0x2A,
    "v":         0x2F,
    "c":         0x2E,
    "a":         0x1E,
    "b":         0x30,
    "d":         0x20,
    "e":         0x12,
    "f":         0x21,
    "g":         0x22,
    "h":         0x23,
    "i":         0x17,
    "j":         0x24,
    "k":         0x25,
    "l":         0x26,
    "m":         0x32,
    "n":         0x31,
    "o":         0x18,
    "p":         0x19,
    "q":         0x10,
    "r":         0x13,
    "s":         0x1F,
    "t":         0x14,
    "u":         0x16,
    "w":         0x11,
    "x":         0x2D,
    "y":         0x15,
    "z":         0x2C,
}

# 状态值
KEY_DOWN = 0
KEY_UP   = 1

# =============================================
# Interception 上下文管理
# =============================================

_ctx = None          # Interception context
_kbd_device = None   # 目标键盘设备 ID
_available = False   # 驱动是否可用


def init() -> bool:
    """初始化 Interception, 返回驱动是否可用"""
    global _ctx, _kbd_device, _available
    
    try:
        _ctx = lib.interception_create_context()
    except Exception as e:
        print(f"[Driver] Interception 调用失败: {e}")
        return False
    
    if not _ctx:
        print("[Driver] Interception 驱动未安装 (ctx=NULL)")
        _available = False
        return False
    
    # 枚举所有键盘设备 (interception_is_keyboard 直接传设备ID, 0-based)
    # 设备 ID 范围是 1~20, is_keyboard 参数是 dev (int)
    for dev in range(1, 21):
        if lib.interception_is_keyboard(dev):
            # 跳过 is_invalid 的设备
            if lib.interception_is_invalid(dev):
                continue
            _kbd_device = dev
            break
    
    if _kbd_device is None:
        print("[Driver] 找不到可用的物理键盘设备")
        lib.interception_destroy_context(_ctx)
        _ctx = None
        _available = False
        return False
    
    _available = True
    print(f"[Driver] Interception 就绪 (ctx={_ctx}, keyboard={_kbd_device})")
    return True


def shutdown():
    """释放 Interception 上下文"""
    global _ctx, _kbd_device, _available
    if _ctx:
        try:
            lib.interception_destroy_context(_ctx)
        except Exception:
            pass
    _ctx = None
    _kbd_device = None
    _available = False


def is_available() -> bool:
    return _available


def _send_scan(scan_code: int, state: int):
    """往目标键盘设备发一个扫描码的按下/抬起"""
    if not _available:
        raise RuntimeError("Interception 驱动未初始化")
    
    stroke = ffi.new("InterceptionKeyStroke *")
    stroke.code = scan_code
    stroke.state = state
    result = lib.interception_send(_ctx, _kbd_device, stroke, 1)
    return result


def send_key(name: str, hold_time: float = 0.02):
    """
    发一个按键 (按下 + 抬起)
      send_key("enter")
      send_key("v")
    """
    if not _available:
        raise RuntimeError("Interception 驱动未初始化")
    
    key = name.lower().strip()
    if key not in SCANCODES:
        # 允许直接传扫描码数字
        try:
            scan = int(key, 16) if key.startswith("0x") else int(key)
        except ValueError:
            raise ValueError(f"未知按键: {name} (支持: {list(SCANCODES.keys())})")
    else:
        scan = SCANCODES[key]
    
    _send_scan(scan, KEY_DOWN)
    time.sleep(hold_time)
    _send_scan(scan, KEY_UP)


def send_hotkey(*keys, hold_time: float = 0.03):
    """
    组合键: send_hotkey("ctrl", "v")
      所有键先按下 → 再按相反顺序抬起
    """
    if not _available:
        raise RuntimeError("Interception 驱动未初始化")
    
    scans = []
    for k in keys:
        k_lower = k.lower().strip()
        if k_lower not in SCANCODES:
            try:
                scan = int(k_lower, 16) if k_lower.startswith("0x") else int(k_lower)
            except ValueError:
                raise ValueError(f"未知按键: {k}")
        else:
            scan = SCANCODES[k_lower]
        scans.append(scan)
    
    # 全部按下
    for s in scans:
        _send_scan(s, KEY_DOWN)
        time.sleep(hold_time)
    
    time.sleep(hold_time)
    
    # 反向全部抬起
    for s in reversed(scans):
        _send_scan(s, KEY_UP)
        time.sleep(hold_time)


def send_text(text: str):
    """
    中文文本: 写入剪贴板 → 驱动级 Ctrl+V 粘贴
    注: FFXIV 聊天框如果禁了 Ctrl+V, 需要换 IMM32 方案
    """
    import pyperclip
    pyperclip.copy(text)
    time.sleep(0.05)
    send_hotkey("ctrl", "v")


# =============================================
# 便捷封装
# =============================================

def bring_to_front(hwnd):
    """把游戏窗口拉到前台"""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    
    fore_hwnd = user32.GetForegroundWindow()
    fore_tid = user32.GetWindowThreadProcessId(fore_hwnd, None)
    cur_tid = kernel32.GetCurrentThreadId()
    if fore_tid != cur_tid:
        user32.AttachThreadInput(cur_tid, fore_tid, True)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(cur_tid, fore_tid, False)


if __name__ == "__main__":
    print("Interception 驱动注入测试")
    print("=" * 40)
    ok = init()
    print(f"\n驱动可用: {ok}")
    if ok:
        print("\n发 3 次 Enter... 请盯着 FFXIV 聊天框!")
        for i in range(3):
            send_key("enter")
            print(f"  [{i+1}] Enter 已发 (scan=0x1C)")
            time.sleep(1.5)
        print("\n测试结束")
    shutdown()
