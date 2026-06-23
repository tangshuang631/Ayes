# Ayes

Ayes 是一个面向人类用户和 AI Agent 的视觉监控、时序记忆与问答工具。

当前仓库先按文档约束落地第一阶段代码骨架：

- `watch spec` 配置契约
- 统一事件模型
- 监控目标数据结构
- macOS 窗口发现最小实现
- 最小 OCR provider 链路
- 最小短期记忆与问答链路

运行测试：

```bash
PYTHONPATH=src python3 -m pytest -q
```

## 当前 MVP 可人工测试步骤

1. 校验 watch spec

```bash
PYTHONPATH=src python3 -m ayes.cli.main validate-spec runtime/mvp-observe-screen.json
```

2. 列出当前窗口候选

```bash
PYTHONPATH=src python3 -m ayes.cli.main list-windows
```

如果要测试窗口监控，可先从输出中挑一个 `window_id`，再生成窗口监控 spec：

```bash
PYTHONPATH=src python3 -m ayes.cli.main create-window-spec 1100 --output runtime/mvp-observe-window.json
```

3. 执行一次最小监控链路

```bash
PYTHONPATH=src python3 -m ayes.cli.main run-once runtime/mvp-observe-screen.json
```

4. 连续执行两次监控并导出事件文件

```bash
PYTHONPATH=src python3 -m ayes.cli.main run-loop runtime/mvp-observe-screen.json --iterations 2 --sleep-seconds 0.2 --dump-path runtime/mvp-events.json
```

5. 检查事件文件

```bash
cat runtime/mvp-events.json
```

当前预期：

- 能完成主屏截图
- 能走通 `Vision OCR`
- 能写出 `text_change` 事件
- 能返回最近短期记忆中的问答结果

6. 测试最小条件监控

```bash
PYTHONPATH=src python3 -m ayes.cli.main check-watch runtime/mvp-triggered-screen.json --minutes 5
```

当前内置样例使用关键词 `Codex`，便于在当前开发环境下更稳定命中。
