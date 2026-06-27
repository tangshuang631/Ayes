# Ayes Local 安装说明

## 1. 安装目标

`ayes-local` 的正式安装形态是：

- 从公开发行仓库复制 skill 模板
- skill 文档安装到目标智能体的 skill 根目录
- 同时生成绑定安装目录运行时的本地包装脚本

公开发行仓库根目录应包含：

```text
SKILL.md
README.md
agents/
references/
scripts/
src/
```

该目录是无状态产物模板，不包含任何用户运行态状态、截图、记忆、日志或 webhook。

默认推荐安装到 Codex：

```bash
git clone https://github.com/tangshuang631/Ayes.git ayes-local
cd ayes-local
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/install_ayes_local_skill.py --skill-root "$HOME/.codex/skills" --python-bin "$PWD/.venv/bin/python"
```

默认会安装到：

```text
$HOME/.codex/skills/ayes-local/
```

并生成：

```text
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local
$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local
```

安装脚本还会尽量创建：

```text
$HOME/.local/bin/ayes-agent-local
$HOME/.local/bin/ayes-menubar-local
```

如果目标位置已被用户自定义文件占用，安装不会报错覆盖；这种情况下仍以安装目录里的绝对 wrapper 为准。

## 2. 自定义安装目录

如果是 OpenClaw 或其他本地 Agent 环境，可指定 skill 根目录：

```bash
.venv/bin/python scripts/install_ayes_local_skill.py --skill-root /path/to/agent/skills --python-bin "$PWD/.venv/bin/python"
```

## 3. 安装产物

安装后目录应至少包含：

```text
<skill_root>/ayes-local/
  SKILL.md
  README.md
  requirements.txt
  agents/openai.yaml
  references/
  scripts/ayes-agent-local
  scripts/ayes-menubar-local
  runtime/
```

其中：

- `scripts/ayes-agent-local` 是最优先给智能体调用的本地命令包装
- `scripts/ayes-menubar-local` 是 macOS 原生 `Ayes 菜单栏.app` 的本地菜单栏控制入口
- `runtime/` 是安装实例自己的运行目录，数据库、日志、截图、证据和按任务切割的记忆文件默认写入这里
- 每个任务的数据目录为 `runtime/tasks/<date>/<task_id>/`；短期紧凑明细在 `memory/short/`，长期简略摘要在 `memory/long/`
- 安装后默认无任务、无 webhook、无已启用视觉增强，后续全部通过用户与 agent 的对话逐步补齐

## 4. 安装后验证

先验证本地包装是否存在：

```bash
ls -l "$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local"
```

如果希望检查全局可发现入口，也可以看：

```bash
ls -l "$HOME/.local/bin/ayes-agent-local"
```

再验证服务与接口：

```bash
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" ensure-service
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" contracts
"$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local" status
"$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local"
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

如果在 macOS 上需要一个用户可见的小图标用于手动暂停、恢复和打开数据目录，可直接运行：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-menubar-local
```

当前 menubar 默认提供：

- 单色灰白体系的常驻状态图标
- 当前状态、当前任务、当前监控目标摘要
- 当前 ROI 列表摘要
- 最近命中摘要
- 最近任务切换
- 手动暂停、恢复、打开 ROI 管理、打开设置和打开数据目录

安装后的包装脚本会导出 `AYES_RUNTIME_DIR=$HOME/.codex/skills/ayes-local/runtime`。安装器默认会把 wrapper 绑定到执行安装脚本的 Python 解释器；因此正式安装后，agent 在新窗口里直接调用安装态 wrapper 时，不必再先搜索 PATH 或重建依赖环境。

因此正式安装使用时，运行态不会写入公开发行仓库或开发仓库。

任务记忆策略也存放在该安装实例的 `runtime/` 中：

- 短期紧凑明细默认保留 7 天，最高 14 天
- 长期简略记忆默认保留 14 天，最高 30 天
- 每个任务可以单独打开“永久保留”，打开后该任务不再自动清理记忆
- 记忆文件按任务和日期切割，文件名包含日期、任务 ID 和 details/summary 类型；默认 details 文件只保留摘要、时间、来源、区域、关键词和质量信息，不写 OCR blocks/bbox 等重字段

## 6. 重新安装时机

以下情况建议重新执行安装脚本：

- 公开发行仓库更新
- `src/ayes/cli/agent_tool.py` 命令面改动
- 仓库路径变化
- 想切换到新的 skill 根目录
