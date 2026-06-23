# Ayes 开发文档索引

## 1. 文档定位

本文件是 Ayes 的主开发文档，也是 `docs` 目录下的开发索引入口。

使用规则：

1. 先看项目规则
2. 再看本索引
3. 再进入对应模块文档
4. 任何需求变更先改文档，再改实现

项目规则见：

- [00-项目规则.md](/Users/apple/Desktop/2026/Ayes/docs/00-项目规则.md)

## 2. 项目总定义

Ayes 是一个面向人类用户和 AI Agent 的视觉时序回放引擎。

第一阶段的核心目标是：

- 面向指定进程下的所有窗口进行长期监控
- 基于 OCR、向量语义匹配和轻量视觉标签抽取高价值变化
- 保存最近 5-15 分钟可提问的视觉时间线
- 支持企业微信 webhook 告警
- 先服务人类用户提问回放，后续再封装为 skill / tool

## 3. 第一阶段固定决策

以下内容为当前已确定决策：

- 主路线：`OCR + 向量语义匹配 + 轻量视觉标签`
- 首个重点监控对象：指定进程下的所有窗口
- 第一阶段主用户：人类用户自己提问回放
- 第一阶段产品形态：本地工具/服务
- 第一阶段时间范围：最近 5-15 分钟短时视觉时间线
- 第一阶段告警出口：企业微信 webhook
- OCR/skill 方向：核心能力需按跨平台抽象设计，不能绑死单一系统 OCR
- YOLO 作为第二阶段增强项，不作为 MVP 主线

## 4. 文档索引

### 核心规则

- [00-项目规则.md](/Users/apple/Desktop/2026/Ayes/docs/00-项目规则.md)

### 正式开发文档

- [02-产品定位与MVP.md](/Users/apple/Desktop/2026/Ayes/docs/02-产品定位与MVP.md)
- [03-监控对象与采集约束.md](/Users/apple/Desktop/2026/Ayes/docs/03-监控对象与采集约束.md)
- [04-技术路线与语义匹配.md](/Users/apple/Desktop/2026/Ayes/docs/04-技术路线与语义匹配.md)
- [05-系统架构与事件模型.md](/Users/apple/Desktop/2026/Ayes/docs/05-系统架构与事件模型.md)
- [06-时间线问答与告警.md](/Users/apple/Desktop/2026/Ayes/docs/06-时间线问答与告警.md)
- [07-Skill接入与后续演进.md](/Users/apple/Desktop/2026/Ayes/docs/07-Skill接入与后续演进.md)
- [08-技术选型与运行形态.md](/Users/apple/Desktop/2026/Ayes/docs/08-技术选型与运行形态.md)
- [09-OCRProvider接口设计.md](/Users/apple/Desktop/2026/Ayes/docs/09-OCRProvider接口设计.md)
- [10-WatchSpec配置契约.md](/Users/apple/Desktop/2026/Ayes/docs/10-WatchSpec配置契约.md)
- [11-事件模型契约.md](/Users/apple/Desktop/2026/Ayes/docs/11-事件模型契约.md)
- [12-记忆存储设计.md](/Users/apple/Desktop/2026/Ayes/docs/12-记忆存储设计.md)

## 5. 文档维护规则

- 调整定位、边界、MVP 时，优先修改 [02-产品定位与MVP.md](/Users/apple/Desktop/2026/Ayes/docs/02-产品定位与MVP.md)
- 调整监控对象、窗口采集、最小化/遮挡约束时，优先修改 [03-监控对象与采集约束.md](/Users/apple/Desktop/2026/Ayes/docs/03-监控对象与采集约束.md)
- 调整 OCR、语义匹配、轻量视觉标签路线时，优先修改 [04-技术路线与语义匹配.md](/Users/apple/Desktop/2026/Ayes/docs/04-技术路线与语义匹配.md)
- 调整模块边界、事件结构、存储结构时，优先修改 [05-系统架构与事件模型.md](/Users/apple/Desktop/2026/Ayes/docs/05-系统架构与事件模型.md)
- 调整回放问答、告警、用户交互时，优先修改 [06-时间线问答与告警.md](/Users/apple/Desktop/2026/Ayes/docs/06-时间线问答与告警.md)
- 调整 skill / tool / MCP 接入路线和阶段规划时，优先修改 [07-Skill接入与后续演进.md](/Users/apple/Desktop/2026/Ayes/docs/07-Skill接入与后续演进.md)
- 调整语言、依赖、运行方式、OCR 引擎、向量方案、存储方案时，优先修改 [08-技术选型与运行形态.md](/Users/apple/Desktop/2026/Ayes/docs/08-技术选型与运行形态.md)
- 调整 OCR 抽象接口、Provider 优先级、输入输出结构时，优先修改 [09-OCRProvider接口设计.md](/Users/apple/Desktop/2026/Ayes/docs/09-OCRProvider接口设计.md)
- 调整 watch spec、任务模式、采样频率、OCR 频率、记忆策略、webhook 策略、受控动作策略时，优先修改 [10-WatchSpec配置契约.md](/Users/apple/Desktop/2026/Ayes/docs/10-WatchSpec配置契约.md)
- 调整事件字段、事件类型、证据引用、优先级、可观测性和告警/动作审计事件时，优先修改 [11-事件模型契约.md](/Users/apple/Desktop/2026/Ayes/docs/11-事件模型契约.md)
- 调整短期详细记忆、长期轻量记忆、保留时间、清理策略和查询边界时，优先修改 [12-记忆存储设计.md](/Users/apple/Desktop/2026/Ayes/docs/12-记忆存储设计.md)

## 6. 临时文档位置

所有临时文档必须放在：

- [temp](/Users/apple/Desktop/2026/Ayes/docs/temp)

命名规则为：

- `YYYY-MM-DD-目的.md`

如果属于已完成的实施方案，完成开发与验证后必须改名为：

- `YYYY-MM-DD-已完成-目的.md`

临时文档必须使用清单形式维护：

- 未完成项使用 `- [ ]`
- 已完成项使用 `- [x]`

临时文档不能替代正式开发文档。
