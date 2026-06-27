---
name: ayes-local
description: Use when the user wants Codex to watch a local screen, process, or ROI over time, ask what happened recently, inspect screenshot evidence, or control an existing Ayes monitoring task through the local Ayes service.
---

# Ayes Local

Ayes is a local macOS monitoring skill. The installed skill is stateless by default: it must not assume existing tasks, webhooks, screenshots, memory, logs, enabled vision models, or user-specific runtime data.

If the user message contains the short prompt `Ayes context mode`, treat the next question as an Ayes monitoring question. Prefer the current running task or most recently active task, and use the lightweight query path first.

## Default Decision Tree

1. In a fresh window, start with the canonical wrapper plus `query`, not with `status`, `ensure-service`, and PATH hunting:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local query --minutes 240 --question "用户的问题"
```

Treat `$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local` as the canonical entrypoint. Do not spend time searching `PATH` first. Do not start with `status`, `ensure-service`, and PATH hunting unless the query or task-control path actually needs it.

2. Ensure the service is available only when needed:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local ensure-service
```

3. For normal recall questions, use `query` first:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local query --minutes 240 --question "用户的问题"
```

Use this for questions like “最近在干什么”, “刚刚发生了什么”, “刚刚看的内容是什么”, “页面里有什么”, “这个任务现在怎么样”. `query` does routing, memory-index lookup, rerank, and compact output. Answer from its `answer/items/retrieval/needs_detail` fields when sufficient.

4. If the user asks for more detail, add compact memory only:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local memory-items --limit 5
```

Do not request raw memory unless the user explicitly asks for raw evidence or debugging.

5. If the user asks for visual evidence or a screenshot, use screenshot:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local screenshot
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local screenshot --fresh --task-id <task_id>
```

6. If the user asks about notifications, use alerts first:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local alerts --minutes 15 --limit 20
```

7. If the user explicitly asks for logs or debugging, then use logs:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local logs --minutes 15
```

Normal recall must not default to logs, raw JSONL, OCR blocks, bbox, evidence refs, full screenshot lists, or full config snapshots.

## Task Control

Common task commands:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local status
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local tasks
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local switch-task --task-id <task_id>
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local start
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local stop
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local control status
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local control pause-all
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local control resume-all
```

If the user asks to create a task from natural language, use the planning flow:

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local plan-spec --prompt "..." --target-type process --process-name Safari
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local confirm-plan --plan-file /tmp/task.plan.json
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local start
```

Read and follow returned `questions[]`, `setup_guidance[]`, `region_intents[]`, and `action_intents[]`. Do not invent missing webhook, ROI, or vision configuration.

## Menu Bar

On macOS, start the local menu bar controller when the user wants desktop controls:

```bash
~/.codex/skills/ayes-local/scripts/ayes-menubar-local
```

The menu bar can pause/resume monitoring, open task directories, configure sampling, configure screenshot hotkey, configure the Ayes context hotkey, and manage ROI/task settings.

The context hotkey pastes `Ayes context mode`; this is intentionally short so the user can put focus in a chat box, press one shortcut, and ask the next question against Ayes context.

## Progressive Disclosure

Read extra references only when the current task requires them:

- `references/installation.md`: install, wrappers, service startup.
- `references/commands.md`: full command surface, ROI, storage, sampling, memory, alerts, vision, menu bar settings.
- `references/privacy.md`: privacy and local data behavior.
- `references/troubleshooting.md`: service, menu bar, permission, hotkey, and capture failures.
- `references/menubar-manual-test.md`: menu bar manual verification.
- `references/stress-test.md`: long-running validation.
- `references/release-checklist.md`: release hardening.

## Response Pattern

Answer with:

1. Which Ayes task or target was used.
2. Time range.
3. Compact evidence summary.
4. Conclusion.
5. If evidence is weak, say what is missing and what command would verify it.

Keep answers compact. Do not expose internal OCR blocks, bbox, raw event JSON, or logs unless the user explicitly asks.
