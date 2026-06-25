# 23 Region Bind 与后台控制契约

## 1. 文档目标

本文件收口以下正式合同：

- `region-bind` 的稳定输入输出格式
- 智能体通过 skill 完成 ROI 绑定的调用流
- 桌面小图标/状态栏菜单对后台任务的控制合同

后续只要调整 ROI 绑定、外部选择器结果格式、截图标注结果格式、托盘暂停恢复语义或后台退出语义，都必须先修改本文件，再修改实现。

## 2. 设计原则

- `watch spec` 仍然是唯一执行契约
- `region-bind` 只解决“区域意图如何变成正式 ROI 坐标”
- 智能体不应口头编造像素坐标
- 外部选择器、截图标注器、轻量桌面工具和 skill 必须共享同一份绑定结果结构
- 后台控制必须独立于 Web 页面是否打开
- 暂停、恢复、退出必须有稳定审计事件

## 3. Region Bind 合同定位

`region-bind` 是 `watch plan draft.region_intents[]` 与最终 `watch spec.target.regions[]` 之间的正式桥梁。

它用于解决以下场景：

- 用户通过智能体说“价格区和库存区重点盯一下”
- 智能体已经知道要监控哪些区域，但还没有真实坐标
- 外部选择器返回了多个框选结果
- 截图标注器返回了多个矩形和语义标签
- 用户要给某个任务绑定多区域 ROI

## 4. 正式输入结构

### 4.1 `region_bind_request`

```json
{
  "bind_version": "1.0",
  "task_id": "task_price_watch",
  "target_ref": {
    "type": "process",
    "process_name": "Google Chrome",
    "window_id": 1024
  },
  "capture_ref": {
    "capture_id": "cap_20260625_120100",
    "image_path": "/abs/path/runtime/evidence/2026-06-25__task_price_watch/cap.png",
    "image_width": 1440,
    "image_height": 900
  },
  "region_intents": [
    {
      "region_intent_id": "ri_price",
      "name": "价格区",
      "purpose": "读取价格并判断是否低于阈值",
      "required": true
    },
    {
      "region_intent_id": "ri_stock",
      "name": "库存区",
      "purpose": "判断是否有货",
      "required": false
    }
  ]
}
```

要求：

- `task_id` 必须关联到当前草案或待确认任务
- `target_ref` 必须说明绑定结果对应哪个监控目标
- `capture_ref` 必须指向本次绑定所基于的截图或预览
- `region_intents[]` 必须来自规划器草案，而不是临时自由文本

### 4.2 `region_bind_result`

```json
{
  "bind_version": "1.0",
  "task_id": "task_price_watch",
  "target_ref": {
    "type": "process",
    "process_name": "Google Chrome",
    "window_id": 1024
  },
  "capture_ref": {
    "capture_id": "cap_20260625_120100",
    "image_width": 1440,
    "image_height": 900
  },
  "region_bindings": [
    {
      "region_intent_id": "ri_price",
      "region_id": "roi_price",
      "name": "价格区",
      "x": 1012,
      "y": 188,
      "w": 196,
      "h": 72,
      "coordinate_space": "target",
      "binding_space": "capture_image",
      "source": "external_selector",
      "confidence": 0.98,
      "notes": "价格文本和货币符号位于同一区域"
    },
    {
      "region_intent_id": "ri_stock",
      "region_id": "roi_stock",
      "name": "库存区",
      "x": 1004,
      "y": 278,
      "w": 220,
      "h": 84,
      "coordinate_space": "target",
      "binding_space": "capture_image",
      "source": "screenshot_annotation",
      "confidence": 0.93
    }
  ],
  "unbound_region_intents": []
}
```

正式要求：

- `region_bindings[]` 必须可直接交给 `confirm-plan`
- `coordinate_space` 在 v1 默认使用 `target`
- `binding_space` 用于说明这组坐标是基于哪种截图空间产生的
- `source` 当前至少支持：
  - `external_selector`
  - `screenshot_annotation`
  - `manual_coordinates`
- `confidence` 为可选字段，但如果外部工具能提供，应保留
- 如有未成功绑定的区域，必须写入 `unbound_region_intents[]`，不能静默丢失

## 5. 与 `confirm-plan` 的衔接

`confirm-plan` 必须接受：

- 规划器返回的 `task_id`
- 已补齐的普通确认字段
- `region_bind_result.region_bindings[]`
- 可选的刷新点击点绑定结果

转化要求：

- `region_intents[].status = bound`
- `watch spec.target.regions[]` 按绑定结果生成
- 若存在 `required = true` 但仍未绑定的区域，`confirm-plan` 不得直接进入可执行状态

## 6. Skill 调用流

### 6.1 纯对话到 ROI 绑定

1. 智能体调用 `ayes-agent plan-spec`
2. 读取 `questions[]`、`region_intents[]`、`action_intents[]`
3. 向用户补问目标、监控意图、区域范围、是否需要刷新点击
4. 若仍缺 ROI 坐标，智能体调用外部选择器或截图标注器
5. 外部工具返回 `region_bind_result`
6. 智能体调用 `ayes-agent confirm-plan`
7. `confirm-plan` 产出最终 `watch spec`
8. 智能体调用 `ayes-agent start` 或等价装载启动入口

### 6.2 允许的回退

如果当前无法获得 ROI 绑定结果：

- 可以把任务退回“整目标监控”
- 但前提是该区域并非 `required = true`
- 必须在确认摘要中明确说明“当前未绑定局部区域，将监控整个目标”

如果区域是必需的：

- 必须保持 `needs_confirmation`
- 必须继续等待选择器/标注器结果或人工补坐标

## 7. 刷新点击点绑定补充

受控刷新点击与 ROI 绑定一样，也必须支持外部绑定结果。

建议结构：

```json
{
  "action_bindings": [
    {
      "action_type": "refresh_click",
      "point_id": "refresh_main",
      "x": 1180,
      "y": 126,
      "coordinate_space": "target",
      "binding_space": "capture_image",
      "source": "external_selector",
      "confidence": 0.97
    }
  ]
}
```

## 8. 后台控制合同

### 8.1 控制对象

后台控制合同不直接操作单帧采样细节，而是面向服务级状态：

- 服务是否运行
- 当前是否有任务运行
- 当前是否处于全局暂停
- 是否存在待处理清理提醒

### 8.2 托盘/状态栏菜单最低能力

桌面小图标菜单至少必须支持：

- `open_workbench`
- `show_status`
- `pause_all_watches`
- `resume_all_watches`
- `open_data_dir`
- `exit_ayes`

### 8.3 控制语义

#### `pause_all_watches`

- 暂停采样、OCR、视觉增强、告警发送和 `refresh_click`
- 已加载任务不得丢失
- 现有短期/长期记忆不得清空
- 必须写入 `watch_paused` 或等价审计事件

#### `resume_all_watches`

- 在原任务配置上继续运行
- 必须写入 `watch_resumed` 或等价审计事件

#### `exit_ayes`

- 若当前仍有任务运行，必须先给出显式确认
- 若用户确认退出，必须先停止监控循环，再持久化必要状态，再退出服务
- 不允许因为 Web 页面关闭、skill 会话结束或 Agent 断线而自动执行

## 9. 7 天清理提醒合同

后台控制层还必须暴露数据清理提醒状态。

建议结构：

```json
{
  "cleanup_reminder": {
    "enabled": true,
    "last_prompt_at": "2026-06-25T12:10:00+08:00",
    "snoozed_until": null,
    "suppress_forever": false,
    "data_dir": "/abs/path/runtime/archive",
    "next_check_after_days": 7
  }
}
```

正式要求：

- 每次提醒都必须可追溯
- 提醒动作应允许用户直接打开数据目录
- 用户选择“不再提醒我”后，必须持久化 `suppress_forever = true`

## 10. 第一阶段结论

- `region-bind` 必须成为独立正式合同，而不是散落在 skill 文案中的描述
- ROI 绑定、刷新点击点绑定和 `confirm-plan` 必须共享同一套稳定结构
- 桌面小图标菜单必须成为后台运行时的人类控制入口
- 7 天清理提醒必须进入后台控制合同与审计链路
