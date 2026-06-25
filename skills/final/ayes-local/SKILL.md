---
name: ayes-local
description: Use when the user wants Codex to watch a local screen, process, or ROI over time, ask what happened in the last few minutes, inspect screenshot evidence, or control an existing Ayes monitoring task through the local Ayes service.
---

# Ayes Local

这是给最终用户安装的正式无状态 skill 产物。

安装完成后的默认约束：

- skill 包本身不携带任何用户任务、webhook、历史截图、记忆或运行日志
- 默认没有已创建任务
- 默认没有已写入的企业微信 webhook
- 默认没有已启用的本地视觉增强
- 只有默认推荐模型信息 `qwen2.5vl:7b` 会作为引导信息暴露给 agent，但不代表已经安装或启用

因此，用户第一次安装后应能直接对 agent 说：

- “帮我启动一个监控任务”
- “帮我做一个触发提醒任务”
- “帮我开启本地大模型增强”

如果缺配置，agent 必须通过对话和正式命令面逐步补齐，而不是假设这些配置已经存在。

## When to Use

Use this skill when the request is about:

- 最近几分钟某个受监控进程发生了什么
- 当前有没有弹窗、报错、价格变化、状态变化
- 读取最近截图证据和相关事件
- 开始、停止、确认当前监控任务状态
- 基于已有监控任务继续追问
- 通过与 agent 对话完成 webhook、本地视觉增强、ROI、刷新点击等配置补齐
- 恢复之前配置过并运行过的任务，或在多个任务之间切换、删除

不要在以下情况直接硬调 Ayes：

- 用户还没有选好目标或 ROI
- 本地 Ayes 服务还没启动
- 用户需要先人工确认预览图是不是正确目标

这些情况应先引导用户打开 Ayes Web 工作台处理配置与核验。

## Default Workflow

1. 先读 `references/installation.md`，确认本机已安装 `ayes-local` 和 `ayes-agent-local` 包装脚本。
2. 先用 `ayes-agent-local ensure-service` 或 `ayes-agent-local status` 确认本地服务可达。
2. 如果用户是在追问最近情况：
   - 先读 `ayes-agent-local observe-live --minutes 5 --limit 20`
   - 优先使用返回的 `status / screenshot / recent_events / memory_items / alerts / logs / evidence_status / agent_hints`
   - 如果问题和提醒有关，再按需补读 `ayes-agent-local alerts`
   - 如果需要更细证据，再补 `ayes-agent-local memory-items`、`ayes-agent-local recent` 和 `ayes-agent-local logs`
   - 最后用 `ayes-agent-local ask --question "..."` 组织回答
3. 如果用户要求开始或恢复监控：
   - 如果用户给的是自然语言任务，先用 `ayes-agent-local plan-spec ...`
   - 优先读取返回的 `questions[]`
   - 同时读取 `setup_guidance[]`
   - 按顺序逐条补问，不要跳过 required 问题
   - 读取 `region_intents[]`，用来确认“价格区/库存区/报错区”等区域用途
   - 如果出现 `region_binding` 问题，优先去拿外部选择器或截图标注器返回的 `region_bindings[]`
   - 读取 `action_intents[]`，用来确认是否启用 refresh_click 以及还缺什么
   - 再读取 `missing_fields / ambiguities / confirmation_summary`
   - 如果 webhook、本地视觉模型或其他依赖没配好，不要只报错结束；要根据 `setup_guidance[]` 用对话反复指导用户完成配置，并在条件满足后继续推进任务装载
   - 如果用户要求自定义企业微信消息内容，要继续补问消息标题或模板，再通过正式命令面写入任务配置
   - 让用户确认或补齐缺失项后，再用 `ayes-agent-local confirm-plan ...`
   - 如果已经有明确结构化 spec，也可以继续用 `ayes-agent-local load-spec ...`
   - 再用 `ayes-agent-local start`
4. 如果用户要求停止持续监控：
   - 用 `ayes-agent-local stop`
5. 如果用户说“继续之前那个任务”“恢复昨天那个价格监控”“切到另一个任务”：
   - 先用 `ayes-agent-local tasks`
   - 再结合任务名、日期、目标和最近活动时间定位历史任务
   - 用 `ayes-agent-local switch-task --task-id ...` 恢复该任务
   - 后续追问优先显式带上 `--task-id`
6. 如果用户要求删除某个任务及其长短期记忆：
   - 先确认要删除的具体 `task_id`
   - 再用 `ayes-agent-local delete-task --task-id ...`
7. 如果用户希望通过小图标手动暂停、恢复或打开数据目录：
   - 在 macOS 上优先运行 `~/.codex/skills/ayes-local/scripts/ayes-menubar-local`
   - 若已安装全局入口，也可直接运行 `ayes-menubar`
   - 菜单栏可进入 ROI 管理、设置、暂停/恢复、任务切换和数据目录
   - 但任务编排、证据回读和大部分交互仍应优先通过 agent 完成

更完整的安装、命令和排障细节，按需继续读取：

- `references/installation.md`
- `references/commands.md`
- `references/troubleshooting.md`

## Tooling

优先使用本地工具：

```bash
ayes-agent-local ensure-service
ayes-agent-local contracts
ayes-agent-local region-bind-contract
ayes-agent-local status
ayes-agent-local plan-spec --task-id task_web --prompt "帮我监控 Safari 里的商品价格低于 299 时提醒我" --target-type process --process-name Safari
ayes-agent-local confirm-plan --plan-file /tmp/task_web.plan.json --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
ayes-agent-local observe-live --task-id task_web --minutes 5 --limit 20
ayes-agent-local recent --task-id task_web --minutes 5 --limit 20
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local screenshot --task-id task_web
ayes-agent-local ask --task-id task_web --minutes 5 --question "最近几分钟发生了什么"
ayes-agent-local memory-items --task-id task_web --minutes 5 --limit 20
ayes-agent-local logs --task-id task_web --minutes 15
ayes-agent-local run-once
ayes-agent-local start
ayes-agent-local stop
ayes-agent-local control status
ayes-agent-local control pause-all
ayes-agent-local control resume-all
ayes-agent-local control cleanup-reminder-check
ayes-agent-local control cleanup-reminder --next-check-after-days 7
ayes-agent-local vision prepare --requested-by agent_enable_local_vision
ayes-agent-local vision enable --provider ollama --model qwen2.5vl:7b --auto-use-when-available true
ayes-agent-local vision status
$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local
ayes-menubar
```

注意：`ayes-agent-local start` 在默认本地地址下会尽力自动拉起 macOS 菜单栏控制入口；失败不会阻断监控。`screenshot` 返回的 `path` 应是最近真实采样帧的唯一文件名，不要把固定兼容文件当作最新证据。

如果没有安装 `ayes-agent-local`，可暂时回退到仓库内命令：

```bash
PYTHONPATH=src python3 -m ayes.cli.agent_tool status
```

若连本地命令也不可用，再回退到等价的本地 HTTP API：

- `/api/agent/contracts`
- `/api/watch/status`
- `/api/agent/observe-live`
- `/api/watch/task/{task_id}`
- `/api/timeline/recent`
- `/api/alerts/recent`
- `/api/timeline/long-term`
- `/api/memory/items`
- `/api/logs`
- `/api/screenshot`
- `/api/ask`
- `/api/watch/start`
- `/api/watch/stop`

## Response Pattern

给用户回答时优先输出：

1. 当前看的是哪个任务 / 哪个目标
2. 时间范围
3. 关键证据事件
4. 结论
5. 如果证据不足，明确说证据不足并指出应该回到工作台调整哪里

如果用户问的是“有没有通知到我”或“为什么没通知”，不要只看普通事件，必须优先结合：

- `observe-live` 中的 `alerts / logs / evidence_status`
- 最近告警审计结果
- 近期日志
- 相关截图与时间范围

不要把 Ayes 当成无边界视觉理解系统。它当前的核心仍是：

- OCR 主链路
- 时序事件
- 短期 / 长期记忆
- 按需视觉增强
- 对话式任务草案与配置确认流

并且这条 skill 的目标不是“告诉用户去哪里自己配置”，而是：

- 优先通过 `questions[]`、`setup_guidance[]` 和正式命令面把配置一步步补齐
- 当用户第一次没配好时继续指导
- 配置一旦满足就继续推进任务，而不是让流程中断

实时观察时的优先证据顺序：

1. `observe-live.evidence_status` 判断当前证据是否可用
2. `observe-live.screenshot` 判断最近截图、目标和 ROI
3. `observe-live.recent_events` 读取最近事件时间线
4. `observe-live.memory_items` 读取短期记忆明细
5. `observe-live.alerts / logs` 排查提醒和后台错误

补问时的顺序要求：

1. 先问目标是否正确
2. 再问是否监控整个目标还是重点区域
3. 如果是多区域，按 `region_intents[]` 逐条确认区域名称和用途
4. 如果出现 `region_binding` 问题，去拿 `region_bindings[]`，不要让用户口头报像素坐标
5. 如果需要先单独读取正式绑定结构，优先用 `region-bind-contract`
6. 如果最近已经有 Ayes 截图证据，优先直接用 `region-bind-request --plan-file ...` 自动复用最近截图；只有自动补图失败时才手工传 capture_ref
7. 如果有刷新动作，按 `action_intents[]` 确认是否启用、频率是多少、坐标是否已绑定
8. 最后再补 webhook 和其他执行前缺口

## Escalation Back To Workbench

出现以下情况时，明确让用户回到 Ayes Web 工作台：

- 目标没选对
- ROI 需要重新框选
- OCR 对不准区域
- 当前预览图为空或明显不是想监控的画面
- 需要重新配置 webhook、refresh_click 或 triggered 条件
