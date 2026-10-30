# FF14 Keybound Brawler Bot

> FFXIV 魔光键影活动 OCR 自动打字发送辅助工具

一个帮你在魔光键影活动里自动识别敌人头顶文字、自动打进聊天框发送的 Python 小工具。

## ✨ 效果

准备就绪 | 识别并发送
:---: | :---:
![screenshot_ready](docs/screenshot_ready.png) | ![screenshot_sending](docs/screenshot_sending.png)

## 🎯 它怎么工作

```
截取游戏屏幕中央
  → RapidOCR 识别敌人头顶文字
  → 1210 条 FFXIV 词库模糊匹配
  → 自动按 Enter 打开聊天框
  → SendInput 注入中文
  → 自动 Enter 发送
  → 循环不停
```

## 🚀 快速开始

### 1. 安装依赖

```powershell
pip install -r requirements.txt
```

### 2. 以管理员身份运行（必须！）

FFXIV 以管理员身份运行，Windows 的 UIPI 权限隔离会让非管理员进程的模拟按键被**静默丢弃**——看起来程序在跑，游戏里什么都没发生。

**右键 `启动_管理员.bat` → 以管理员身份运行**

或者：

```powershell
# 管理员 CMD / PowerShell
python main.py --autostart
```

### 3. 进入魔光键影关卡后

- **Alt+V** — 开始自动循环
- **Shift+V** — 停止
- **F8** — 切换悬浮窗透明度

就不用管了，它会自动识别、自动打字、自动发送。

## ⚙️ 常用参数

```powershell
# 自定义循环间隔和发送次数
python main.py --autostart --interval 2.0 --max-iterations 30

# 指定 OCR 区域 (left top right bottom)
python main.py --region 600 400 1300 750

# 自定义窗口标题关键词
python main.py --window-title "最终幻想XIV"
```

## 📦 项目结构

```
FF14-Keybound-Brawler-Bot/
├── main.py              # 悬浮窗主程序
├── win_driver.py        # Interception 驱动注入封装
├── win_keys.py          # SendInput 回退实现
├── words.txt            # 1210 条 FFXIV 词汇
├── docs/TECHNICAL.md    # 技术文档（架构、原理、踩坑记录）
└── README.md
```

## ⚠️ 注意事项

- **管理员权限** — 非管理员运行 = SendInput 被 UIPI 静默丢弃 = 游戏里什么都不发生
- **窗口化/无边框** — 全屏独占时截图可能失败，建议设成窗口化最大化
- **输入法** — 不需要手动切中文输入法，程序直接灌 Unicode 字符

## 🔧 技术细节 & 原理

想看底层实现、为什么 Interception 驱动需要重启、SendInput 的 ctypes 结构体到底怎么对齐的？

👉 [docs/TECHNICAL.md](docs/TECHNICAL.md)

## 📜 License

MIT
