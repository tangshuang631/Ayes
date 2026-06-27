# Ayes Local for Windows

Windows 版 Ayes Local 是给 Codex、OpenClaw 或其他本地 Agent 安装的屏幕/进程/窗口/ROI 监控 skill。

如果你是 macOS 用户，请安装仓库里的 `skills/final/ayes-local/`。

## 安装

```powershell
git clone https://github.com/tangshuang631/Ayes.git Ayes
cd Ayes\skills\final\ayes-local-windows
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\install_ayes_local_skill.py --skill-root "$env:USERPROFILE\.codex\skills" --python-bin "$PWD\.venv\Scripts\python.exe"
```

验证：

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" ensure-service
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" contracts
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" status
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1"
```

安装后，Agent 应优先使用安装态绝对 wrapper，而不是先在 PATH 里搜索命令：

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" query --minutes 240 --question "最近在干什么"
```

## 功能

- 全屏监控：基于 `mss` 截取主屏幕。
- 窗口/进程监控：基于 Windows 窗口边界做 best-effort 裁剪采样。
- ROI 子任务：通过 agent 命令创建和管理 ROI。
- 近期回忆：默认使用 `query`，优先轻量索引和记忆，不默认读取原始日志。
- 短期/长期记忆：按任务目录保存。
- 托盘控制：开始、暂停、继续、打开设置、打开数据目录。
- 快捷键配置：截图快捷键和 `Ayes context mode` 提问快捷键。

## 默认数据目录

```text
%USERPROFILE%\.codex\skills\ayes-local\runtime\
```

任务目录：

```text
runtime\tasks\<date>\<task_id>\
  screenshots\latest\
  screenshots\evidence\
  memory\short\
  memory\long\
  logs\
  config\
```

默认不保存逐事件 evidence 截图，只保留少量 latest 帧。

## 当前限制

- 窗口/进程监控第一版使用窗口矩形裁剪，窗口被遮挡或最小化时不保证能捕获真实窗口内容。
- 托盘依赖 `pystray`，设置弹窗依赖 Python 自带 `tkinter`。
- 全局快捷键依赖 `keyboard`，部分系统可能要求管理员权限。
- 本地视觉增强是可选功能，仍依赖用户本机 Ollama 和视觉模型；没有 Ollama 时 OCR 和记忆索引仍可正常工作。Ollama 官网：https://ollama.com。
- 用户也可以直接对 agent 说“启用 Ayes 本地模型增强”，agent 会按 skill 文档检查 Ollama、拉取默认 `qwen2.5vl:7b` 并启用。

更多见 `references/windows.md`。
