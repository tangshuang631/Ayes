# Ayes Local 安装说明

## 1. 安装目标

`ayes-local` 的正式安装形态是：

- skill 文档安装到目标智能体的 skill 根目录
- 同时生成一个绑定当前 Ayes 仓库路径的本地包装脚本

默认推荐安装到 Codex：

```bash
cd /Users/apple/Desktop/2026/Ayes
python3 scripts/install_ayes_local_skill.py
```

默认会安装到：

```text
$HOME/.codex/skills/ayes-local/
```

并生成：

```text
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local
```

## 2. 自定义安装目录

如果是 OpenClaw 或其他本地 Agent 环境，可指定 skill 根目录：

```bash
cd /Users/apple/Desktop/2026/Ayes
python3 scripts/install_ayes_local_skill.py --skill-root /path/to/agent/skills
```

## 3. 安装产物

安装后目录应至少包含：

```text
<skill_root>/ayes-local/
  SKILL.md
  agents/openai.yaml
  references/
  scripts/ayes-agent-local
```

其中 `scripts/ayes-agent-local` 是最优先给智能体调用的本地命令包装。

## 4. 安装后验证

先验证本地包装是否存在：

```bash
ls -l "$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local"
```

再验证服务与接口：

```bash
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" ensure-service
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" contracts
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" status
```

## 5. 后台配合原则

`ayes-local` skill 本身不是常驻后台。

真正长期运行的是：

- Ayes 本地后台服务
- Ayes 监控任务

skill 只是随时接入读取：

- 当前状态
- 最近截图
- 近期事件
- 短期记忆
- 长期摘要
- 最近日志

## 6. 重新安装时机

以下情况建议重新执行安装脚本：

- `skills/ayes-local/` 文档结构改动
- `src/ayes/cli/agent_tool.py` 命令面改动
- 仓库路径变化
- 想切换到新的 skill 根目录
