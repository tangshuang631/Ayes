# Ayes Local 卸载说明

## 默认原则

卸载不应误删用户数据。优先先停止服务和菜单栏，再由用户明确选择是否删除 `runtime/`。

## 停止服务和菜单栏

```bash
pkill -f 'ayes.api.server|uvicorn.*ayes|AyesMenubar|Ayes 菜单栏.app' || true
```

如果安装了 `ayes-agent-local`，也可先查看状态：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local status
```

## 仅卸载 skill 文档和包装脚本

这会保留运行数据备份在原目录外，适合暂时移除入口但保留历史。

```bash
mv "$HOME/.codex/skills/ayes-local" "$HOME/.codex/skills/ayes-local.backup.$(date +%Y%m%d-%H%M%S)"
```

## 完整删除安装态

确认不再需要任务、截图、记忆和日志后：

```bash
rm -rf "$HOME/.codex/skills/ayes-local"
```

## 删除某个任务而不是整个 skill

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local delete-task --task-id <task_id>
```

## OpenClaw 或其他 Agent

如果安装到自定义 skill 根目录，把路径替换成：

```text
<skill_root>/ayes-local
```

卸载前应先确认对应 Agent 没有正在使用该 skill。

## 重新安装

重新安装不会默认删除已有 runtime。安装脚本会保留目标目录里的 `runtime/`：

```bash
python3 scripts/install_ayes_local_skill.py
```
