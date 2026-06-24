---
name: ayes-local
description: Use when the user wants Codex to watch a local screen, process, or ROI over time, ask what happened in the last few minutes, inspect screenshot evidence, or control an existing Ayes monitoring task through the local Ayes service.
---

# Ayes Local

## Overview

Ayes gives Codex a local visual timeline over the user's chosen screen or process.

Use it to read current monitoring state, recent screen changes, screenshot evidence, short-term memory, and recent Q&A results from the local Ayes service.

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

1. 先用 `ayes-agent status` 或 `ayes-agent contracts` 确认本地服务和接口状态。
2. 如果用户是在追问最近情况：
   - 先读 `ayes-agent screenshot`
   - 再读 `ayes-agent recent`
   - 最后用 `ayes-agent ask --question "..."` 组织回答
3. 如果用户要求开始或恢复监控：
   - 必要时用 `ayes-agent load-spec ...`
   - 再用 `ayes-agent start`
4. 如果用户要求停止持续监控：
   - 用 `ayes-agent stop`

## Tooling

优先使用本地工具：

```bash
ayes-agent contracts
ayes-agent status
ayes-agent recent --task-id task_web --minutes 5 --limit 20
ayes-agent screenshot --task-id task_web
ayes-agent ask --task-id task_web --minutes 5 --question "最近几分钟发生了什么"
ayes-agent start
ayes-agent stop
```

如果没有安装 `ayes-agent`，可以回退到等价的本地 HTTP API：

- `/api/agent/contracts`
- `/api/watch/status`
- `/api/timeline/recent`
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

不要把 Ayes 当成无边界视觉理解系统。它当前的核心仍是：

- OCR 主链路
- 时序事件
- 短期 / 长期记忆
- 按需视觉增强

## Escalation Back To Workbench

出现以下情况时，明确让用户回到 Ayes Web 工作台：

- 目标没选对
- ROI 需要重新框选
- OCR 对不准区域
- 当前预览图为空或明显不是想监控的画面
- 需要重新配置 webhook、refresh_click 或 triggered 条件
