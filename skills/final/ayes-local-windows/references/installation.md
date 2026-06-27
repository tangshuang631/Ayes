# Windows 安装

## 安装到 Codex

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

## 安装到其他 Agent

把 `--skill-root` 换成对应 Agent 的 skills 目录。安装后的 skill 名仍是 `ayes-local`，这样 agent 可以复用同一套触发规则。

## 运行目录

默认运行数据写到：

```text
%USERPROFILE%\.codex\skills\ayes-local\runtime\
```

安装脚本会保留已有 `runtime\`，覆盖代码和文档时不会删除历史任务数据。
