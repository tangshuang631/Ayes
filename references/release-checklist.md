# Ayes Local 发行前检查清单

当前第一版发行目标：macOS + Codex/OpenClaw 本地 skill。公开 GitHub 仓库根目录就是 `ayes-local` 发行态目录。

## 1. 发行态目录

- `SKILL.md` 存在。
- `README.md` 存在。
- `requirements.txt` 存在。
- `agents/openai.yaml` 存在。
- `scripts/install_ayes_local_skill.py` 存在。
- `scripts/run_ayes_service.py` 存在。
- `src/ayes/` 存在。
- `references/installation.md` 存在。
- `references/commands.md` 存在。
- `references/troubleshooting.md` 存在。
- `references/privacy.md` 存在。
- `references/uninstall.md` 存在。
- `references/menubar-manual-test.md` 存在。
- `references/stress-test.md` 存在。
- 发行态目录不包含 `runtime/`、数据库、真实 webhook、历史截图、任务记忆或日志。

## 2. 安装

```bash
python3 scripts/install_ayes_local_skill.py
```

验证：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local ensure-service
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local contracts
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local status
```

## 3. macOS 权限

- 屏幕录制权限可触发并允许。
- 辅助功能权限可用于快捷键粘贴。
- 本地服务可监听 `127.0.0.1:8770`。

## 4. 菜单栏

按 `references/menubar-manual-test.md` 完整手测：

- 图标可见。
- 设置可打开和保存。
- 任务列表可展开。
- 开始/暂停/继续可点击一次生效。
- ROI 可通过最新截图框选并创建。
- 打开目录进入任务专属目录。

## 5. 核心 Agent 流程

- `plan-spec` 能生成问题和 setup guidance。
- `confirm-plan` 能装载任务。
- `start/stop/status` 可用。
- `activity` 可回答最近活动。
- `memory-items` 默认紧凑输出。
- `screenshot --fresh --task-id ...` 可对未运行任务即时采样。
- `roi list/create/update/delete` 可用。
- `task-alert` 可配置 webhook，但发行模板不预置真实 webhook。

## 6. 默认写入策略

- 默认采样间隔为 6 秒。
- 默认 `quality=standard`。
- 默认 `save_ocr_screenshots=false`。
- `screenshots/latest/` 只保留少量最新帧。
- `screenshots/evidence/` 默认不写入。

## 7. 不在第一版承诺

- Windows/Linux 支持。
- 8 小时压测已完成。
- 云端同步。
- 企业微信真实 webhook 在所有网络环境下必达。
- OCR/视觉模型对所有页面都准确理解。

这些属于后续硬化或增强项。
