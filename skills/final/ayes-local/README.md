# Ayes Local

Ayes Local 是一个 macOS 本地屏幕监控 skill。它让 Codex、OpenClaw 或其他本地 Agent 拥有“可持续观察屏幕的眼睛”：可以监控全屏、某个进程、窗口或 ROI 区域，并在之后回答“刚刚发生了什么”“我刚才看了什么”“这个区域有没有变化”。

第一版只支持 macOS。

## 功能

- 屏幕监控：监控整个屏幕。
- 进程监控：监控指定 App 进程，例如 Chrome、哔哩哔哩、WPS。
- 窗口监控：监控指定窗口。
- ROI 区域监控：在任务截图上框选区域并命名，例如“价格监控”“播放器区域”“错误提示区”。
- 近期回忆：回答最近几分钟发生了什么，默认走轻量 `activity`，节省 token。
- 短期记忆：按任务保存紧凑明细，默认 7 天，最高 14 天。
- 长期记忆：按任务保存简略摘要，默认 14 天，最高 30 天。
- 最新截图证据：按需读取最新真实采样帧，支持未运行任务即时采样。
- 本地视觉增强：可选接入 Ollama 视觉模型，例如 `qwen2.5vl:7b`。
- 企业微信提醒：可选给任务或 ROI 配置 webhook。
- macOS 菜单栏：暂停、继续、打开设置、打开任务目录、创建 ROI、截图快捷键。
- 低写入默认策略：默认 6 秒采样，默认不保存逐事件 evidence 截图。

## 安装到 Codex

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

如果菜单栏启动成功，macOS 右上角会出现 `Ayes ○` 或 `Ayes ◉`。

## 安装到 OpenClaw 或其他 Agent

把 `--skill-root` 换成目标 Agent 的 skills 目录：

```bash
git clone https://github.com/tangshuang631/Ayes.git ayes-local
cd ayes-local
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/install_ayes_local_skill.py --skill-root /path/to/agent/skills --python-bin "$PWD/.venv/bin/python"
```

然后让 Agent 读取并使用安装后的 `ayes-local` skill。

## 第一次使用

安装后可以直接对 Agent 说：

```text
帮我启动一个屏幕监控任务
```

或者：

```text
帮我监控 Chrome 这个进程，任务名叫 Chrome 页面监控
```

Agent 应该先调用：

```bash
ayes-agent-local ensure-service
ayes-agent-local plan-spec ...
ayes-agent-local confirm-plan ...
ayes-agent-local start
```

如果需要菜单栏：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local
```

## 常用教程

### 1. 查看当前有没有监控任务

```bash
ayes-agent-local status
```

### 2. 问最近几分钟发生了什么

```bash
ayes-agent-local activity --minutes 5
```

Agent 回答普通回忆问题时应优先用 `activity`，不要默认读取日志或原始 JSONL。

### 3. 读取更细的短期记忆

```bash
ayes-agent-local memory-items --task-id <task_id> --minutes 5 --limit 5
```

默认返回紧凑结构，过滤 OCR blocks、bbox、evidence_refs 等重字段。

### 4. 读取最新截图证据

```bash
ayes-agent-local screenshot --task-id <task_id>
```

如果任务没有运行，但想按该任务目标即时采样：

```bash
ayes-agent-local screenshot --task-id <task_id> --fresh
```

### 5. 创建 ROI

菜单栏里打开任务子菜单，点击 `设定 ROI...`。Ayes 会即时截取该任务目标，弹出截图框选窗口，拖拽框选后输入 ROI 名称。

Agent 也可以用命令创建：

```bash
ayes-agent-local roi create \
  --task-id <task_id> \
  --roi-name 价格监控 \
  --region "roi_price|价格监控|120|240|360|160|target"
```

### 6. 调整采样和磁盘写入

默认策略已经偏保守：

```bash
ayes-agent-local sampling --interval-sec 6 --quality standard --save-ocr-screenshots false
```

如果长期监控建议使用：

```bash
ayes-agent-local sampling --quality space_saver --save-ocr-screenshots false
```

只有确实需要逐事件原图证据时才开启：

```bash
ayes-agent-local sampling --save-ocr-screenshots true
```

### 7. 开启本地视觉增强

先安装并启动 Ollama，再拉取视觉模型：

```bash
ollama pull qwen2.5vl:7b
```

然后：

```bash
ayes-agent-local vision models
ayes-agent-local vision enable --provider ollama --model qwen2.5vl:7b --auto-use-when-available true
```

如果选择了非视觉模型，Ayes 会自动关闭本地视觉增强。

### 8. 企业微信提醒

给某个任务或 ROI 配 webhook：

```bash
ayes-agent-local task-alert \
  --task-id <task_id_or_roi_task_id> \
  --enabled true \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" \
  --message-title "Ayes 提醒"
```

## 数据目录

默认写入：

```text
$HOME/.codex/skills/ayes-local/runtime/
```

任务目录：

```text
runtime/tasks/<date>/<task_id>/
  screenshots/latest/
  screenshots/evidence/
  memory/short/
  memory/long/
  logs/
  config/
```

默认不上云，默认不保存逐事件 evidence 截图。更多见 `references/privacy.md`。

## 卸载

停止服务和菜单栏：

```bash
pkill -f 'ayes.api.server|uvicorn.*ayes|AyesMenubar|Ayes 菜单栏.app' || true
```

完整卸载：

```bash
rm -rf "$HOME/.codex/skills/ayes-local"
```

如果想先保留数据：

```bash
mv "$HOME/.codex/skills/ayes-local" "$HOME/.codex/skills/ayes-local.backup.$(date +%Y%m%d-%H%M%S)"
```

更多见 `references/uninstall.md`。

## 文档

- `SKILL.md`：给 Agent 看的 skill 入口。
- `references/installation.md`：安装和验证。
- `references/commands.md`：完整命令面。
- `references/troubleshooting.md`：排障。
- `references/privacy.md`：隐私与数据流。
- `references/uninstall.md`：卸载。
- `references/menubar-manual-test.md`：菜单栏手测。
- `references/stress-test.md`：长跑压测方法。
- `references/release-checklist.md`：发行检查清单。

## 当前限制

- 第一版只支持 macOS。
- 需要屏幕录制权限。
- 截图快捷键粘贴需要辅助功能权限。
- 本地视觉增强依赖 Ollama 和视觉模型。
- OCR 和视觉模型不能保证理解所有复杂画面。
- 8 小时长跑压测清单已提供，但是否完成取决于发行方实际执行。
