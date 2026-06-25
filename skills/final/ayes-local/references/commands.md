# Ayes Local 命令清单

以下命令默认使用安装后的本地包装：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local
```

为简洁，下文用 `ayes-agent-local` 代指该脚本。

注意：

- 这是最终无状态 skill 产物对应的命令面
- 刚安装完成时，通常还没有任何任务、webhook 或已启用视觉增强
- 正常首轮流程应是 `ensure-service -> plan-spec -> questions/setup_guidance -> confirm-plan -> start`
- 发布给用户的正式 skill 不应预置任何真实 webhook；只有用户明确授权后，agent 才应在当前任务里写入 webhook

## 1. 服务与契约

```bash
ayes-agent-local ensure-service
ayes-agent-local contracts
ayes-agent-local region-bind-contract
ayes-agent-local status
ayes-agent-local observe-live --minutes 5 --limit 20
~/.codex/skills/ayes-local/scripts/ayes-menubar-local
ayes-menubar
```

用途：

- `ensure-service`：确保本地服务可达，默认地址为 `http://127.0.0.1:8770`
- `contracts`：查看当前 HTTP 接口契约
- `region-bind-contract`：单独读取正式 `region-bind` 输入输出合同，适合外部选择器、截图标注器或 agent 做结构对齐
- `status`：查看当前任务、运行状态、最近健康摘要
- `observe-live`：读取面向 agent 的实时观察上下文，是追问屏幕现状时的优先入口
- `~/.codex/skills/ayes-local/scripts/ayes-menubar-local`：启动 skill 自带的菜单栏控制面，供用户查看当前任务/目标/ROI/最近命中，手动暂停、恢复、切换任务、进入 ROI 管理、进入设置和打开数据目录
- `ayes-menubar`：若系统已安装全局命令，也可作为等价入口

## 2. 目标与任务

```bash
ayes-agent-local targets
ayes-agent-local tasks
ayes-agent-local memory-policy --task-id 2026-06-25__price_watch
ayes-agent-local memory-policy --task-id 2026-06-25__price_watch --short-term-days 10 --long-term-days 25 --disable-auto-cleanup true
ayes-agent-local memory-cleanup --task-id 2026-06-25__price_watch
ayes-agent-local switch-task --task-id 2026-06-25__price_watch
ayes-agent-local delete-task --task-id 2026-06-25__old_watch
ayes-agent-local control status
ayes-agent-local control pause-all
ayes-agent-local control resume-all
ayes-agent-local control cleanup-reminder-check
ayes-agent-local control cleanup-reminder --next-check-after-days 7
ayes-agent-local plan-spec --task-id task_plan --prompt "帮我监控 Safari 里的商品价格低于 299 时提醒我" --target-type process --process-name Safari
ayes-agent-local confirm-plan --plan-file /tmp/task_plan.json --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
ayes-agent-local task --task-id task_web
```

用途：

- `targets`：读取当前可选屏幕/进程目标摘要
- `tasks`：列出已持久化任务，便于恢复、切换和继续追问
- `memory-policy`：读取或更新单个任务的记忆策略；短期详细记忆默认 7 天、最高 14 天，长期简略记忆默认 14 天、最高 30 天
- `memory-policy --disable-auto-cleanup true`：让该任务永久保留记忆，不再自动清理；传 `false` 可恢复自动清理
- `memory-cleanup`：按当前任务策略立即执行一次过期记忆清理
- `switch-task`：把历史任务恢复为当前任务
- `delete-task`：删除指定任务及其长短期记忆、日志与长期摘要
- `control status/pause-all/resume-all`：给 agent 和菜单栏共享同一套后台暂停/恢复状态入口
- `control cleanup-reminder-check`：执行一次清理提醒到期检查，通常用于排障或人工验证
- `control cleanup-reminder --next-check-after-days`：调整清理提醒间隔；默认 7 天
- `plan-spec`：读取自然语言任务并生成 `watch spec` 草案、缺失项和确认摘要
- `plan-spec`：同时返回 `questions[] / region_intents[] / action_intents[] / setup_guidance[]`，供智能体逐条补问并完成缺失配置
- `confirm-plan`：补齐确认项后正式装载任务
- `task`：读取持久化任务配置快照

如果用户要求自定义企业微信消息标题或正文模板，可在确认阶段补入：

```bash
ayes-agent-local confirm-plan \
  --plan-file /tmp/task_plan.json \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" \
  --alert-message-title "库存提醒" \
  --alert-message-template "任务 {task_id} 命中：{summary}"
```

其中可用模板变量至少包括：

- `{task_id}`
- `{timestamp}`
- `{process_name}`
- `{window_title}`
- `{priority}`
- `{confidence}`
- `{summary}`
- `{event_id}`

如果用户想先验证安装后整条告警链路，而不立刻给真实企业微信发消息，可在本机执行：

```bash
cd /Users/apple/Desktop/2026/Ayes
python3 scripts/smoke_ayes_local_skill.py
```

默认会完成：

- 安装到临时 skill 根目录
- 回收可安全关闭的旧本地服务
- 自启本地 round-trip webhook 接收端
- 验证 `plan-spec -> confirm-plan -> start -> run-once -> alert_sent`

如果用户已经授权并提供真实企业微信 webhook，也可以直接验证真实外发：

```bash
cd /Users/apple/Desktop/2026/Ayes
python3 scripts/smoke_ayes_local_skill.py \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
```

如果还要同时验证自定义消息标题和正文模板，可追加：

```bash
python3 scripts/smoke_ayes_local_skill.py \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" \
  --alert-message-title "库存提醒" \
  --alert-message-template "任务 {task_id} 命中：{summary}"
```

## 3. 近期证据链路

```bash
ayes-agent-local observe-live --task-id task_web --minutes 5 --limit 20
ayes-agent-local screenshot --task-id task_web
ayes-agent-local recent --task-id task_web --minutes 5 --limit 20
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local memory-items --task-id task_web --minutes 5 --limit 20
ayes-agent-local memory-items --task-id task_web --minutes 10080 --limit 50
ayes-agent-local long-term --task-id task_web --hours 336 --limit 50
ayes-agent-local logs --task-id task_web --minutes 15
ayes-agent-local run-once
```

用途：

- `screenshot`：读取最近截图路径与 ROI 覆盖信息
- `recent`：读取最近时间线事件
- `alerts`：读取最近告警审计结果
- `memory-items`：读取短期详细记忆事件明细；默认短期保留 7 天，最高 14 天
- `long-term`：读取长期简略摘要；默认保留 14 天，最高 30 天
- `logs`：读取近期日志
- `run-once`：执行一次即时采样，适合安装后 smoke 或人工核验

`screenshot` 返回的 `path` 应指向最近真实采样帧的唯一文件名；不要假设固定的 `web-last-frame.png` 就是最新图。固定文件仅作为兼容指针存在。

`observe-live` 聚合返回：

- `status`：当前任务、目标、运行状态、健康摘要
- `screenshot`：最近截图、ROI、捕获状态
- `recent_events`：最近时间线事件
- `memory_items`：短期记忆明细
- `alerts`：告警审计事件
- `logs`：近期后台日志
- `evidence_status`：证据是否足够 agent 回答
- `agent_hints`：下一步建议，例如启动监控、执行一次采样或检查 ROI/OCR

其中 `agent_hints.task_context` 会明确告诉智能体：

- 当前正在查看哪个任务
- 当前是否只是回读持久化证据
- 最近有哪些可恢复的历史任务
- 用户说“继续之前那个任务”时是否应先 `tasks` 再 `switch-task`

追问“现在屏幕怎样”“最近发生了什么”“有没有通知出去”时，应先用 `observe-live`，再按问题补细颗粒命令。

如果用户问“昨天某个进程在做什么”“最近几天最低价是什么时候”：

- 优先根据问题跨度设置 `memory-items --minutes`，短期详细记忆可查到任务策略允许的天数
- 如果跨度超出短期详细记忆或需要概览，改用 `long-term --hours` 或 `ask --hours`
- 如果问题超出短期和长期保留策略，应明确说明记忆已超过保留范围
- 记忆文件按任务和日期切割存放在安装目录 `runtime/memory/<task_id>/short/` 与 `runtime/memory/<task_id>/long/`

## 3.1 本地视觉增强准备与启用

只有当用户明确希望开启本地 Ollama 视觉增强时，才执行：

```bash
ayes-agent-local vision prepare --requested-by agent_enable_local_vision
ayes-agent-local vision enable --provider ollama --model qwen2.5vl:7b --auto-use-when-available true
ayes-agent-local vision status
```

说明：

- `vision prepare`：只在显式启用请求下检查 Ollama / 服务 / 默认模型是否就绪
- `vision enable`：写入本地视觉增强配置
- `vision status`：回读当前启用状态
- 默认模型应使用 `qwen2.5vl:7b`

## 4. 提问

最近几分钟问答：

```bash
ayes-agent-local ask --task-id task_web --minutes 5 --question "最近几分钟发生了什么"
```

长期摘要问答：

```bash
ayes-agent-local ask --task-id task_web --hours 24 --question "今天这个进程最低大概是什么时候"
```

说明：

- `minutes` 主要走短期详细链路
- `hours` 主要走长期摘要链路
- 若用户问“最近 xx 小时/昨天/最近几天”，应显式带 `--hours`

如果用户问“刚才有没有真的通知出去”或“为什么没通知”，优先读取：

```bash
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local logs --task-id task_web --minutes 15
```

## 4.1 恢复、切换与删除历史任务

如果用户说“继续之前那个任务”“把昨天那个价格监控重新启用”“切到另一个任务”，标准顺序是：

```bash
ayes-agent-local tasks
ayes-agent-local switch-task --task-id 2026-06-25__price_watch
ayes-agent-local observe-live --task-id 2026-06-25__price_watch --minutes 5 --limit 20
```

说明：

- 长短期记忆、时间线、告警和日志都按 `task_id` 独立存储
- `tasks` 返回的 `memory_policy.memory_dir` 是该任务独立记忆目录
- 切回历史任务后，后续 `ask/recent/memory-items/alerts/logs` 应优先显式带该 `task_id`
- 如果用户要求删除某个旧任务，应先确认具体任务，再执行：

```bash
ayes-agent-local delete-task --task-id 2026-06-25__old_watch
```

## 5. 启停监控

```bash
ayes-agent-local start
ayes-agent-local stop
```

注意：

- `start` 前应已有已装载任务
- 默认本地服务地址下，`start` 会尽力自动拉起 macOS 菜单栏控制入口
- `stop` 会停止当前持续监控

## 5.1 菜单栏 ROI 与设置

macOS 菜单栏图标点击或右键后，用户可进入：

- ROI 管理：基于当前任务目标/最近截图打开工作台标注器，框选多个 ROI、命名、启用/禁用或删除
- 设置：查看任务列表、近期日志、清理提醒间隔、本地视觉增强和熄屏整屏捕获策略

熄屏策略说明：

- 进程/窗口监控优先使用窗口捕获，通常比整屏截图更适合熄屏场景
- 整屏监控的“熄屏虚拟屏幕”设置是尝试策略，不是强保证；若 macOS 不提供可读帧，应提示用户切换到进程或窗口监控

## 6. 装载最小 watch spec

优先推荐的自然语言编排流：

```bash
ayes-agent-local plan-spec \
  --task-id task_price \
  --prompt "帮我监控 Google Chrome 里的商品价格低于 299 时提醒我" \
  --target-type process \
  --process-name "Google Chrome"
```

如果返回提示缺少 webhook，则把输出 JSON 保存为本地文件后确认装载：

```bash
ayes-agent-local confirm-plan \
  --plan-file /tmp/task_price.plan.json \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
```

如果 `plan-spec` 或后续运行态返回 webhook、本地视觉模型或其他依赖未就绪，智能体不应只停在“当前无法继续”这一层，而应：

1. 读取 `setup_guidance[]`
2. 把 `user_steps` 转成当前轮对话中的明确指导
3. 在用户补完配置后继续执行 `confirm-plan`、`vision prepare`、`vision enable` 等后续命令
4. 如果用户仍不会操作，就继续按同一 guidance 反复指导，而不是要求用户自己去翻文档

如果用户已经明确授权真实 webhook，则 agent 的目标不应只是“记录这个 URL”，而应继续把它写入 `confirm-plan`，必要时还要补上：

- `--alert-message-title`
- `--alert-message-template`

这样后台服务才能在长时间持续运行期间，独立按任务配置真实外发企业微信消息。

当用户已知完整结构化配置时，仍可直接使用 `load-spec`，但面向 Codex/OpenClaw 的默认成熟路线应优先走 `plan-spec -> setup_guidance/questions -> confirm-plan`。

如果 `plan-spec` 返回：

- `questions[]`：智能体应先逐条补问
- `region_intents[]`：智能体应向用户确认区域名称、用途，以及是否真的需要这些区域
- `action_intents[]`：智能体应确认是否启用刷新点击、频率多少、是否已有点击点

当 `questions[]` 中出现 `region_binding` 时，标准做法不是让智能体口头问像素坐标，而是：

1. 调外部选择器或截图标注器
2. 获取 `region_bindings[]`
3. 再把这些绑定结果传给 `confirm-plan`

如果使用本地命令行确认，可把绑定结果转成多次 `--region-binding`：

```bash
ayes-agent-local confirm-plan \
  --plan-file /tmp/task_price.plan.json \
  --region-binding "ri_price|roi_price|价格区|120|240|360|160|target|screenshot_annotation" \
  --region-binding "ri_stock|roi_stock|库存区|120|420|360|120|target|external_selector" \
  --refresh-click-enabled \
  --refresh-click-point "100,120" \
  --refresh-click-coordinate-space screen
```

如果当前任务已经生成过最近截图，也可以直接先生成正式绑定请求，让工具自动补齐最近截图路径和尺寸：

```bash
ayes-agent-local region-bind-request --plan-file /tmp/task_price.plan.json
```

只有在自动补图失败或需要强制指定其他截图时，才手工追加：

```bash
ayes-agent-local region-bind-request \
  --plan-file /tmp/task_price.plan.json \
  --capture-id cap_demo_2 \
  --image-path /tmp/cap.png \
  --image-width 1440 \
  --image-height 900
```

推荐补问顺序：

1. 先处理 `target_missing`
2. 再处理 `region_scope / region_definition`
3. 再处理 `refresh_click_enable / refresh_click_interval / refresh_click_point`
4. 最后处理 `webhook_missing` 等执行前缺口

推荐的 `region_bindings[]` 结构：

```json
[
  {
    "region_intent_id": "ri_price",
    "region_id": "roi_price",
    "name": "价格区",
    "x": 120,
    "y": 240,
    "w": 360,
    "h": 160,
    "coordinate_space": "target",
    "source": "screenshot_annotation"
  }
]
```

屏幕观察任务：

```bash
ayes-agent-local load-spec \
  --task-id task_web \
  --mode observe \
  --target-type screen \
  --screen-id 1
```

按进程装载 triggered 任务：

```bash
ayes-agent-local load-spec \
  --task-id task_price \
  --mode triggered \
  --target-type process \
  --process-name "Google Chrome" \
  --query "价格低于 299" \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" \
  --screenshot-interval-ms 500 \
  --ocr-interval-ms 500 \
  --change-detection-interval-ms 500
```

启用本地视觉辅助：

```bash
ayes-agent-local load-spec \
  --task-id task_chart \
  --mode observe \
  --target-type process \
  --process-name "Google Chrome" \
  --enable-vision \
  --vision-provider ollama \
  --vision-model qwen2.5vl:7b
```
