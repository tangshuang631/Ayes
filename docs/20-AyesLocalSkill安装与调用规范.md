# 20 Ayes Local Skill 安装与调用规范

## 1. 文档目标

本文件定义 `ayes-local` 这个正式 skill 的：

- 定位
- 安装流
- 目录产物
- 调用规范
- 后台运行配合方式
- 失败回退要求

后续只要调整 `ayes-local` 的 skill 文案、安装方式、本地工具包装或智能体调用契约，都必须先修改本文件，再改实现。

## 2. 定位

`ayes-local` 不是一个只会读几条 HTTP 接口的演示 skill。

它的正式目标是：

- 让 Codex / OpenClaw / 同类智能体能够把 Ayes 当成“本地持续看屏幕的眼睛”
- 在用户已经选好目标、配置好 ROI 并启动后台监控后
- 通过稳定本地工具和 HTTP 背板读取：
  - 当前监控状态
  - 当前截图证据
  - 最近几分钟事件
  - 最近告警结果
  - 短期记忆与问答结果
  - 长期摘要
  - 最近日志

它必须服务于“长期后台运行 + 随问随答”，而不是一次性脚本调用。

并且它还必须支持：

- 通过对话式补问完成目标与 ROI 绑定
- 在后台持续运行时回读当前任务状态
- 与桌面小图标/状态栏菜单共享同一后台服务状态

## 3. 组成产物

`ayes-local` 当前阶段至少应由以下产物组成：

### 3.1 仓库内正式 skill

- `skills/final/ayes-local/SKILL.md`
- `skills/final/ayes-local/agents/openai.yaml`
- `skills/final/ayes-local/references/installation.md`
- `skills/final/ayes-local/references/commands.md`
- `skills/final/ayes-local/references/troubleshooting.md`

这里的 `skills/final/ayes-local/` 必须视为最终交付产物目录。

额外约束：

- 目录内只放可安装给最终用户的正式无状态 skill 模板
- 不得携带用户任务、webhook、截图、日志、短期/长期记忆等运行态状态
- 用户首次安装后，应通过 agent 对话和正式命令面按需补齐所有真实配置
- 任何开发期或本机测试期使用过的真实企业微信 webhook，都不得写入正式 skill 模板、示例产物或安装结果

### 3.2 本地工具入口

- `ayes-agent`

该工具必须作为智能体优先调用的本地命令包装，而不是要求 skill 手写 curl。

### 3.3 安装脚本

当前阶段必须提供一个正式安装脚本，用于把 `ayes-local` 安装到指定 skill 根目录，并生成本地机器可直接调用的包装脚本。

要求：

- 支持默认安装到 Codex skill 根目录
- 支持自定义目标目录，方便 OpenClaw 或其他 Agent 环境复用
- 支持生成绑定当前仓库绝对路径的本地脚本包装

当前脚本实现路径应固定为：

- `scripts/install_ayes_local_skill.py`

## 4. 安装目标目录约定

当前阶段采用“仓库内 skill 模板 + 安装脚本落地到 Agent skill 根目录”的方式。

默认推荐目标包括：

- Codex：`$HOME/.codex/skills/`
- 其他智能体：由用户手动指定 skill 根目录

安装结果目录建议为：

```text
<skill_root>/ayes-local/
  SKILL.md
  agents/openai.yaml
  references/
  scripts/
  runtime/
```

其中 `scripts/` 下允许包含由安装脚本生成的本地包装脚本。
其中 `runtime/` 是该安装实例的本地运行态目录，存放数据库、截图、日志、证据和按任务切割的记忆文件；正式 skill 模板不得携带该目录。

记忆运行态约定：

- 任务记忆策略、短期详细记忆、长期简略记忆都必须写入安装后的 `runtime/`
- 不得默认写入开发仓库 `/Users/apple/Desktop/2026/Ayes/runtime`
- 每个任务必须拥有独立目录：`runtime/memory/<task_id>/`
- 短期详细记忆按日期写入 `runtime/memory/<task_id>/short/YYYY-MM-DD-<task_id>-details.jsonl`
- 长期简略记忆按日期写入 `runtime/memory/<task_id>/long/YYYY-MM-DD-<task_id>-summary.jsonl`
- 短期详细记忆默认保留 7 天、最高 14 天
- 长期简略记忆默认保留 14 天、最高 30 天
- 每个任务必须支持独立关闭自动清理；关闭后该任务记忆不再自动删除

## 5. 安装流要求

当前阶段正式安装流必须满足：

1. 用户在本地仓库执行安装脚本
2. 安装脚本将 `ayes-local` 模板复制到目标 skill 根目录
3. 安装脚本写入绑定当前仓库绝对路径的本地工具包装
4. 安装脚本输出：
   - 安装后的 skill 路径
   - 如何验证安装
   - 如何验证本地 Ayes 服务

安装脚本至少应生成以下能力包装：

- 确保本地 Ayes 服务已启动
- 调用 `ayes-agent` 本地命令

当前生成包装脚本的推荐名称为：

- `ayes-agent-local`
- `ayes-menubar-local`

包装脚本必须导出：

- `PYTHONPATH=<repo_root>/src`
- `AYES_RUNTIME_DIR=<skill_root>/ayes-local/runtime`

这样安装后的运行态不会落到开发仓库 `runtime/`。

## 6. 调用入口要求

智能体侧优先使用顺序必须明确为：

1. 先使用安装后生成的本地包装脚本
2. 包装脚本内部再调用仓库里的 `ayes.cli.agent_tool`
3. `ayes-agent` 再调用本地 HTTP API

不推荐顺序：

- skill 直接硬写 curl
- skill 直接拼接大量 HTTP URL 和 JSON
- 每次会话都重新发明服务启动方式

## 7. 后台运行配合方式

`ayes-local` 要真正支持“AI 的眼睛”，前提不是 skill 自己常驻，而是：

- Ayes 后台服务常驻
- 监控任务常驻
- skill 随时接入读取最近状态与时间线

因此必须明确：

- skill 不是后台监控主进程
- Ayes 后台服务才是唯一长期运行底座
- skill 负责：
  - 确保服务可达
  - 读取状态
  - 读取证据
  - 读取最近告警
  - 发起问答
  - 必要时启动或停止当前监控任务

并且必须明确：

- webhook / 本地通知等即时提醒由后台服务直接负责
- skill / agent 不作为第一触发通知渠道
- skill / agent 负责回读与解释，而不是代替服务发通知
- 用户一旦明确授权并提供 webhook，后台服务就应能在 Codex / OpenClaw 不在线回复时继续独立完成企业微信外发

## 8. `ayes-agent` 最低能力面

为了支撑智能体稳定调用，`ayes-agent` 当前阶段至少应具备：

- `ensure-service`
- `contracts`
- `status`
- `targets`
- `plan-spec`
- `confirm-plan`
- `task`
- `observe-live`
- `recent`
- `alerts`
- `ask`
- `screenshot`
- `run-once`
- `start`
- `stop`
- `load-spec`

当前已正式纳入命令面的扩展项还包括：

- `memory-items`
- `logs`
- `long-term`
- `control`
- `region-bind-contract`

其中：

- `ensure-service`：保证本地 Ayes 服务可复用或被拉起
- `targets`：读取候选目标摘要
- `plan-spec`：把自然语言和已知目标转成任务草案、缺失项与确认摘要
- `plan-spec`：除 `questions[] / region_intents[] / action_intents[]` 外，还必须返回 `setup_guidance[]`，用于缺配置时通过对话继续补齐
- `confirm-plan`：在补齐 webhook / 目标 / ROI / 点击点后确认装载最终任务
- `task`：读取任务配置或持久化任务信息
- `tasks` / `switch-task` / `delete-task`：列出、恢复、切换或删除历史任务及其独立记忆
- `memory-policy`：查看或调整单个任务的短期详细记忆、长期简略记忆和自动清理策略
- `memory-cleanup`：按单个任务策略立即执行一次过期记忆清理
- `observe-live`：聚合当前状态、截图、近期事件、短期记忆、告警、日志和证据质量，是 agent 追问屏幕现状时的优先入口
- `observe-live.agent_hints.task_context`：告诉 agent 当前正在看哪个任务、是否只是回读持久化证据、有哪些历史任务可恢复
- `recent` / `ask` / `screenshot`：构成细颗粒追问和回退闭环
- `alerts`：读取最近告警审计结果，回答“是否通知过 / 为什么没通知”
- `control`：读取或变更后台运行状态，例如暂停全部任务、恢复全部任务、打开数据目录提示
- `control cleanup-reminder --next-check-after-days N`：调整清理提醒间隔，默认 7 天
- `region-bind-contract`：输出正式 `region-bind` 输入输出格式说明，便于 agent 或外部工具按同一合同产出绑定结果

补充要求：

- `start` 在默认本地服务地址上启动持续监控后，应尽力自动拉起 macOS 菜单栏控制入口；菜单栏失败不得导致监控启动失败
- `screenshot` 必须返回最近真实采样帧的唯一文件路径，而不是只返回可能缓存的固定文件名
- 菜单栏必须可进入 ROI 管理和设置界面

## 9. 技能文档要求

`SKILL.md` 必须清楚说明：

- 何时应该触发 `ayes-local`
- 何时不应该触发
- 默认调用顺序
- 自然语言任务如何先走草案再走确认
- 如何优先读取 `questions[]` 并逐条补问
- 如何在 webhook、本地视觉模型或其他依赖未就绪时读取 `setup_guidance[]` 并继续指导用户完成配置
- 如何在用户说“继续之前的任务”时先定位 `task_id`，再恢复并继续追问
- 如何在需要 ROI、多区域和刷新点击点时引用正式 `region-bind` 合同
- 没有目标或 ROI 时如何回退到工作台
- 如何回答用户，而不是只返回原始 JSON

重要求：

- 文档要简洁，但不能模糊
- 不能把安装说明、命令清单、故障排查全部硬塞到一个短文件里
- 对较长内容，应拆到 `references/` 下

## 10. 引用文档要求

`skills/final/ayes-local/references/` 当前阶段至少应有以下内容：

- 安装说明
- 命令清单
- 后台服务与故障排查说明
- `region-bind` 参考说明
- 后台控制与托盘状态说明

作用：

- 保持 `SKILL.md` 简洁
- 让智能体按需读取更详细说明
- 降低 skill 主文档上下文膨胀

## 11. 回答规范

智能体通过 `ayes-local` 给用户回答时，默认应优先输出：

1. 当前读取的是哪个任务 / 哪个目标
2. 读取的时间范围
3. 关键证据
4. 结论
5. 若证据不足或目标未配置，明确给出下一步

不允许：

- 只回一坨 JSON
- 不说明时间范围
- 不说明证据来源
- 将“未配置目标”伪装成“没有发生任何事”

## 12. 失败回退要求

以下情况必须有明确回退：

### 12.1 本地服务不可达

- 先尝试 `ensure-service`
- 若仍失败，返回可诊断错误
- 错误中应尽量附带最近日志线索

### 12.2 当前没有已装载任务

- 明确说明当前无任务
- 优先尝试通过 `plan-spec -> confirm-plan` 帮用户完成任务配置
- 若必须人工框选 ROI 或点击点，再引导用户回到选择器/工作台完成绑定

### 12.3 当前无可用截图或 OCR 很稀疏

- 明确说明当前证据不足
- 告诉用户应该核验目标预览、ROI 或可观测性状态

### 12.4 当前处于全局暂停

- 明确说明后台任务当前已暂停
- 返回最近一次暂停时间和原因
- 如果用户希望继续监控，优先调用 `control resume-all`

## 12.5 webhook 与自定义消息边界

- 正式发布给用户的 `ayes-local` skill 必须保持无状态，不得预置任何真实 webhook 地址
- 用户在本机明确授权后，agent 才能把 webhook 通过 `confirm-plan` 写入当前任务配置
- 如果用户没有自定义消息模板，默认发送任务创建阶段由 agent 确认后的提醒内容
- 如果用户要求更灵活的消息标题或正文，应通过 `confirm-plan` 写入：
  - `alert_message_title`
  - `alert_message_template`
- 自定义消息模板应至少支持：
  - `{task_id}`
  - `{timestamp}`
  - `{process_name}`
  - `{window_title}`
  - `{priority}`
  - `{confidence}`
  - `{summary}`
  - `{event_id}`

## 12.6 安装后 smoke 验证要求

当前正式安装后 smoke 入口为：

```bash
python3 scripts/smoke_ayes_local_skill.py
```

它应至少支持两类验证：

1. 本地 round-trip smoke
2. 真实企业微信外发 smoke

本地 round-trip smoke 用于证明：

- 安装脚本能生成可执行的 `ayes-agent-local`
- smoke 会先回收可安全关闭的旧本地服务，再验证当前安装产物
- `plan-spec -> confirm-plan -> start -> run-once -> alerts/ask` 主链路可跑通
- 本地临时 webhook 接收端能真实收到 POST

真实企业微信外发 smoke 用于证明：

- 用户在本机授权并提供真实 webhook 后
- Ayes 后台服务可以独立完成企业微信通知
- 即使 Codex / OpenClaw 不是即时在线回复，也不影响 webhook 成功外发

如果用户要验证自定义消息标题与正文模板，安装后 smoke 还应支持：

```bash
python3 scripts/smoke_ayes_local_skill.py \
  --alert-message-title "库存提醒" \
  --alert-message-template "任务 {task_id} 命中：{summary}"
```

## 13. 当前阶段结论

`ayes-local` 必须被视为 Ayes 面向 Agent 的正式交付物，而不是附属 demo。

是否真正达标，不看“有没有一个 `SKILL.md`”，而看以下事实是否同时成立：

- 有正式文档约束
- 有可安装 skill 目录
- 有明确安装流
- 有本地工具包装
- 有后台服务配合方式
- 有正式 `region-bind` 协作合同
- 有后台暂停 / 恢复 / 退出语义
- 有最小随问随答闭环
- 有测试覆盖核心安装与调用契约
