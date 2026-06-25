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

- `skills/ayes-local/SKILL.md`
- `skills/ayes-local/agents/openai.yaml`
- `skills/ayes-local/references/installation.md`
- `skills/ayes-local/references/commands.md`
- `skills/ayes-local/references/troubleshooting.md`

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
```

其中 `scripts/` 下允许包含由安装脚本生成的本地包装脚本。

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

## 8. `ayes-agent` 最低能力面

为了支撑智能体稳定调用，`ayes-agent` 当前阶段至少应具备：

- `ensure-service`
- `contracts`
- `status`
- `targets`
- `plan-spec`
- `confirm-plan`
- `task`
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
- `confirm-plan`：在补齐 webhook / 目标 / ROI / 点击点后确认装载最终任务
- `task`：读取任务配置或持久化任务信息
- `recent` / `ask` / `screenshot`：构成“随问随答”的最小闭环
- `alerts`：读取最近告警审计结果，回答“是否通知过 / 为什么没通知”
- `control`：读取或变更后台运行状态，例如暂停全部任务、恢复全部任务、打开数据目录提示
- `region-bind-contract`：输出正式 `region-bind` 输入输出格式说明，便于 agent 或外部工具按同一合同产出绑定结果

## 9. 技能文档要求

`SKILL.md` 必须清楚说明：

- 何时应该触发 `ayes-local`
- 何时不应该触发
- 默认调用顺序
- 自然语言任务如何先走草案再走确认
- 如何优先读取 `questions[]` 并逐条补问
- 如何在需要 ROI、多区域和刷新点击点时引用正式 `region-bind` 合同
- 没有目标或 ROI 时如何回退到工作台
- 如何回答用户，而不是只返回原始 JSON

重要求：

- 文档要简洁，但不能模糊
- 不能把安装说明、命令清单、故障排查全部硬塞到一个短文件里
- 对较长内容，应拆到 `references/` 下

## 10. 引用文档要求

`skills/ayes-local/references/` 当前阶段至少应有以下内容：

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
