# Desktop Clock — Windows 桌面水印时钟

> 屏幕右下角、任务栏上方的极简水印时钟。透明背景，只有文字浮在桌面上。NTP 同步的 UTC+8 时间，精确到秒，与系统时区设置无关。

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

## 预览

```
19:42:08
2026-09-02 Tue
```

> 透明背景、无边框、始终置顶，像水印一样贴在任务栏上方，不遮挡任何窗口内容。

- 截图占位：建议放置 `screenshot.png`（右下角水印效果 + 托盘图标 T）

## 特性

- **真·水印效果** — `UpdateLayeredWindow` + 32 位 BGRA per-pixel alpha，文字抗锯齿边缘平滑融合，无色键锯齿
- **NTP 精准授时** — `ntp.aliyun.com` → `pool.ntp.org` → `time.windows.com` 三级容灾，算法 `offset = ((t2-t1)+(t3-t4))/2`，每小时自动重同步，失败静默回退系统时间
- **固定 UTC+8** — 不跟随系统时区，适合需要北京时间的场景
- **高 DPI 适配** — `SetProcessDpiAwareness(2)` + 系统 DPI 校正，Pillow 72dpi 与 tkinter 点阵对齐
- **极低打扰** — 200ms 刷新、5 秒自动重停靠、托盘仅一个 `T` 图标（Sync now / Exit）
- **可配置** — 字号 / 颜色 / 透明背景三档可调

## 环境要求

- Windows 10 / 11
- Python 3.8+（需 `tkinter`，官方安装包默认自带）
- 依赖：`pystray` + `Pillow`

## 快速开始

```bat
git clone https://github.com/D6326/desktop-clock.git
cd desktop-clock

pip install -r requirements.txt

:: 手动启动（无黑窗）
run.bat

:: 或直接
pythonw desktop_clock.py
```

> `pythonw.exe` 不会弹出命令行窗口；用 `python.exe` 会多一个黑窗。

## 开机自启

```bat
install_startup.bat    :: 安装 — 在 shell:startup 生成 DesktopClock.vbs
uninstall_startup.bat  :: 移除
```

原理：`install_startup.bat` 用 `%~dp0` 动态生成 `DesktopClock.vbs` 到 `shell:startup` 目录，路径永远指向当前安装位置。**移动文件夹后只需重新双击 `install_startup.bat` 即可，无需改任何文件。** `launch.vbs` 仅作参考保留。

## 配置

首次运行会自动生成 `clock_config.json`，不存在时使用内置默认值。

```json
{
  "font_size": 12,
  "color": "#cccccc",
  "transparent": true
}
```

| 字段 | 说明 |
|---|---|
| `font_size` | 字号（px，Pillow 渲染前会按系统 DPI 换算） |
| `color` | 文字颜色，`#cccccc` 浅灰 / `#ffffff` 纯白 / `#888888` 更低调 |
| `transparent` | `true` 透明背景（水印） / `false` 深色半透明背景 `rgba(24,24,24,0.75)` |

修改后重启时钟生效。

## 技术细节

| 模块 | 说明 |
|---|---|
| 透明窗口 | `WS_EX_LAYERED \| WS_EX_TRANSPARENT \| WS_EX_TOOLWINDOW` + `UpdateLayeredWindow(ULW_ALPHA)`，BGRA 预乘 alpha |
| 定位 | `FindWindowW("Shell_TrayWnd")` 获取任务栏矩形，计算右下角坐标；`after(5000)` 周期性重停靠 |
| 字体 | 优先 `consola.ttf` → `consolab.ttf` → `cour.ttf`，均尝试 `WINDIR/Fonts` 回退，最后 `ImageFont.load_default()` |
| 托盘 | `pystray`，缺失时静默降级（无托盘也能跑） |

## 项目结构

```
desktop-clock/
├── desktop_clock.py          主程序（水印时钟）
├── run.bat                   双击启动
├── launch.vbs                VBS 静默启动参考
├── install_startup.bat       安装开机自启
├── uninstall_startup.bat     移除开机自启
├── clock_config.json         运行时配置（自动生成，已 gitignore）
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
└── TaskbarClock/             遗留方案：C# DeskBand（仅 Win10）
    ├── TaskbarClock.cs
    ├── build.bat
    ├── register.bat
    └── unregister.bat
```

## 遗留方案 TaskbarClock

`TaskbarClock/` 是早期 C# `IDeskBand2` COM 方案，可把时钟嵌入任务栏内部。Windows 11 已移除任务栏 Toolbars 菜单，无法启用，仅在 Windows 10 上可用，保留作参考。

```bat
cd TaskbarClock
build.bat              :: 编译 TaskbarClock.dll（需 .NET Framework csc.exe）
register.bat           :: 管理员身份注册
unregister.bat         :: 注销
```

## 常见问题

**时钟不显示？** 检查是否被其他置顶窗口遮挡；确认 `pythonw` 进程在任务管理器中存在。

**NTP 同步失败？** 内网或防火墙可能拦截 UDP 123，会自动回退到系统时间；托盘点 Sync now 可手动重试。

**想改位置？** 修改 `desktop_clock.py` 中 `_dock()` 的 `-10` / `-8` 边距。

**高分屏文字模糊？** 已做 DPI 感知，若仍模糊请检查系统缩放是否为非整数（如 125%）。

## 路线图

- [ ] 天气信息
- [ ] 多时区
- [ ] 跟随系统主题切换文字颜色
- [ ] 自定义日期格式

## 许可证

[MIT](./LICENSE)
