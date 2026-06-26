# Ayes

Ayes 是一个面向本地 Agent 的 macOS 屏幕、进程和 ROI 监控工具。它让 Codex、OpenClaw 或其他 Agent 可以通过本地 skill 读取最近截图、OCR 事件、短期记忆、长期摘要和告警状态，并回答“刚刚发生了什么”这类带时间维度的问题。

当前第一版发行目标：macOS + 本地 skill。

## 1. 给普通用户的公开发行版

公开 GitHub 仓库建议只发布以下目录的内容：

```text
skills/final/ayes-local/
```

也就是说，公开仓库根目录应长这样：

```text
README.md
SKILL.md
agents/
references/
scripts/
src/
```

不要把开发仓库的 `runtime/`、测试截图、历史任务、日志、数据库或真实 webhook 发布到公开仓库。

用户安装公开发行版：

```bash
git clone https://github.com/tangshuang631/Ayes.git ayes-local
cd ayes-local
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/install_ayes_local_skill.py --skill-root "$HOME/.codex/skills" --python-bin "$PWD/.venv/bin/python"
```

验证：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local ensure-service
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local contracts
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local status
$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local
```

OpenClaw 或其他 Agent：

```bash
.venv/bin/python scripts/install_ayes_local_skill.py --skill-root /path/to/agent/skills --python-bin "$PWD/.venv/bin/python"
```

## 2. Ayes Local 能做什么

- 监控整个屏幕、指定进程、指定窗口。
- 给任务创建 ROI 子任务，只监控某个区域。
- 回答最近几分钟做了什么、看了什么、页面有什么变化。
- 基于短期紧凑明细和长期简略摘要做回忆。
- 按需读取最新截图证据。
- 可选接入 Ollama 本地视觉模型增强复杂画面理解。
- 可选配置企业微信 webhook 做条件提醒。
- 菜单栏支持暂停、继续、设置、任务目录、ROI 框选和截图快捷键。

## 3. 默认安全策略

- 默认采样间隔 6 秒。
- 默认采样质量 `standard`。
- 默认不保存逐事件 evidence 截图。
- `screenshots/latest/` 只保留少量最新帧。
- 运行数据写入安装目录下的 `runtime/`，不会写入公开仓库或开发仓库。
- 发行态 skill 不携带任务、历史截图、记忆、日志、webhook 或已启用视觉增强配置。

## 4. 开发仓库使用方式

开发时可直接从本仓库安装当前发行态：

```bash
python3 scripts/install_ayes_local_skill.py --repo-root "$(pwd)" --skill-root "$HOME/.codex/skills"
```

运行测试：

```bash
PYTHONPATH=src python3 -m pytest -q
```

## 5. 同步发行态

`skills/final/ayes-local/` 是准备复制到公开 GitHub 仓库的自包含发行目录。它应包含：

- `README.md`
- `requirements.txt`
- `SKILL.md`
- `agents/openai.yaml`
- `references/*.md`
- `scripts/install_ayes_local_skill.py`
- `scripts/run_ayes_service.py`
- `src/ayes/`

当 `src/ayes` 或安装脚本变更后，需要同步到 `skills/final/ayes-local/`，再发布公开仓库。

## 6. 发行前检查

发行前至少检查：

```bash
PYTHONPATH=src python3 -m pytest -q tests/cli/test_install_ayes_local_skill.py
PYTHONPATH=src python3 -m pytest -q
```

并阅读：

- `skills/final/ayes-local/references/release-checklist.md`
- `skills/final/ayes-local/references/privacy.md`
- `skills/final/ayes-local/references/uninstall.md`
- `skills/final/ayes-local/references/menubar-manual-test.md`
- `skills/final/ayes-local/references/stress-test.md`

## 7. 当前限制

- 第一版只支持 macOS。
- 需要 macOS 屏幕录制权限。
- 截图快捷键粘贴需要辅助功能权限。
- 本地视觉增强依赖用户本机 Ollama 和视觉模型。
- 8 小时长跑压测清单已提供，但公开发行前是否完成取决于发行方实际执行。
