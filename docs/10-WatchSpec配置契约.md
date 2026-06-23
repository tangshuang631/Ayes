# 10 Watch Spec 配置契约

## 1. 文档目标

`watch spec` 是 Ayes 第一阶段最核心的任务配置契约。

它负责描述：

- 监控目标
- 任务模式
- 截图与 OCR 频率
- 短期详细记忆策略
- 长期轻量记忆策略
- 触发条件
- 企业微信 webhook 策略
- 受控刷新点击策略

后续代码实现、CLI、HTTP API、skill / tool 接入都必须围绕本契约展开。

## 2. 任务模式

`mode` 必须支持两种值：

- `triggered`
- `observe`

### 2.1 triggered

`triggered` 表示目标触发监控。

适用场景：

- 某个目标状态出现时通知我
- 某个数值低于或高于阈值时通知我
- 页面出现验证码时通知我
- 控制台出现报错时通知我
- 登录失效、断连、超时时通知我

行为要求：

- 必须配置 `watch_intent.enabled = true`
- 可以配置 `alert.enabled = true`
- 可以配置 `actions.refresh_click.enabled = true`
- 命中触发条件后写入事件时间线
- 命中触发条件后按配置发送 webhook

### 2.2 observe

`observe` 表示观察型监控。

适用场景：

- 帮我开始持续监控这个屏幕
- 帮我观察这个进程
- 先盯着这个窗口，后面我随时问你

行为要求：

- 可以不配置触发条件
- 默认不主动发送 webhook
- 持续维护短期详细记忆
- 持续维护长期轻量记忆
- 用户提问时进入时间线检索链路

## 3. 完整结构

第一阶段建议结构如下：

```json
{
  "spec_version": "1.0",
  "mode": "triggered",
  "target": {
    "type": "process|window|screen",
    "process_name": "TargetApp",
    "process_id": null,
    "window_id": null,
    "screen_id": null,
    "include_all_windows": true,
    "only_observable_windows": true
  },
  "sampling": {
    "screenshot_interval_ms": 1000,
    "ocr_interval_ms": 1000,
    "change_detection_interval_ms": 1000,
    "max_fps": 2,
    "skip_ocr_when_no_change": true
  },
  "memory": {
    "short_term": {
      "enabled": true,
      "retain_minutes": 15,
      "detail_level": "high"
    },
    "long_term": {
      "enabled": true,
      "retain_hours": 24,
      "max_retain_hours": 72,
      "summary_interval_minutes": 5,
      "detail_level": "summary"
    }
  },
  "watch_intent": {
    "enabled": true,
    "summary": "当目标状态满足条件时通知我",
    "queries": ["目标出现", "状态变化", "字段满足条件"],
    "rules": [
      {
        "type": "text_contains",
        "any": ["状态可用", "目标出现", "满足条件"]
      },
      {
        "type": "numeric_threshold",
        "field": "numeric_field",
        "operator": "lt",
        "value": 299.0,
        "unit": "custom"
      }
    ],
    "semantic_match": {
      "enabled": true,
      "threshold": 0.78
    }
  },
  "alert": {
    "enabled": true,
    "channel": "wecom_webhook",
    "webhook_url_env": "AYES_WECOM_WEBHOOK_URL",
    "priority_threshold": "medium",
    "cooldown_sec": 120,
    "dedupe_window_sec": 300
  },
  "actions": {
    "refresh_click": {
      "enabled": false,
      "point": {"x": 0, "y": 0},
      "coordinate_space": "window|screen",
      "interval_sec": 30,
      "cooldown_sec": 30,
      "max_clicks_per_hour": 120,
      "pause_when_target_matched": true
    }
  }
}
```

## 4. 监控目标

`target.type` 支持：

- `process`
- `window`
- `screen`

### 4.1 process

监控指定进程下的窗口。

要求：

- 可以通过 `process_name` 或 `process_id` 绑定
- 默认 `include_all_windows = true`
- 默认 `only_observable_windows = true`
- 无画面或无业务价值窗口不进入主监控链路

### 4.2 window

监控用户明确选择的单个窗口。

要求：

- 必须提供 `window_id`
- 适合用户从预览列表点击绑定

### 4.3 screen

监控整个屏幕。

要求：

- 必须提供 `screen_id`
- 适合用户要求“持续监控屏幕”的场景

## 5. 采样与 OCR 频率

采样和 OCR 频率必须允许用户调整。

第一阶段至少支持以下常见配置：

- 一秒两张：`screenshot_interval_ms = 500`
- 一秒五张：`screenshot_interval_ms = 200`
- 三秒一张：`screenshot_interval_ms = 3000`

OCR 频率由 `ocr_interval_ms` 控制。

原则：

- 截图频率和 OCR 频率必须分开配置
- OCR 默认只在变化检测命中后运行
- 高频截图不等于高频 OCR
- `max_fps` 用于保护资源占用

推荐默认值：

- `screenshot_interval_ms = 1000`
- `change_detection_interval_ms = 1000`
- `ocr_interval_ms = 1000`
- `max_fps = 2`
- `skip_ocr_when_no_change = true`

## 6. 短期详细记忆

短期详细记忆用于最近几分钟的细粒度问答。

第一阶段要求：

- 默认开启
- 默认保留 15 分钟
- 上限为 15 分钟
- 保存高密度事件
- 保存必要截图切片或证据引用
- 支持“刚才几分钟内发生了什么”类问题

## 7. 长期轻量记忆

长期轻量记忆用于长期监控。

第一阶段建议：

- 默认开启
- 默认保留 24 小时
- 最高可配置到 72 小时
- 每 5 分钟生成一次摘要
- 只保存关键事件、告警、阶段摘要和状态变化
- 不保存与短期详细记忆同等密度的细节
- 必须持久化，服务或 skill 重启后不能清零

长期轻量记忆用于回答：

- 今天大致发生过什么
- 最近几个小时有没有异常
- 什么时候出现过触发事件

## 8. Watch Intent

`watch_intent` 描述用户或 Agent 要关注什么。

`triggered` 模式下：

- 必须启用
- 必须有 `summary`
- 至少提供 `queries` 或 `rules` 之一

第一阶段必须支持通用条件监控，例如：

- 某个状态出现时提醒
- 某个数值低于某个阈值时提醒
- 数值高于某个阈值时提醒
- 某字段变化到指定范围时提醒

商品价格只是其中一个例子，不是唯一场景，也不是主要边界。

因此 `rules` 必须支持基本数值阈值规则，例如：

- `lt`
- `lte`
- `gt`
- `gte`
- `eq`

`observe` 模式下：

- 可以关闭
- 关闭时不主动做触发判断，只做事件记录和时间线问答

## 9. Webhook 策略

第一阶段标准告警出口是企业微信 webhook。

要求：

- webhook 地址应通过环境变量或安全配置读取
- 不应硬编码在 watch spec 文档或代码中
- 必须支持冷却时间
- 必须支持去重窗口
- 必须支持优先级阈值

推荐字段：

- `webhook_url_env`
- `priority_threshold`
- `cooldown_sec`
- `dedupe_window_sec`

完整告警策略见：

- [14-企业微信Webhook告警策略.md](/Users/apple/Desktop/2026/Ayes/docs/14-企业微信Webhook告警策略.md)

## 10. 受控刷新点击

`refresh_click` 是受控辅助动作，只服务于监控任务。

适用场景：

- 某个页面需要刷新状态
- 某个页面需要点击刷新按钮
- 状态页需要周期点击查询

边界：

- 必须由用户明确选择点击点
- 必须绑定窗口或屏幕坐标空间
- 必须支持关闭
- 必须记录点击动作事件
- 不允许扩展为开放式自动操作规划

完整策略见：

- [15-受控刷新点击策略.md](/Users/apple/Desktop/2026/Ayes/docs/15-受控刷新点击策略.md)

## 11. 配置校验规则

第一阶段至少需要校验：

- `mode` 必须是 `triggered` 或 `observe`
- `target.type` 必须是 `process`、`window` 或 `screen`
- `short_term.retain_minutes` 不能超过 15
- `long_term.retain_hours` 不能超过 72
- `screenshot_interval_ms` 必须大于 0
- `ocr_interval_ms` 必须大于 0
- `triggered` 模式下 `watch_intent.enabled` 必须为 true
- `alert.enabled = true` 时必须能解析 webhook 配置
- `refresh_click.enabled = true` 时必须提供点击点和坐标空间

## 12. 第一阶段结论

`watch spec` 是后续实现的配置中心。

任何新增监控模式、采样策略、OCR 频率、记忆策略、webhook 策略、受控动作策略，都必须先更新本文件，再进入实现。
