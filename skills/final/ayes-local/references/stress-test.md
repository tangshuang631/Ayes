# Ayes Local 长跑压测说明

当前文档只定义第一版压测方法；发行前硬化阶段可以先不实际跑 8 小时。

## 目标

验证长时间运行时：

- 服务不崩溃。
- 菜单栏仍可打开。
- 采样间隔稳定。
- `screenshots/latest/` 不无限增长。
- 默认不写入大量 `screenshots/evidence/`。
- SQLite、日志、短期记忆和长期摘要体积增长可控。

## 推荐 8 小时配置

```bash
ayes-agent-local sampling --interval-sec 6 --quality standard --save-ocr-screenshots false
ayes-agent-local start
```

## 观察命令

每 30 分钟记录一次：

```bash
ayes-agent-local status
ayes-agent-local query --minutes 30 --question "最近半小时主要发生了什么"
du -sh "$HOME/.codex/skills/ayes-local/runtime"
find "$HOME/.codex/skills/ayes-local/runtime/tasks" -path '*/screenshots/latest/*' -type f | wc -l
find "$HOME/.codex/skills/ayes-local/runtime/tasks" -path '*/screenshots/evidence/*' -type f | wc -l
```

## 失败判定

- 服务退出或 `status` 不可用。
- 菜单栏无法打开。
- 默认配置下 evidence 图片持续增长。
- latest 图片不清理，持续无限增长。
- runtime 在默认配置下异常快速增长。
- 普通问题需要读取 logs 或原始 JSONL 才能回答。

## 高写入模式单独测试

以下配置不应作为默认发行策略，只用于评估极限：

```bash
ayes-agent-local sampling --interval-sec 0.5 --quality original --save-ocr-screenshots true
```

该模式会显著增加磁盘占用和 SSD 写入量，必须在测试说明里标注风险。
