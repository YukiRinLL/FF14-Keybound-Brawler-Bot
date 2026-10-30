# FFXIV 魔光键影自动发送辅助

> 屏幕中央 OCR 识别 → 词库模糊匹配 → Interception 驱动级键盘注入 → 自动 Enter → 粘贴 → Enter 发送

---

## 🎯 功能

1. **悬浮窗**：置顶、半透明、可拖动、Alt+V 开始/Shift+V 停止
2. **RapidOCR 识别**：每秒截图游戏屏幕中央区域，识别文字
3. **词库模糊匹配**：1210 条 FFXIV 词汇，SequenceMatcher 相似度 ≥ 0.55
4. **Interception 驱动级注入**：FFXIV 用 Raw Input API 独占键盘，必须内核驱动级注入
5. **自动发送链**：Enter 开聊天框 → 写剪贴板 → 驱动级 Ctrl+V → Enter 发送

---

## 📁 项目结构

```
e:\魔光键影\
├── main.py                  # 悬浮窗主程序 (OCR+匹配+循环)
├── win_driver.py            # Interception 驱动级注入封装
├── win_keys.py              # SendInput 回退实现
├── words.txt                # 1210 条 FFXIV 词汇
├── requirements.txt         # Python 依赖
├── interception_driver/     # Interception 驱动安装包 (已安装)
└── README.md                # 本文档
```

---

## 🔌 Interception 驱动注入原理

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

## 📦 扫描码表 (Set 1)

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

## 🔤 中文输入方案

**FFXIV 聊天框禁用了 Ctrl+V 粘贴**，但驱动级 Ctrl+V 是有效的。输入链：

```
1. 驱动级 Enter (scan 0x1C) → 打开聊天框
2. pyperclip.copy("给我魔晶石") → 写系统剪贴板
3. 驱动级 Ctrl (0x1D) DOWN → V (0x2F) DOWN → V UP → Ctrl UP
4. 驱动级 Enter (scan 0x1C) → 发送
```

其他方案对比：

| 方案 | 效果 | 备注 |
|---|---|---|
| SendInput KEYEVENTF_UNICODE | ❌ | 被 Raw Input 忽略 |
| IMM32 ImmSetCompositionString | ❌ | ImmGetContext 返回 NULL |
| 驱动级逐字符扫描码 | ❌ | 中文无对应扫描码 |
| **驱动级 Ctrl+V 剪贴板** | ✅ | 剪贴板走系统层，游戏不拦截 |

---

## 🚀 快速开始

### 前置条件

```powershell
# 1. 安装 Interception 驱动 (管理员 CMD)
cd "e:\魔光键影\interception_driver\Interception\command line installer"
install-interception.exe /install
# 输出 "Interception successfully installed. You must reboot for it to take effect."
# 重启电脑！

# 2. 以管理员身份运行 (必须!)
:: 右键 "启动_管理员.bat" → 以管理员身份运行
:: 或在管理员 CMD 里: python main.py --autostart
```

### 输入方案 (已验证)

```
SendInput KEYEVENTF_SCANCODE  → Enter 开聊天框 (Set 1 扫描码)
SendInput KEYEVENTF_UNICODE  → 灌 Unicode 中文字符
SendInput KEYEVENTF_SCANCODE  → Enter 发送
```

**关键：必须管理员身份运行！**
FFXIV 以 High Integrity 运行，普通 Python 是 Medium Integrity。
Windows UIPI 机制会静默丢弃低权限进程的 SendInput → 什么都不发生。
管理员身份运行后，和游戏同权限 → SendInput 正常工作。
参考: https://gitee.com/changmenc/ff14_dzt (FF14打字通，纯 SendInput 方案)

### 运行

```powershell
# 正常模式（悬浮窗出来后手动按 Alt+V 开始）
python e:\魔光键影\main.py

# 自动开始循环
python e:\魔光键影\main.py --autostart

# 自定义参数
python e:\魔光键影\main.py --autostart --interval 2.0 --pause-between 0.3 --max-iterations 20
```

### 命令行参数

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

## 🔧 技术细节

### win_keys.py (SendInput 回退)

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

do_action():
  INTERCEPTION_AVAILABLE = True  →  驱动级 Enter + 剪贴板 Ctrl+V
  INTERCEPTION_AVAILABLE = False →  SendInput 回退 (VK 模式)
```

### bring_to_front 窗口激活

```python
# FFXIV 窗口: HWND=460772, title='最终幻想XIV'
# 游戏可能抗拒前台切换, 用 AttachThreadInput 辅助:

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

## 🐛 踩过的坑 & 解决

| # | 问题 | 根因 | 解决 |
|---|---|---|---|
| 1 | SendInput 返回 0 (静默失败) | INPUT 结构体 union 缺 MOUSEINPUT → 大小不对 (40字节) | union 包含全部三种 + c_void_p + _anonymous_ |
| 2 | SendInput 在 FFXIV 里什么都不发生 | **UIPI 权限隔离！** 游戏 High Integrity, Python Medium Integrity | **以管理员身份运行 main.py** |
| 3 | Interception ctx = NULL | 驱动未安装 / 安装后未重启 | install-interception.exe /install → 重启 |
| 4 | install-interception.exe 静默失败 | 需要管理员权限 + 路径有空格 | 用 admin CMD 显式运行 |
| 5 | Python interception API 名不同 | 新版 Python 包删了 get_device_caps | 用 is_keyboard + is_invalid 枚举 |
| 6 | Unicode 输入无效 | SendInput KEYEVENTF_UNICODE 被 Raw Input 忽略 | 驱动级 Ctrl+V 剪贴板 |
| 7 | 中文扫描码不存在 | 中文无硬件扫描码 | 驱动级 Enter + 剪贴板 + Ctrl+V 组合 |
| 8 | Ctrl+V 粘贴游戏禁了 | 游戏过滤标准粘贴消息 | 驱动级扫描码 Ctrl+V 绕过过滤 |
| 9 | 悬浮窗抢焦点 | 置顶线程每 0.6s 强制 SetWindowPos | 加 SWP_NOACTIVATE 标志 |
| 10 | 窗口标题 "FFXIV" 搜不到 | 游戏窗口标题是中文 "最终幻想XIV" | main.py 默认 title 已修正 |

---

## ⚠️ 已知限制

1. **必须重启**：Interception 内核驱动安装后必须重启生效
2. **管理员权限**：驱动安装器需要管理员权限
3. **魔光键影模式**：游戏内特定模式下可能无法输入（待调查）
4. **全屏独占**：FFXIV 用全屏独占时，截图/窗口激活可能异常（建议窗口化最大化）
5. **Windows 重启后**：驱动自动加载，但 main.py 每次运行需重新调用 interception_create_context

---

## 🧪 验证 Checklist

- [x] Interception 驱动安装 + ctx 创建成功
- [x] 驱动级 Enter → FFXIV 聊天框弹出
- [x] 驱动级 Ctrl+V → 中文粘贴进聊天框
- [x] 驱动级 Enter → 发送消息
- [x] RapidOCR 屏幕中央区域识别正常
- [x] 1210 词库模糊匹配正常
- [x] main.py 悬浮窗正常 (置顶/半透明/可拖动)
- [x] Alt+V 开始 / Shift+V 停止 正常
- [ ] 魔光键影模式输入（待调查）

---

## 版本历史

| 日期 | 变更 |
|---|---|
| 2026-10-29 | 初版：main.py + win_driver.py + win_keys.py + 驱动安装 + 完整端到端 |
