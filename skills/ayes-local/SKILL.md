---
name: ayes-local
description: Use when the user wants Codex to watch a local screen, process, or ROI over time, ask what happened in the last few minutes, inspect screenshot evidence, or control an existing Ayes monitoring task through the local Ayes service.
---

# Ayes Local

## When to Use

Use this skill when the request is about:

- 最近几分钟某个受监控进程发生了什么
- 当前有没有弹窗、报错、价格变化、状态变化
- 读取最近截图证据和相关事件
- 开始、停止、确认当前监控任务状态
- 基于已有监控任务继续追问

不要在以下情况直接硬调 Ayes：

- 用户还没有选好目标或 ROI
- 本地 Ayes 服务还没启动
- 用户需要先人工确认预览图是不是正确目标

这些情况应先引导用户打开 Ayes Web 工作台处理配置与核验。

## Default Workflow

1. 先读 `references/installation.md`，确认本机已安装 `ayes-local` 和 `ayes-agent-local` 包装脚本。
2. 先用 `ayes-agent-local ensure-service` 或 `ayes-agent-local status` 确认本地服务可达。
2. 如果用户是在追问最近情况：
   - 先读 `ayes-agent-local screenshot`
   - 再读 `ayes-agent-local recent`
   - 如果问题和提醒有关，补读 `ayes-agent-local alerts`
   - 必要时补 `ayes-agent-local memory-items` 和 `ayes-agent-local logs`
   - 最后用 `ayes-agent-local ask --question "..."` 组织回答
3. 如果用户要求开始或恢复监控：
   - 如果用户给的是自然语言任务，先用 `ayes-agent-local plan-spec ...`
   - 优先读取返回的 `questions[]`
   - 按顺序逐条补问，不要跳过 required 问题
   - 读取 `region_intents[]`，用来确认“价格区/库存区/报错区”等区域用途
   - 如果出现 `region_binding` 问题，优先去拿外部选择器或截图标注器返回的 `region_bindings[]`
   - 读取 `action_intents[]`，用来确认是否启用 refresh_click 以及还缺什么
   - 再读取 `missing_fields / ambiguities / confirmation_summary`
   - 让用户确认或补齐缺失项后，再用 `ayes-agent-local confirm-plan ...`
   - 如果已经有明确结构化 spec，也可以继续用 `ayes-agent-local load-spec ...`
   - 再用 `ayes-agent-local start`
4. 如果用户要求停止持续监控：
   - 用 `ayes-agent-local stop`

更完整的安装、命令和排障细节，按需继续读取：

- `references/installation.md`
- `references/commands.md`
- `references/troubleshooting.md`

## Tooling

优先使用本地工具：

```bash
ayes-agent-local ensure-service
ayes-agent-local contracts
ayes-agent-local status
ayes-agent-local plan-spec --task-id task_web --prompt "帮我监控 Safari 里的商品价格低于 299 时提醒我" --target-type process --process-name Safari
ayes-agent-local confirm-plan --plan-file /tmp/task_web.plan.json --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
ayes-agent-local recent --task-id task_web --minutes 5 --limit 20
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local screenshot --task-id task_web
ayes-agent-local ask --task-id task_web --minutes 5 --question "最近几分钟发生了什么"
ayes-agent-local memory-items --task-id task_web --minutes 5 --limit 20
ayes-agent-local logs --task-id task_web --minutes 15
ayes-agent-local run-once
ayes-agent-local start
ayes-agent-local stop
```

如果没有安装 `ayes-agent-local`，可暂时回退到仓库内命令：

```bash
PYTHONPATH=src python3 -m ayes.cli.agent_tool status
```

若连本地命令也不可用，再回退到等价的本地 HTTP API：

- `/api/agent/contracts`
- `/api/watch/status`
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

- 最近告警审计结果
- 近期日志
- 相关截图与时间范围

不要把 Ayes 当成无边界视觉理解系统。它当前的核心仍是：

- OCR 主链路
- 时序事件
- 短期 / 长期记忆
- 按需视觉增强
- 对话式任务草案与配置确认流

补问时的顺序要求：

1. 先问目标是否正确
2. 再问是否监控整个目标还是重点区域
3. 如果是多区域，按 `region_intents[]` 逐条确认区域名称和用途
4. 如果出现 `region_binding` 问题，去拿 `region_bindings[]`，不要让用户口头报像素坐标
5. 如果有刷新动作，按 `action_intents[]` 确认是否启用、频率是多少、坐标是否已绑定
6. 最后再补 webhook 和其他执行前缺口

## Escalation Back To Workbench

出现以下情况时，明确让用户回到 Ayes Web 工作台：

- 目标没选对
- ROI 需要重新框选
- OCR 对不准区域
- 当前预览图为空或明显不是想监控的画面
- 需要重新配置 webhook、refresh_click 或 triggered 条件
