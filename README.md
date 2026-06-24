# Ayes

Ayes 是一个面向人类用户和 AI Agent 的视觉监控、时序记忆与问答工具。

当前主入口路线：

- `Ayes 本地后台服务`
- `Ayes skill / 本地工具`
- `Ayes 轻量 Web 工作台（配置 + 核验）`

当前仓库先按文档约束落地第一阶段代码骨架：

- `watch spec` 配置契约
- 统一事件模型
- 监控目标数据结构
- macOS 窗口发现最小实现
- 最小 OCR provider 链路
- 最小短期记忆与问答链路
- 面向 Agent 的本地 HTTP API 合同
- 轻量 Web 工作台

## 当前推荐使用方式

1. 启动本地 Ayes 服务
2. 用 Web 工作台选择监控目标与 ROI
3. 装载任务并开始持续监控
4. 通过 Web 工作台做人类核验
5. 通过 Ayes skill 或本地工具把最近截图、事件、记忆和问答结果交给 Codex / Agent

运行测试：

```bash
PYTHONPATH=src python3 -m pytest -q
```

## 当前 MVP 可人工测试步骤

1. 校验 watch spec

```bash
PYTHONPATH=src python3 -m ayes.cli.main validate-spec runtime/mvp-observe-screen.json
```

2. 列出当前窗口候选

```bash
PYTHONPATH=src python3 -m ayes.cli.main list-windows
```

如果要测试窗口监控，可先从输出中挑一个 `window_id`，再生成窗口监控 spec：

```bash
PYTHONPATH=src python3 -m ayes.cli.main create-window-spec 1100 --output runtime/mvp-observe-window.json
```

3. 执行一次最小监控链路

```bash
PYTHONPATH=src python3 -m ayes.cli.main run-once runtime/mvp-observe-screen.json
```

4. 连续执行两次监控并导出事件文件

```bash
PYTHONPATH=src python3 -m ayes.cli.main run-loop runtime/mvp-observe-screen.json --iterations 2 --sleep-seconds 0.2 --dump-path runtime/mvp-events.json
```

5. 检查事件文件

```bash
cat runtime/mvp-events.json
```

当前预期：

- 能完成主屏截图
- 能走通 `Vision OCR`
- 能写出 `text_change` 事件
- 能返回最近短期记忆中的问答结果

6. 测试最小条件监控

```bash
PYTHONPATH=src python3 -m ayes.cli.main check-watch runtime/mvp-triggered-screen.json --minutes 5
```

当前内置样例使用关键词 `Codex`，便于在当前开发环境下更稳定命中。

## 当前 Web 工作台测试步骤

1. 启动本地服务

```bash
cd /Users/apple/Desktop/2026/Ayes
/bin/zsh scripts/start_ayes_service.sh
```

2. 浏览器打开：

```text
http://127.0.0.1:8770/
```

3. 在页面中测试以下链路：

- 点击“监控整个屏幕”
- 点击“执行一次”
- 查看运行状态是否出现 `has_runner: true`
- 查看“近期事件”是否出现 `text_change`
- 查看“问答与短期记忆”是否返回最近结果
- 查看“近期日志”是否追加 `执行一次监控采样`
- 查看“当前截图预览”是否出现最近截图
- 查看页面中的 Agent 入口摘要与 API 合同查看区

4. 窗口目标测试：

- 在左侧窗口列表中点击某个窗口
- 点击“执行一次”
- 观察状态、事件、记忆和日志是否更新

5. 长期摘要测试：

- 先执行一次监控
- 若已启动持续监控，可等待超过长期摘要间隔后再刷新长期摘要，观察运行中是否已出现周期性摘要
- 点击“停止”
- 在左侧 `task_id` 保持最近任务 id
- 在左侧长期摘要小时范围中输入 `24`
- 点击“按小时刷新长期摘要”或“刷新长期摘要”
- 查看“长期摘要”区是否出现该任务的摘要记录，并确认查询上下文中可见 `hours` 范围或最近摘要范围说明

## 当前闭环 smoke

如果本地服务已经启动，可直接运行：

```bash
cd /Users/apple/Desktop/2026/Ayes
python3 scripts/smoke_human_flow.py --base-url http://127.0.0.1:8770
```

如果本地后台还没启动，当前 smoke 会先尝试复用或拉起默认本地服务，再等待 `/api/status` 就绪。

当前 smoke 会验证最小主链路：

- 装载一个带 ROI 的屏幕任务
- 执行一次监控
- 读取 `status`
- 读取 `timeline.recent`
- 读取 `ocr/snippets`
- 读取 `memory/items`
- 读取 `logs`
- 读取 `ask`

## 当前 Agent / Skill 相关接口

读取接口合同：

```bash
curl -s http://127.0.0.1:8770/api/agent/contracts
```

当前建议优先让 Agent 使用：

- `/api/watch/load-configured`
- `/api/watch/start`
- `/api/watch/stop`
- `/api/watch/status`
- `/api/screenshot`
- `/api/timeline/recent`
- `/api/ask`
- `/api/logs`

## ayes-local skill 安装

当前仓库已经内置正式的 `ayes-local` skill 模板和本地安装脚本。

默认安装到 Codex：

```bash
cd /Users/apple/Desktop/2026/Ayes
python3 scripts/install_ayes_local_skill.py
```

安装后将生成：

```text
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local
```

建议先验证：

```bash
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" ensure-service
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" contracts
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" status
```

`ayes-local` 的目标不是替代后台服务，而是让 Codex / OpenClaw / 其他 Agent 可以稳定复用：

- 当前监控状态
- 最近截图证据
- 近期事件时间线
- 短期记忆与长期摘要
- 最近日志

详细安装和命令说明见：

- `docs/20-AyesLocalSkill安装与调用规范.md`
- `skills/ayes-local/references/installation.md`
- `skills/ayes-local/references/commands.md`
- `skills/ayes-local/references/troubleshooting.md`

当前补充能力：

- `/api/timeline/long-term` 已支持可选 `hours` 范围过滤
- `/api/ask` 已支持显式 `hours` 参数，用于超过 15 分钟窗口的长期摘要问答
- 当用户传入 `hours` 时，问答链路会优先走长期轻量记忆层，而不是错误回落到短期记忆

当前阶段的最低通过标准：

- `status_has_runner=true`
- `timeline.recent` 返回 `items`
- `ocr/snippets` 返回 `items`
- `memory/items` 返回 `items`
- `ask` 返回 `answer`
- `ask` 返回 `structured_vision_matches`
- `status` 返回 `last_ocr_quality / last_vision_decision / last_vision_summary`
- 若 timeline/snippet 中存在事件，应尽量带 `preview_overlay`
- 若 timeline 中存在 OCR 或 vision 事件，应尽量能观察到 OCR 质量摘要或 vision 结构化结果
