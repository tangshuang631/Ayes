---
name: ayes-local
description: Use on Windows when the user wants Codex or another local agent to watch a screen, process, window, or ROI over time, ask what happened recently, inspect screenshot evidence, or control an existing Ayes monitoring task through the local Ayes service.
---

# Ayes Local for Windows

Ayes is a local Windows monitoring skill. The installed skill is stateless by default: it must not assume existing tasks, webhooks, screenshots, memory, logs, enabled vision models, or user-specific runtime data.

If the user message contains `Ayes context mode`, treat the next question as an Ayes monitoring question. Prefer the current running task or most recently active task, and use the lightweight query path first.

## Default Decision Tree

1. Ensure the service is available only when needed:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" ensure-service
```

Treat `"$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1"` as the canonical entrypoint. Do not spend time searching `PATH` first.

2. For normal recall questions, use `query` first:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" query --minutes 240 --question "user question"
```

Use this for questions like “最近在干什么”, “刚刚发生了什么”, “刚刚看的内容是什么”, “页面里有什么”, “这个任务现在怎么样”. `query` does routing, memory-index lookup, rerank, and compact output.

3. If the user asks for more detail, add compact memory only:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" memory-items --limit 5
```

4. If the user asks for visual evidence or a screenshot, use screenshot:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" screenshot
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" screenshot --fresh --task-id <task_id>
```

5. If the user asks about notifications, use alerts first:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" alerts --minutes 15 --limit 20
```

6. If the user explicitly asks for logs or debugging, then use logs:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" logs --minutes 15
```

Normal recall must not default to logs, raw JSONL, OCR blocks, bbox, evidence refs, full screenshot lists, or full config snapshots.

## Task Control

Common commands:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" status
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" tasks
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" switch-task --task-id <task_id>
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" start
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" stop
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" control status
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" control pause-all
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" control resume-all
```

If the user asks to create a task from natural language:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" plan-spec --prompt "..." --target-type process --process-name chrome.exe
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" confirm-plan --plan-file C:\Temp\task.plan.json
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" start
```

Read returned `questions[]`, `setup_guidance[]`, `region_intents[]`, and `action_intents[]`. Do not invent missing webhook, ROI, or vision configuration.

## Windows Tray

Start the tray controller when the user wants desktop controls:

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1"
```

The tray can start/continue/pause monitoring, open task data, open settings, configure sampling, configure screenshot hotkey, and configure the `Ayes context mode` question hotkey.

## Progressive Disclosure

Read extra references only when required:

- `references/windows.md`: Windows install, tray, dependencies, limitations.
- `references/commands.md`: full command surface, ROI, storage, sampling, memory, alerts, vision.
- `references/privacy.md`: local data behavior.
- `references/troubleshooting.md`: service and capture failures.

## Response Pattern

Answer with task/target, time range, compact evidence summary, conclusion, and evidence gaps. Keep answers compact. Do not expose internal OCR blocks, bbox, raw event JSON, or logs unless the user explicitly asks.
