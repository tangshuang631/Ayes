# 07 Skill 接入与后续演进

## 1. 当前接入策略

当前阶段结论明确：

> 本地服务已经是底座，下一优先级是把它正式收口为 Codex skill + 本地工具入口；Web 工作台降级为轻量配置与核验入口。

原因：

- skill 只是入口，不是核心能力
- 当前最重要的是让 Agent 真正能稳定调用这些能力
- 核心引擎已经具备第一批 API 化边界，继续拖延 skill 化只会让前端越长越重

因此当前阶段的主路线改为：

1. 本地后台服务继续作为唯一状态与能力底座
2. 暴露稳定 HTTP API 与极薄 CLI / tool 包装
3. 在仓库内维护正式 skill 文档与安装骨架
4. Web 工作台只承担配置、启动、核验与排查职责

由于后续要封装成跨平台可接入的 skill，因此 OCR、事件模型、时间线检索接口都必须避免绑定单一平台实现。

## 2. 当前正式接口面

建议第一阶段按未来 skill 化方式设计接口：

- `watch.create`
- `watch.start`
- `watch.stop`
- `watch.status`
- `timeline.query`
- `timeline.recent`
- `timeline.explain`
- `alerts.test`
- `snapshot.inspect`
- `actions.configure_refresh_click`
- `actions.disable_refresh_click`

当前已存在的 HTTP 接口应视为第一版正式 skill 背板，包括：

- `/api/targets`
- `/api/agent/plan-watch-spec`
- `/api/watch/confirm-plan`
- `/api/watch/load-configured`
- `/api/watch/start`
- `/api/watch/stop`
- `/api/watch/status`
- `/api/watch/task/{task_id}`
- `/api/status`
- `/api/screenshot`
- `/api/timeline/recent`
- `/api/timeline/long-term`
- `/api/events`
- `/api/ocr/snippets`
- `/api/memory/items`
- `/api/logs`
- `/api/ask`
- `/api/agent/contracts`

未来 skill 的典型调用方式包括：

- “帮我监控这个商品，有货时通知我”
- “帮我持续观察这个进程，后面我随时问你”
- “帮我看最近 5 分钟有没有出现有货状态”
- “给这个页面配置一个刷新点击点，每 30 秒点一次”

这些调用最终都应落到统一的 `watch spec`，而不是让 skill 直接操作底层采集模块。

其中从当前阶段开始，推荐的正式编排顺序调整为：

1. `targets` 或工作台选择目标
2. `plan-watch-spec` 生成任务草案
3. 智能体复述 `confirmation_summary`
4. `confirm-plan` 确认并装载最终任务
5. `start`
6. `recent / screenshot / ask / alerts / logs` 回读运行证据

## 2.1 当前阶段补充要求

虽然仍需要维护 Web 工作台，但不能走向“只有界面、没有 skill / 工具入口”的方向。

因此当前阶段必须同时推进：

- 面向 Agent 的正式 skill 文档与工具入口
- 人类可用的轻量本地 Web 工作台
- 面向后续 Agent / skill / tool 的 API 化边界

明确要求：

- 前端操作监控任务时，背后应调用统一服务接口
- 前端查看事件、记忆、日志时，背后应调用统一查询接口
- 不允许把核心监控逻辑直接写进浏览器页面或页面局部状态中
- 不允许让 skill 只能靠手写 curl 才能使用
- 至少应提供一个极薄的本地工具命令，屏蔽基础 URL、请求方法和最常用参数拼装

这既是为了后续 Agent 接入，也是为了避免前后端职责混乱。

## 2.2 当前实现校准

当前代码已补出第一批 agent / skill 可调用接口雏形：

- `/api/watch/status`
- `/api/watch/task/{task_id}`
- `/api/timeline/recent`
- `/api/ask`
- `/api/logs`
- `/api/agent/contracts`

其中：

- `/api/agent/contracts` 用于直接暴露当前可用接口合同
- `watch.*` 路径服务于任务状态查询
- `timeline.*` 路径服务于近期事件和记忆查询

这意味着当前阶段已经不再只有“给前端用的页面接口”，而是开始形成后续 Agent 可直接调用的稳定边界。

## 2.3 当前 skill 入口形态

当前阶段的 Ayes skill 应采用以下形态：

- skill 本身只负责告诉 Codex：
  - 什么时候应该使用 Ayes
  - 遇到什么问题先读取哪些接口
  - 何时让用户回到 Web 工作台做目标选择或 ROI 调整
- skill 不承载底层实现逻辑
- skill 优先调用本地 `ayes-agent` 工具命令或等价薄包装
- 若本地服务未启动，skill 应先提示启动 Ayes 服务或桌面启动器

进一步收口后，正式交付形态应明确为：

- 仓库内维护 `skills/ayes-local/` 作为唯一正式模板
- 由 `scripts/install_ayes_local_skill.py` 安装到目标 Agent 的 skill 根目录
- 安装时生成绑定当前仓库路径的 `ayes-agent-local` 包装脚本
- `SKILL.md` 保持简洁，详细安装、命令、排障说明拆到 `references/`
- 智能体默认先调 `ayes-agent-local`，再由其转发到 `ayes.cli.agent_tool` 与本地 HTTP API

推荐的 skill 使用场景包括：

- “帮我把这句话先转成监控任务草案，再告诉我还缺什么配置”
- “帮我读取当前正在监控的目标最近几分钟发生了什么”
- “帮我看看最近有没有弹窗报错”
- “帮我查询这个任务最近有没有命中价格条件”
- “帮我读取当前截图和对应证据”
- “帮我停止或开始当前监控任务”

以下情况应优先让用户回到 Web 工作台：

- 还没有选好监控目标
- 需要重新框选 ROI
- 需要确认当前预览图是不是正确目标
- 需要人工排查截图与 OCR 是否对齐

而以下情况已经应优先交给 skill / CLI / API：

- 简单的屏幕 / 进程级监控任务草案生成
- 价格阈值、有货提醒、错误弹窗等常见 watch intent 编排
- webhook 是否缺失、触发条件是否缺失这类确认问题

## 3. 第二阶段方向

第二阶段再考虑：

- YOLO
- 更完整的 skill 化
- MCP 化
- 面向更多 Agent 的接入

## 4. YOLO 的位置

YOLO 是增强项，不是第一阶段基础依赖。

适合第二阶段加入 YOLO 的条件包括：

- 已经明确垂直场景
- 已经积累真实标注数据
- OCR 和规则无法稳定识别关键非文本目标

## 5. 后续商业化方向

优先切入场景包括：

- 客服后台监控
- 云手机或虚拟屏幕任务监控
- 运维控制台异常监控
- 长时间无人值守任务监控
- 高频工作台异常提示

核心卖点不是“更强 OCR”，而是：

- 可提问的视觉时间线
- 面向重点变化的监控和告警
- 给人类和 Agent 的短时视觉记忆能力
