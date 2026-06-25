# 22 OCR 与视觉融合结构化观察

## 1. 文档目标

本文件定义 Ayes 如何把 OCR 和可选视觉增强统一成一份结构化观察结果。

目标不是让视觉模型替代 OCR，而是解决以下问题：

- OCR 与视觉增强目前是两条平行结果，后续难以被统一消费
- 问答、事件、日志、skill 回答需要共享同一份“屏幕上读到了什么”
- 文字、位置、区域、视觉补充语义必须能进入统一结构

## 2. 设计原则

- OCR 仍是第一阶段主链路
- 视觉增强是按需补充层，不得变成每帧主路径
- 统一结构必须同时保留文本、位置、区域和视觉语义
- 上层问答、事件、日志、skill 回答只依赖统一结构，不直接依赖底层 provider 原始输出

## 3. Structured Observation 结构

每次 ROI 或整目标采样后，必须生成统一的结构化观察：

```json
{
  "observation_version": "1.0",
  "source": "ocr|ocr+vision",
  "region": {
    "region_id": "roi_price",
    "name": "价格区"
  },
  "text": {
    "full_text": "当前价格 ¥199 库存充足",
    "char_count": 13,
    "provider": "vision",
    "confidence": 0.96,
    "blocks": []
  },
  "layout": {
    "primary_direction": "left_top",
    "dense_text": false,
    "block_count": 2
  },
  "visual": {
    "provider": "ollama",
    "model": "qwen2.5vl:7b",
    "summary": "价格区显示 199 元，旁边出现绿色购买按钮",
    "detail_lines": [
      "主数字位于左上偏中位置",
      "右侧有明显按钮样式区域"
    ],
    "labels": ["price_like", "button_like"]
  },
  "entities": [
    {
      "type": "numeric",
      "field": "price",
      "value": 199.0,
      "unit": "CNY",
      "evidence": "当前价格 ¥199"
    }
  ],
  "warnings": [],
  "fusion_notes": [
    "OCR 文本较稀疏，已补充视觉摘要"
  ]
}
```

## 4. 统一结构最少字段

默认本地视觉模型应优先使用 `qwen2.5vl:7b`，因为该模型可直接通过 Ollama 拉取并接入实时监控链路。`Molmo` 可作为实验增强模型单独验证，不纳入默认路径。

本地视觉增强并不是默认主链路。实际运行时应优先使用 OCR，仅在高视觉负载场景下调用本地模型，例如图表、按钮、颜色、图标、布局或 OCR 稀疏但图像结构明显的区域；纯文本、纯数字、价格阈值等任务默认不应触发本地视觉模型。

第一阶段至少必须输出：

- `text.full_text`
- `text.blocks`
- `text.provider`
- `text.char_count`
- `layout.block_count`
- `visual.summary`
- `visual.detail_lines`
- `entities`
- `fusion_notes`

即使未启用视觉增强，也必须输出统一结构；只是 `visual.*` 为空。

## 5. OCR 与视觉增强的职责

OCR 层负责：

- 文本读取
- 文本块与坐标
- 置信度与稀疏度

视觉增强层负责：

- 图表、图片、图标、按钮样式、颜色状态等非文本补充
- 对 OCR 稀疏或视觉型区域给出摘要与细节行
- 对需要视觉理解的问题提供补充语义

融合层负责：

- 合并 OCR 和视觉结果
- 统一输出文本、布局、视觉、实体和警告
- 给上层提供可稳定消费的观察对象

## 6. 与事件模型的关系

统一结构化观察不替代事件模型，而是：

- 成为 OCR 事件和视觉事件共享的结构化载荷
- 支撑问答链路、日志、近期原始读取结果和 skill 回答
- 作为后续轻量实体抽取和规则匹配的基础输入

第一阶段要求：

- OCR 事件必须暴露 `structured_observation`
- 视觉增强事件也必须暴露 `structured_observation`
- 问答结果中应能直接回传 `structured_observations`

## 7. 与 watch intent 的关系

数值条件、文本条件和视觉型条件都应优先基于统一结构做匹配。

例如：

- `价格低于 299`：优先读取 `entities`
- `最近几分钟有没有报错弹窗`：优先读取文本块和视觉摘要
- `图里是不是出现红色下跌走势`：OCR 不足时读取视觉补充摘要

## 8. 第一阶段实现结论

当前阶段正式结论如下：

- Ayes 必须新增统一 `structured observation` 层
- OCR 与视觉增强都要进入同一结构
- 上层 API、问答、日志、skill 回答都应逐步依赖该统一结构
- 视觉增强只作为按需补强，不改变 OCR 主链路定位
