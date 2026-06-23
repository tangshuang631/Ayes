# 09 OCR Provider 接口设计

## 1. 设计目标

OCR 是 Ayes 的核心能力之一，但后续要封装成面向 Agent 的 skill，因此 OCR 层必须天然支持跨平台。

本文件定义：

- 统一 OCR 抽象接口
- Provider 能力标识
- 输入输出结构
- 错误模型
- Provider 选择优先级

## 2. 设计原则

- 上层逻辑不依赖具体 OCR 引擎
- 上层只依赖统一 OCR 结果结构
- 平台差异留在 Provider 实现层
- Provider 可插拔、可替换、可回退
- 同一事件链路允许按配置切换 Provider

## 3. 抽象接口

建议定义统一接口：

```python
class OCRProvider:
    name: str
    version: str

    def capabilities(self) -> dict:
        ...

    def recognize(self, image: "ImageInput", options: dict | None = None) -> "OCRResult":
        ...
```

## 4. 输入结构

OCR Provider 的输入建议统一为：

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class ImageInput:
    image_path: Optional[str] = None
    image_bytes: Optional[bytes] = None
    width: Optional[int] = None
    height: Optional[int] = None
    source: Optional[str] = None
    window_id: Optional[str] = None
    region_id: Optional[str] = None
    timestamp: Optional[float] = None
```

要求：

- 至少提供 `image_path` 或 `image_bytes`
- 上层可附带窗口、区域、时间元信息
- Provider 不负责决定业务事件，只负责 OCR 结果

## 5. 输出结构

OCR 输出建议统一为：

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class OCRTextBlock:
    text: str
    confidence: float
    bbox: list[float]
    line_index: Optional[int] = None
    block_type: Optional[str] = None

@dataclass
class OCRResult:
    provider: str
    elapsed_ms: int
    full_text: str
    blocks: List[OCRTextBlock] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw: Optional[dict] = None
```

要求：

- `full_text` 供快速检索和事件摘要使用
- `blocks` 供区域绑定、变化对比、精细检索使用
- `raw` 仅用于保留底层引擎原始结果，不允许上层直接依赖

## 6. 能力标识

每个 Provider 应暴露能力信息，例如：

```python
{
  "languages": ["zh", "en"],
  "supports_angle_cls": True,
  "supports_layout": False,
  "supports_gpu": True,
  "supports_offline": True,
  "supports_multiplatform": True
}
```

用途：

- 运行时选择合适 Provider
- 为不同平台和部署模式做降级
- 支持后续 skill 暴露可用能力

## 7. 错误模型

Provider 需要统一抛出或返回以下错误类型：

- 初始化失败
- 模型缺失
- 输入图像无效
- 推理失败
- 超时
- 能力不支持

建议在业务层将其归一化为：

- `provider_unavailable`
- `invalid_input`
- `recognition_failed`
- `timeout`
- `unsupported_option`

## 8. Provider 优先级

当前优先级建议：

### 8.1 第一优先：PaddleOCR Provider

适用原因：

- 跨平台
- Python 生态成熟
- 中文和英文支持较好
- 便于后续结构化和扩展

### 8.2 第二优先：RapidOCR Provider

适用原因：

- 部署较轻
- 速度和便携性较好
- 可作为低成本替代方案

### 8.3 第三优先：Tesseract Provider

适用原因：

- 生态成熟
- 跨平台广泛
- 作为兜底方案可接受

但不建议作为 Ayes 主路线默认 Provider。

## 9. 与业务层的边界

OCR Provider 不负责：

- 判断事件优先级
- 判断是否命中监控意图
- 生成最终告警
- 生成时间线问答结论

这些工作属于：

- 轻量视觉标签层
- 语义匹配层
- 事件抽取层
- 时间线问答层

## 10. 第一阶段结论

第一阶段正式结论如下：

- 必须先定义跨平台 OCR Provider 抽象
- 上层逻辑只依赖统一 OCR 结果
- 默认优先实现 PaddleOCR Provider
- 允许后续补充 RapidOCR Provider 和 Tesseract Provider
- 平台专属 OCR 只能作为可替换实现，不得成为唯一接口基础
