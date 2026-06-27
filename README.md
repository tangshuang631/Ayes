# Ayes

Ayes 是一个面向本地 Agent 的屏幕、进程、窗口和 ROI 监控 skill。它让 Codex、OpenClaw 或其他 Agent 可以通过本地服务读取最近截图、OCR 事件、短期记忆、长期摘要和告警状态，并回答“刚刚发生了什么”“我刚才看了什么”这类带时间维度的问题。

当前发行目标：

- macOS：正式支持，菜单栏控制面较完整。
- Windows：第一版支持，提供托盘控制面；窗口/进程捕获使用 best-effort 窗口矩形裁剪。

## 1. 选择发行目录

公开仓库里保留两个自包含 skill 发行目录：

```text
skills/final/ayes-local/          # macOS
skills/final/ayes-local-windows/  # Windows
```

Agent 或用户拿到仓库链接后，应先判断系统：

- macOS 用户安装 `skills/final/ayes-local/`
- Windows 用户安装 `skills/final/ayes-local-windows/`

不要发布或安装开发仓库里的 `runtime/`、测试截图、历史任务、日志、数据库或真实 webhook。

## 2. macOS 安装

```bash
git clone https://github.com/tangshuang631/Ayes.git Ayes
cd Ayes/skills/final/ayes-local
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/install_ayes_local_skill.py --skill-root "$HOME/.codex/skills" --python-bin "$PWD/.venv/bin/python"
```

安装器会把安装态 wrapper 绑定到你执行安装时使用的 Python 解释器；因此安装完成后，新窗口里的 agent 应优先直接使用安装后的绝对 wrapper，而不是先搜索 PATH 或手动补 `PYTHONPATH`。

验证：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local ensure-service
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local contracts
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local status
$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local
```

## 3. Windows 安装

```powershell
git clone https://github.com/tangshuang631/Ayes.git Ayes
cd Ayes\skills\final\ayes-local-windows
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\install_ayes_local_skill.py --skill-root "$env:USERPROFILE\.codex\skills" --python-bin "$PWD\.venv\Scripts\python.exe"
```

Windows 版同样会把安装态 PowerShell wrapper 绑定到安装时传入的 Python 解释器。

验证：

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" ensure-service
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" contracts
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" status
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1"
```

## 4. Ayes 能做什么

- 监控整个屏幕、指定进程、指定窗口。
- 给任务创建 ROI 子任务，只监控某个区域。
- 回答最近几分钟做了什么、看了什么、页面有什么变化。
- 基于短期紧凑明细和长期简略摘要做回忆。
- 按需读取最新截图证据。
- 可选接入 Ollama 本地视觉模型增强复杂画面理解。
- 可选配置企业微信 webhook 做条件提醒。
- macOS 菜单栏 / Windows 托盘支持暂停、继续、设置、任务目录、快捷键和数据目录入口。

## 5. 默认安全策略

- 默认采样间隔 6 秒。
- 默认采样质量 `standard`。
- 默认不保存逐事件 evidence 截图。
- `screenshots/latest/` 只保留少量最新帧。
- 运行数据写入安装目录下的 `runtime/`，不会写入公开仓库或开发仓库。
- 发行态 skill 不携带任务、历史截图、记忆、日志、webhook 或已启用视觉增强配置。
- Agent 普通回忆问题默认使用 `query`，不默认读取原始 JSONL、OCR blocks、bbox、截图列表或日志。

## 6. 开发仓库使用方式

开发时可直接从本仓库安装当前 macOS 发行态：

```bash
python3 scripts/install_ayes_local_skill.py --repo-root "$(pwd)" --skill-root "$HOME/.codex/skills"
```

运行测试：

```bash
PYTHONPATH=src python3 -m pytest -q
```

同步发行态时，核心源码应同步到：

```text
skills/final/ayes-local/src/ayes/
skills/final/ayes-local-windows/src/ayes/
```

## 7. 当前限制

- macOS 需要屏幕录制权限；截图快捷键粘贴需要辅助功能权限。
- Windows 窗口/进程监控第一版使用窗口矩形裁剪，窗口被遮挡或最小化时不保证能捕获真实窗口内容。
- Windows 托盘依赖 `pystray`，设置弹窗依赖 `tkinter`，快捷键依赖 `keyboard`。
- 本地视觉增强依赖用户本机 Ollama 和视觉模型。
- 8 小时长跑压测清单已提供，但公开发行前是否完成取决于发行方实际执行。
