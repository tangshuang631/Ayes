# 14 企业微信 Webhook 告警策略

## 1. 文档目标

本文件定义 Ayes 第一阶段的企业微信 webhook 告警策略。

它覆盖：

- 告警启用条件
- 触发条件
- 去重策略
- 冷却策略
- 消息模板
- 失败处理
- 告警审计事件
- 与 skill / agent 的职责边界

## 2. 适用模式

企业微信 webhook 默认只服务于 `triggered` 模式。

`observe` 模式默认不主动发送 webhook。

如果用户在观察型监控运行期间追加触发目标和告警配置，则任务可以从纯观察型行为扩展为带告警行为，但必须更新对应 `watch spec`。

## 3. 告警启用条件

发送 webhook 前必须同时满足：

- `watch spec.mode = triggered`
- `alert.enabled = true`
- `alert.channel = wecom_webhook`
- webhook 地址可解析
- 事件命中 `watch_intent`
- 事件优先级达到 `priority_threshold`
- 未命中去重窗口
- 未命中冷却窗口

## 4. 触发条件

告警触发来源包括：

- 规则命中
- 关键词命中
- 向量语义命中
- 轻量视觉标签命中
- 高优先级事件命中

典型场景：

- 目标状态满足条件
- 数值低于或高于阈值
- 验证码出现
- 登录失效
- 断连
- 错误提示
- 超时

## 5. 去重策略

去重用于避免同一事件反复通知。

建议去重键：

```text
task_id + target_id + matched_query_or_rule + normalized_summary
```

第一阶段默认：

- `dedupe_window_sec = 300`

在去重窗口内，如果新事件与旧事件去重键一致，则不发送 webhook，而是记录 `alert_suppressed` 事件。

## 6. 冷却策略

冷却用于限制同一任务的告警频率。

第一阶段默认：

- `cooldown_sec = 120`

冷却规则：

- 同一 `task_id` 在冷却时间内最多发送一次告警
- 高优先级事件可以保留后续升级空间，但第一阶段不绕过冷却
- 被冷却抑制的告警必须记录 `alert_suppressed` 事件

## 7. 消息模板

第一阶段建议使用文本消息。

模板：

```text
[Ayes] 命中监控目标

目标：{watch_intent_summary}
时间：{timestamp}
任务：{task_id}
进程：{process_name}
窗口：{window_title}
优先级：{priority}
置信度：{confidence}

摘要：{event_summary}
证据：{evidence_summary}
事件：{event_id}
```

对于由刷新点击后触发的变化，追加：

```text
触发来源：刷新点击后检测到变化
```

## 8. Webhook 地址管理

webhook 地址不允许硬编码进代码或文档示例。

第一阶段推荐：

- 通过环境变量读取
- 默认变量名：`AYES_WECOM_WEBHOOK_URL`

为了支持本地安装后 smoke 和单任务自测，当前阶段允许在受控本地场景下通过 `watch spec.alert.webhook_url` 直接传入 webhook 地址。

但约束是：

- 仅用于本地开发、临时 smoke 或单机验证
- 正式长期使用仍优先环境变量
- 文档默认安装流仍以环境变量为主

如果后续支持多任务多 webhook，可扩展为安全本地配置，但仍不应写死在 `watch spec` 明文样例中。

为了在不依赖外部企业微信网络的情况下验证告警发送链路，允许在用户本机执行本地 round-trip smoke：

```bash
python3 scripts/smoke_webhook_flow.py
```

该脚本的目标是证明：

- 后台告警消息格式符合当前文本模板
- 本地 webhook 接收端可以真实收到 POST
- 后续可把同一 webhook URL 用于本机临时自测

如果当前执行环境不允许监听本地端口，应把这一步保留为“用户本机实测项”，而不是错误地宣称已完成真实 round-trip 验证。

## 9. 失败处理

发送失败必须记录。

失败类型包括：

- webhook 未配置
- HTTP 请求失败
- 企业微信返回非成功状态
- 超时
- 频率限制

第一阶段策略：

- 失败不阻塞监控任务继续运行
- 写入 `alert_suppressed` 或 `alert_failed` 审计事件
- 保留失败原因
- 后续可以由用户查询“为什么没有通知我”

## 10. 告警事件

告警相关事件必须进入事件流。

事件类型：

- `alert_sent`
- `alert_suppressed`
- `alert_failed`

要求：

- `alert_sent` 记录实际发送成功
- `alert_suppressed` 记录去重或冷却导致的抑制
- `alert_failed` 记录发送失败

## 11. 与长期记忆的关系

长期轻量记忆必须保留：

- `alert_sent`
- `alert_failed`
- 高优先级 `alert_suppressed`

原因：

- 用户可能在几小时后追问是否通知过
- 告警轨迹是长期监控的重要摘要

## 12. 与 skill / agent 的职责边界

企业微信 webhook 的即时通知责任必须由 Ayes 后台服务承担。

明确规则：

- 监控命中后，后台服务直接发 webhook
- 不依赖 Codex / OpenClaw / 其他 agent 此刻是否在线
- 不依赖已安装 skill 的智能体是否能立即回复

`ayes-local` 和其他 agent 入口的职责是：

- 启动或恢复本地服务
- 装载任务
- 查询最近告警
- 查询最近截图、事件、记忆、日志
- 在用户追问时解释“刚才发生了什么”

因此：

- 告警通知渠道是工具底座能力
- 智能体回复渠道是交互层能力
- 两者必须解耦，不能把“有没有提醒到用户”建立在智能体实时回复之上

## 13. 与 Watch Spec 的关系

告警策略由 `watch spec.alert` 控制。

关键字段：

- `enabled`
- `channel`
- `webhook_url_env`
- `webhook_url`
- `message_title`
- `message_template`
- `priority_threshold`
- `cooldown_sec`
- `dedupe_window_sec`

## 14. 第一阶段结论

企业微信 webhook 是第一阶段唯一标准告警出口。

告警必须建立在事件模型之上。

发送、抑制和失败都必须进入事件流，保证后续问答可以解释“是否通知过”和“为什么没通知”。
