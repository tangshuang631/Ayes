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
- 查询昨天、最近几天或更久之前的任务记忆
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
   - 先读 `ayes-agent-local activity --minutes 5`
   - 普通“最近在干什么/刚刚发生了什么”只使用 `activity` 返回的 `primary_summary / timeline / keywords / confidence / has_screenshot_evidence`
   - 如果需要更细事件，再补 `ayes-agent-local memory-items --limit 5`
   - 如果用户明确要截图证据，再补 `ayes-agent-local screenshot`；只有需要完整实时上下文时才用 `observe-live`
   - 如果用户明确要求排障、日志或“为什么没通知”，才补 `ayes-agent-local logs`；正常回忆问题不要默认查日志
   - `status` 只能作为运行状态和日志计数摘要来源；不要把它当成近期活动明细来源
   - 如果问题和提醒有关，先读 `ayes-agent-local alerts`，排障时再读日志
   - 如需组织跨时间回答，再用 `ayes-agent-local ask --question "..."`
   - 如果用户问“昨天”“最近几天”或超出短期紧凑明细窗口的问题，显式用 `ayes-agent-local ask --hours ...` 或 `ayes-agent-local long-term --hours ...`
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
7. 如果用户要求调整记忆保存时间：
   - 先用 `ayes-agent-local memory-policy --task-id ...` 查看当前策略
   - 短期紧凑明细默认 7 天、最高 14 天；长期简略记忆默认 14 天、最高 30 天
   - 若用户说“不自动清理/永久保留”，用 `--disable-auto-cleanup true`
   - 若用户说“恢复自动清理”，用 `--disable-auto-cleanup false`
7. 如果用户希望通过小图标手动暂停、恢复或打开数据目录：
   - 在 macOS 上运行 `~/.codex/skills/ayes-local/scripts/ayes-menubar-local`，该入口必须启动原生 `Ayes 菜单栏.app`
   - 若已安装全局入口，也可直接运行 `ayes-menubar`
   - 菜单栏可查看最近任务，进入 ROI 管理、原生桌面设置弹窗、暂停/恢复、任务切换和数据目录
   - 菜单顶部 `Ayes 监控中` 下方应列出当前正在运行的任务；这些任务入口与最近任务一致，可打开任务目录或进入专属设置
   - 暂停后菜单顶部必须显示 `Ayes 已暂停`，主动作必须从 `暂停监控` 变成 `继续上次的监控`，并继续保留当前任务入口
   - “打开当前任务目录”必须进入 `runtime/tasks/<date>/<task_id>/`，最近任务子菜单里的“打开任务目录”也必须进入该任务专属目录
   - 设置弹窗不跳转 Web；采样间隔可直接在桌面弹窗调整，范围 0.5 秒到 1 小时
   - 从某个任务右键进入“专属设置”时，设置页样式与普通设置一致，但采样和记忆配置优先写入该任务；保存失败必须明确提示，不能静默回退到全局/默认值
   - 设置弹窗里的本地大模型增强模型必须来自 `/api/vision/models` 的 Ollama 模型下拉列表，不允许自由输入
   - 如果用户选择非视觉模型，菜单栏和服务端都必须自动关闭本地大模型增强，并提示“当前选择增强模型为非视觉模型，已关闭本地模型增强。”
   - 设置弹窗可配置“截图快捷键”，例如 `cmd+shift+9`；只在 Ayes 菜单栏进程运行且当前任务正在监控时生效
   - 快捷键触发后会把最新真实采样图写入系统剪贴板，并模拟粘贴到当前焦点输入框
   - 但任务编排、证据回读和大部分交互仍应优先通过 agent 完成
8. 如果用户要求调整采样策略：
   - 默认采样间隔是 6 秒；截图、OCR、变化检测默认保持一致
   - 默认采样质量是 `standard`，会把最长边限制到 1920；可选 `original / standard / space_saver / ultra_saver`
   - 默认不保存事件证据截图；`save_ocr_screenshots=true` 只在用户明确需要逐事件原图证据时开启
   - `screenshots/latest/` 是短期最新帧缓存，供 `screenshot` 和截图快捷键使用，即使关闭事件证据截图也会保留少量最新帧
   - `screenshots/evidence/` 是逐事件证据图目录，长期高频开启会快速占用磁盘
   - 用 `ayes-agent-local sampling` 查看当前任务采样策略
   - 用 `ayes-agent-local sampling --interval-sec 6` 或 `--interval-ms 6000` 更新当前任务
   - 用 `ayes-agent-local sampling --quality space_saver --save-ocr-screenshots false` 降低落盘压力
   - 允许范围是 0.5 秒到 1 小时；更新会作用于当前任务的截图、OCR 和变化检测间隔

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
ayes-agent-local activity --task-id task_web --minutes 5
ayes-agent-local memory-items --task-id task_web --minutes 5 --limit 5
ayes-agent-local observe-live --task-id task_web --minutes 5 --limit 20
ayes-agent-local recent --task-id task_web --minutes 5 --limit 20
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local screenshot --task-id task_web
ayes-agent-local ask --task-id task_web --minutes 5 --question "最近几分钟发生了什么"
ayes-agent-local memory-items --task-id task_web --minutes 5 --limit 20
ayes-agent-local memory-policy --task-id task_web
ayes-agent-local memory-policy --task-id task_web --short-term-days 10 --long-term-days 25 --disable-auto-cleanup true
ayes-agent-local memory-cleanup --task-id task_web
ayes-agent-local sampling
ayes-agent-local sampling --interval-sec 3
ayes-agent-local sampling --task-id task_web --interval-sec 6
ayes-agent-local roi list --task-id task_web
ayes-agent-local roi create --task-id task_web --roi-name 价格监控 --region "roi_price|价格监控|120|240|360|160|target"
ayes-agent-local roi update --task-id task_web --roi-task-id task_web__roi_price --enabled false
ayes-agent-local roi delete --task-id task_web --roi-task-id task_web__roi_price
ayes-agent-local task-alert --task-id task_web__roi_price --enabled true --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" --message-title "价格提醒"
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
ayes-agent-local vision models
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
- `/api/activity`
- `/api/watch/status`
- `/api/agent/observe-live`
- `/api/watch/task/{task_id}`
- `/api/timeline/recent`
- `/api/alerts/recent`
- `/api/timeline/long-term`
- `/api/memory/items`
- `/api/tasks/{task_id}/memory-policy`
- `/api/tasks/{task_id}/memory-cleanup`
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

- `alerts` 中的最近告警审计结果
- 最近告警审计结果
- 近期日志，仅在排障时读取
- 相关截图与时间范围

不要把 Ayes 当成无边界视觉理解系统。它当前的核心仍是：

- OCR 主链路
- 时序事件
- 短期 / 长期记忆
- 按需视觉增强
- 对话式任务草案与配置确认流

无 ROI 任务的默认观察策略：

- 没有配置 ROI 时，Ayes 会继续监控整个屏幕、窗口或进程目标
- 系统会自动生成主内容区、全目标、顶部栏、左右侧栏和底部栏等注意力区域
- 主内容区权重最高，优先用于“当前主要内容”和本地视觉增强触发
- 顶部、侧栏、底部和全目标不是被忽略；它们仍会进入 OCR 事件和记忆，只是权重较低，避免边角小字抢占主摘要
- 回答“最近主要在做什么”时优先看 `structured_observation.attention.primary=true` 或长期摘要里的 `main_content_snapshot`
- 回答“旁边/顶部/底部有没有什么信息”时也要检索低权重区域事件，不能只看主内容区

记忆策略：

- 每个任务都有独立记忆策略和目录，默认在 `$HOME/.codex/skills/ayes-local/runtime/tasks/<date>/<task_id>/`
- 任务目录下按类型分为 `screenshots/`、`memory/`、`config/`、`logs/`；截图继续细分 `screenshots/latest/` 和 `screenshots/evidence/`
- `screenshots/latest/` 只保留少量最新真实采样帧和 `web-last-frame.png` 兼容指针，用于截图接口、ROI 标注、快捷键复制粘贴
- `screenshots/evidence/` 只在 `save_ocr_screenshots=true` 时写入逐事件证据图；默认关闭以避免长时间监控产生海量图片
- 短期紧凑明细默认保留 7 天，最高 14 天，适合回答最近几分钟、昨天、最近几天的细节问题
- 长期简略记忆默认保留 14 天，最高 30 天，适合短期紧凑明细之外的问题
- `disable_auto_cleanup=true` 表示永久保留该任务记忆，不再自动清理
- 如果用户询问超出短期和长期保留范围的内容，应明确说明记忆已超出保留范围，而不是编造

并且这条 skill 的目标不是“告诉用户去哪里自己配置”，而是：

- 优先通过 `questions[]`、`setup_guidance[]` 和正式命令面把配置一步步补齐
- 当用户第一次没配好时继续指导
- 配置一旦满足就继续推进任务，而不是让流程中断

近期回忆时的优先证据顺序：

1. `activity` 读取轻量近期活动摘要，回答普通“最近在做什么”
2. `memory-items --limit 5` 默认读取紧凑短期明细，过滤 OCR blocks、bbox、evidence_refs 等重字段
3. `screenshot` 只在用户要求截图证据时读取
4. `observe-live` 只在需要完整实时上下文、证据状态或 ROI/截图综合信息时读取
5. `alerts` 用于通知相关问题
6. `logs` 只在用户明确要求日志或排障时读取

Token 节省规则：

- 普通回忆问题不得默认读取 `/api/logs` 或 `ayes-agent-local logs`
- 不得把原始 JSONL、完整 OCR blocks、bbox、evidence_refs 或完整配置快照带入回答上下文
- `status.health_summary.recent_logs` 只代表聚合计数，不包含原始日志内容；不能用它回答“最近在做什么”
- 需要细节时优先使用 `memory-items --limit 5`，仍不够且用户明确要原始证据/排障时再用 `memory-items --raw`

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
