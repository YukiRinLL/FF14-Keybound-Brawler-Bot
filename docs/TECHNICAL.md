# 技术文档

> 详细的架构、API 原理、踩坑记录见本文档。快速上手指南看 [README.md](../README.md)。

---

## 功能

1. **悬浮窗**：置顶、半透明、可拖动、Alt+V 开始/Shift+V 停止
2. **RapidOCR 识别**：每秒截图游戏屏幕中央区域，识别文字
3. **词库模糊匹配**：1210 条 FFXIV 词汇，SequenceMatcher 相似度 ≥ 0.55
4. **Interception 驱动级注入**：FFXIV 用 Raw Input API 独占键盘，必须内核驱动级注入
5. **自动发送链**：Enter 开聊天框 → 写剪贴板 → 驱动级 Ctrl+V → Enter 发送

---

## 项目结构

```
FF14-Keybound-Brawler-Bot/
├── main.py                  # 悬浮窗主程序 (OCR+匹配+循环)
├── win_driver.py            # Interception 驱动级注入封装
├── win_keys.py              # SendInput 回退实现
├── words.txt                # 1210 条 FFXIV 词汇
├── requirements.txt         # Python 依赖
├── 启动_管理员.bat           # 管理员一键启动
├── docs/
│   ├── TECHNICAL.md         # 本文档
│   ├── screenshot_ready.png
│   └── screenshot_sending.png
└── README.md
```

---

## Interception 驱动注入原理

FFXIV 游戏窗口用 **Raw Input API** 直接从硬件读取键盘事件，绕过了所有 Windows 消息队列。因此所有标准 Windows 合成输入都无效：

| 方案 | 在 FFXIV 中效果 | 原因 |
|---|---|---|
| SendInput (VK 模式) | ❌ 无效 | 游戏只读 Raw Input |
| SendInput (SCANCODE 模式) | ❌ 无效 | 同上 |
| keybd_event | ❌ 无效 | 同上 |
| PostMessage / SendMessage | ❌ 无效 | 游戏自绘，无子窗口 |
| IMM32 ImmGetContext | ❌ 返回 NULL | 游戏不用标准 IME |
| pynput / pyautogui / keyboard | ❌ 无效 | 底层都是 SendInput |
| **Interception 内核驱动** | ✅ **有效** | 注册成 HID 键盘设备，Raw Input 读到的扫描码和真键盘无区别 |

### Interception Python API 要点（v0.16+）

```python
from interception import ffi, lib

# 1. 创建上下文
ctx = lib.interception_create_context()
# NULL = 驱动未装, 非 NULL = 驱动就绪

# 2. 枚举键盘设备 (1~20)
for dev in range(1, 21):
    if lib.interception_is_keyboard(dev) and not lib.interception_is_invalid(dev):
        kbd = dev
        break

# 3. 发扫描码 (Enter = 0x1C)
stroke = ffi.new("InterceptionKeyStroke *")
stroke.code = 0x1C       # 扫描码 Set 1
stroke.state = 0         # INTERCEPTION_KEY_DOWN
lib.interception_send(ctx, kbd, stroke, 1)
stroke.state = 1         # INTERCEPTION_KEY_UP
lib.interception_send(ctx, kbd, stroke, 1)

# 4. 释放
lib.interception_destroy_context(ctx)
```

⚠️ 注意 Python interception 包 API 与原版 C 库不同：
- 没有 `interception_get_device_caps`，用 `interception_is_keyboard(dev)` 枚举
- `interception_get_hardware_id(ctx, dev, buf, buf_size)` 4 参数
- `interception_send(ctx, dev, stroke_ptr, count)` 用 ffi.new("InterceptionKeyStroke *") 创建 stroke

---

## 扫描码表 (Set 1)

游戏用 Set 1 扫描码，Interception 直接发这个：

| 键 | 扫描码 |
|---|---|
| Enter | 0x1C |
| Ctrl (左) | 0x1D |
| Shift (左) | 0x2A |
| Alt | 0x38 |
| V | 0x2F |
| C | 0x2E |
| A | 0x1E |
| Space | 0x39 |
| Esc | 0x01 |

完整列表见 `win_driver.py` 的 `SCANCODES` 字典。

---

## 中文输入方案

输入链：

```
1. SendInput KEYEVENTF_SCANCODE (Enter, scan 0x1C) → 打开聊天框
2. SendInput KEYEVENTF_UNICODE → 灌 Unicode 中文字符
3. SendInput KEYEVENTF_SCANCODE (Enter, scan 0x1C) → 发送
```

**关键：必须管理员身份运行！**
FFXIV 以 High Integrity 运行，普通 Python 是 Medium Integrity。
Windows UIPI 机制会静默丢弃低权限进程的 SendInput → 什么都不发生。

参考: https://gitee.com/changmenc/ff14_dzt (FF14打字通，纯 SendInput + 管理员运行)

---

## 命令行参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--region` | 自动 | OCR 区域 (left top right bottom) |
| `--window-title` | "最终幻想XIV" | 游戏窗口标题关键词 |
| `--center-ratio` | 0.3 | 屏幕中央区域比例 |
| `--interval` | 0.0 | 循环间隔（秒） |
| `--pause-between` | 0.08 | Enter→输入→Enter 之间间隔 |
| `--max-iterations` | 0 (无限) | 循环上限 |
| `--autostart` | False | 启动即自动开始循环 |

### 悬浮窗快捷键

| 快捷键 | 功能 |
|---|---|
| **Alt+V** | 开始循环 |
| **Shift+V** | 停止循环 |
| **F8** | 切换透明度 (0.55 ↔ 0.88) |
| 鼠标拖动 | 移动悬浮窗位置 |

---

## 技术细节

### win_keys.py (SendInput)

ctypes 结构体必须与 MS 定义对齐：

```python
# 错误: dwExtraInfo 用了 ctypes.POINTER(ctypes.c_ulong) → 64位对齐错误
# 错误: INPUT 没有 _anonymous_ → .U.ki 访问可能失败
# 错误: INPUT_UNION 只有 KEYBDINPUT → INPUT 大小 32 字节 (SendInput 需要 40 字节!)

# 正确定义:
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD),
                ("dwFlags", DWORD), ("time", DWORD),
                ("dwExtraInfo", ctypes.c_void_p)]  # ← 关键

class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ("U",)  # ← 关键
    _fields_ = [("type", DWORD), ("U", INPUT_UNION)]
```

在 x64 上：
- KEYBDINPUT = 24 字节
- INPUT_UNION = 最大成员 MOUSEINPUT = 32 字节
- **INPUT = 40 字节** ← SendInput 要求的大小

### win_driver.py (Interception 驱动)

```
模块加载时:
  1. from win_driver import init → 自动尝试创建 ctx
  2. ctx != NULL → INTERCEPTION_AVAILABLE = True
  3. 枚举 keyboard 设备 (is_keyboard + !is_invalid)
  4. 选第一个可用键盘设备
```

### bring_to_front 窗口激活

```python
# FFXIV 窗口可能抗拒前台切换, 用 AttachThreadInput 辅助:
if fore_tid != cur_tid:
    user32.AttachThreadInput(cur_tid, fore_tid, True)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur_tid, fore_tid, False)
user32.ShowWindow(hwnd, SW_RESTORE)
```

### OCR 识别流程

```
RapidOCR(img) → list of [[[pts], text, conf], ...]
  ↓ pick_word_in_region() 取最靠近屏幕中心的候选
  ↓ 清洗: re.sub(r'[^\u4e00-\u9fff\w]', '', ocr_raw)
  ↓ fuzzy_match_best() SequenceMatcher(ratio ≥ 0.55)
  ↓ 匹配到词库中的词 → 执行输入链
  ↓ 未匹配 → 退回 OCR 原文
```

---

## 踩过的坑 & 解决

| # | 问题 | 根因 | 解决 |
|---|---|---|---|
| 1 | SendInput 返回 0 (静默失败) | INPUT 结构体 union 缺 MOUSEINPUT → 大小不对 (40字节) | union 包含全部三种 + c_void_p + _anonymous_ |
| 2 | SendInput 在 FFXIV 里什么都不发生 | **UIPI 权限隔离！** 游戏 High Integrity, Python Medium Integrity | **以管理员身份运行** |
| 3 | Interception ctx = NULL | 驱动未安装 / 安装后未重启 | install-interception.exe /install → 重启 |
| 4 | install-interception.exe 静默失败 | 需要管理员权限 + 路径有空格 | 用 admin CMD 显式运行 |
| 5 | Python interception API 名不同 | 新版 Python 包删了 get_device_caps | 用 is_keyboard + is_invalid 枚举 |
| 6 | Unicode 输入无效 | SendInput KEYEVENTF_UNICODE 被 Raw Input 忽略 | 管理员权限 → UIPI 不拦截 → Unicode 生效 |
| 7 | 悬浮窗抢焦点 | 置顶线程每 0.6s 强制 SetWindowPos | 加 SWP_NOACTIVATE 标志 |
| 8 | 窗口标题 "FFXIV" 搜不到 | 游戏窗口标题是中文 "最终幻想XIV" | main.py 默认 title 已修正 |

---

## 已知限制

1. **管理员权限**：必须以管理员身份运行（UIPI 权限隔离）
2. **全屏独占**：FFXIV 用全屏独占时，截图/窗口激活可能异常（建议窗口化最大化）

---

## 版本历史

| 日期 | 变更 |
|---|---|
| 2026-10-30 | v1.0: 初版发布，完整端到端验证 |
