# Windows 使用说明

## 入口

安装后主要入口：

```powershell
%USERPROFILE%\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1
%USERPROFILE%\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1
```

Agent 应优先使用 `ayes-agent-local.ps1 query` 回答普通回忆问题，只有需要细节、证据或排障时才逐步读取 `memory-items`、`screenshot` 或 `logs`。

## 托盘菜单

Windows 托盘提供：

- 状态显示：未运行、已装载、监控中、已暂停。
- 确保服务启动。
- 开始 / 继续当前任务。
- 暂停监控。
- 继续上次的监控。
- 设置。
- 打开数据目录。
- 退出控制面。

设置窗口可以调整采样间隔、采样质量、是否保存 evidence 截图、截图快捷键和提问快捷键。

## 捕获策略

- 全屏：使用 `mss` 采样主屏幕。
- 窗口/进程：使用窗口边界做屏幕裁剪。
- 如果窗口被遮挡、最小化或在虚拟桌面外，Windows 第一版可能只能返回不可观测或裁剪到遮挡后的画面。

这是产品第一版的明确限制；后续可以升级到 Win32 PrintWindow / Windows Graphics Capture。

## 依赖

```powershell
pip install -r requirements.txt
```

关键依赖：

- `mss`：屏幕截图。
- `pygetwindow`：窗口候选。
- `psutil`：进程信息。
- `pystray`：系统托盘。
- `keyboard`：快捷键。
- `rapidocr-onnxruntime`：OCR。

## 隐私和数据

默认运行数据写在安装后的 skill 目录：

```text
%USERPROFILE%\.codex\skills\ayes-local\runtime\
```

默认不上云，默认不保存逐事件原图证据。用户开启 webhook 或 Ollama 视觉增强时，才会调用对应本地或外部服务。
