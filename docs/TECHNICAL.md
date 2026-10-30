# Technical Documentation

Detailed architecture, API design, and lessons learned. Quick start is in [README.md](../README.md).

---

## Feature overview

1. Floating overlay -- topmost, semi-transparent, draggable, Alt+V start / Shift+V stop
2. RapidOCR -- captures game screen center region ~1 per second, recognizes text
3. Wordlist fuzzy match -- 1210-entry FFXIV vocabulary, SequenceMatcher ratio >= 0.55
4. Interception driver-level injection -- FFXIV uses Raw Input API, requires kernel driver for synthetic input
5. Send chain -- Enter opens chat -> write clipboard -> driver-level Ctrl+V -> Enter sends

---

## Input injection: why SendInput alone is not enough

FFXIV reads keyboard events directly from the HID layer via **Raw Input API**, bypassing the standard Windows message queue entirely. Every standard synthetic input method is silently ignored:

| Method | Result in FFXIV | Reason |
|---|---|---|
| SendInput (VK mode) | Silently dropped | Game reads Raw Input only |
| SendInput (ScanCode mode) | Silently dropped | Same |
| keybd_event | Silently dropped | Same |
| PostMessage / SendMessage WM_CHAR | Silently dropped | Game is custom-drawn, no child windows |
| IMM32 ImmGetContext | Returns NULL | Game does not use standard IME |
| pynput / pyautogui / keyboard | Silently dropped | All wrap SendInput underneath |
| **Interception kernel driver** | Works | Registers as a real HID keyboard device, Raw Input sees it as physical hardware |

In addition, **UIPI (User Interface Privilege Isolation)** comes into play:

- FFXIV runs as **High Integrity** (Administrator)
- Python runs as **Medium Integrity** (normal user)
- Windows security: lower-integrity processes' SendInput calls are silently discarded
- **Solution: run Python as Administrator**. Same integrity level -> SendInput works normally.

Reference: https://gitee.com/changmenc/ff14_dzt (FF14打字通, pure SendInput + admin run)

---

## Interception Python API (v0.16+)

```python
from interception import ffi, lib

# 1. Create context
ctx = lib.interception_create_context()
# NULL = driver not installed, non-NULL = ready

# 2. Enumerate keyboard devices (1..20)
kbd = None
for dev in range(1, 21):
    if lib.interception_is_keyboard(dev) and not lib.interception_is_invalid(dev):
        kbd = dev
        break

# 3. Send a scan code (Enter = 0x1C)
stroke = ffi.new("InterceptionKeyStroke *")
stroke.code = 0x1C       # Set 1 scan code
stroke.state = 0         # INTERCEPTION_KEY_DOWN
lib.interception_send(ctx, kbd, stroke, 1)
stroke.state = 1         # INTERCEPTION_KEY_UP
lib.interception_send(ctx, kbd, stroke, 1)

# 4. Cleanup
lib.interception_destroy_context(ctx)
```

Note: the Python package API differs from the original C library:
- No `interception_get_device_caps` -- use `interception_is_keyboard(dev)` enumeration
- `interception_get_hardware_id(ctx, dev, buf, buf_size)` takes 4 args
- `interception_send(ctx, dev, stroke_ptr, count)` -- create strokes with `ffi.new("InterceptionKeyStroke *")`

---

## Scan code table (Set 1)

FFXIV expects Set 1 scan codes. Interception sends these directly:

| Key | Scan Code |
|---|---|
| Enter | 0x1C |
| Left Ctrl | 0x1D |
| Left Shift | 0x2A |
| Alt | 0x38 |
| V | 0x2F |
| C | 0x2E |
| A | 0x1E |
| Space | 0x39 |
| Esc | 0x01 |

Complete list in `win_driver.py` under `SCANCODES`.

---

## Chinese input approach

The Send chain:

```
1. SendInput KEYEVENTF_SCANCODE (Enter, scan 0x1C) -> open chat input
2. SendInput KEYEVENTF_UNICODE -> inject raw Unicode characters
3. SendInput KEYEVENTF_SCANCODE (Enter, scan 0x1C) -> send
```

Key requirement: **run as Administrator**. Without admin, UIPI silently drops all SendInput calls.

Alternative approaches tested and rejected:

| Approach | Result | Reason |
|---|---|---|
| PostMessage WM_UNICHAR / WM_CHAR | No effect | Game ignores posted window messages |
| IMM32 ImmSetCompositionString | ImmGetContext returns NULL | Game does not expose IME context |
| Driver-level per-character scan codes | N/A | Chinese characters have no hardware scan codes |
| Clipboard + driver-level Ctrl+V | Works but unreliable | Some game modes filter paste |

---

## CLI arguments

| Argument | Default | Description |
|---|---|---|
| `--region` | auto | OCR region `left top right bottom` |
| `--window-title` | `最终幻想XIV` | Game window title keyword |
| `--center-ratio` | `0.3` | Screen center area ratio for OCR |
| `--interval` | `0.0` | Loop interval in seconds |
| `--pause-between` | `0.08` | Pause between Enter / text / Enter |
| `--max-iterations` | `0` (unlimited) | Max loop iterations |
| `--autostart` | `False` | Auto-start on launch |

### Overlay hotkeys

| Hotkey | Action |
|---|---|
| **Alt+V** | Start loop |
| **Shift+V** | Stop loop |
| **F8** | Toggle transparency (0.55 <-> 0.88) |
| Mouse drag | Move overlay window |

---

## Technical details

### win_keys.py -- SendInput ctypes structs

The INPUT struct must match the MS definition exactly. On x64 the total size must be **40 bytes** or SendInput silently fails with error 87 (INVALID_PARAMETER).

```python
# WRONG: dwExtraInfo as ctypes.POINTER(ctypes.c_ulong) -> 64-bit alignment error
# WRONG: INPUT missing _anonymous_ -> .U.ki access fails
# WRONG: INPUT_UNION with only KEYBDINPUT -> INPUT = 32 bytes, SendInput needs 40!

# CORRECT:
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD),
                ("dwFlags", DWORD), ("time", DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]  # critical

class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("U",)  # critical
    _fields_ = [("type", DWORD), ("U", INPUT_UNION)]
```

Sizes on x64:
- KEYBDINPUT = 24 bytes
- INPUT_UNION = max member MOUSEINPUT = 32 bytes
- **INPUT = 40 bytes** (SendInput requirement)

### win_driver.py -- Interception driver wrapper

```
Import time:
  1. from win_driver import init -> auto-try creating ctx
  2. ctx != NULL -> INTERCEPTION_AVAILABLE = True
  3. Enumerate keyboard devices (is_keyboard + !is_invalid)
  4. Pick first available keyboard device
```

### Window activation

```python
# FFXIV may resist foreground switching. Use AttachThreadInput:
if fore_tid != cur_tid:
    user32.AttachThreadInput(cur_tid, fore_tid, True)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur_tid, fore_tid, False)
user32.ShowWindow(hwnd, SW_RESTORE)
```

### OCR pipeline

```
RapidOCR(img) -> [[[pts], text, conf], ...]
  -> pick_word_in_region() picks candidate closest to screen center
  -> Clean: re.sub(r'[^\u4e00-\u9fff\w]', '', ocr_raw)
  -> fuzzy_match_best() SequenceMatcher(ratio >= 0.55)
  -> Matched wordlist entry -> execute input chain
  -> No match -> fall back to raw OCR text
```

---

## Pitfalls and fixes

| # | Issue | Root Cause | Fix |
|---|---|---|---|
| 1 | SendInput returns 0 silently | INPUT union missing MOUSEINPUT -> wrong size (needs 40 bytes) | Include all three members + c_void_p + _anonymous_ |
| 2 | SendInput does nothing in FFXIV | **UIPI!** Game runs High Integrity, Python runs Medium Integrity | **Run as Administrator** |
| 3 | Interception ctx = NULL | Driver not installed or not rebooted after install | install-interception.exe /install -> reboot |
| 4 | install-interception.exe fails silently | Needs admin rights + path with spaces | Run explicitly from admin CMD |
| 5 | Python interception API mismatch | New Python package removed get_device_caps | Use is_keyboard + is_invalid enumeration |
| 6 | Unicode input not working | KEYEVENTF_UNICODE dropped by UIPI | Run Python as admin |
| 7 | Overlay steals focus | Topmost thread forces SetWindowPos every 0.6s | Add SWP_NOACTIVATE flag |
| 8 | Window title search fails | Game window title is Chinese "最终幻想XIV", not "FFXIV" | main.py uses Chinese keyword by default |

---

## Known limitations

1. **Admin required** -- UIPI isolation makes SendInput ineffective without same integrity level
2. **Fullscreen exclusive** -- Screenshot capture may fail; windowed maximized recommended

---

## Version history

| Date | Change |
|---|---|
| 2026-10-30 | v1.0: initial release, end-to-end verified |
