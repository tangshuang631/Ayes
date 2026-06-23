# Ayes

Ayes 是一个面向人类用户和 AI Agent 的视觉监控、时序记忆与问答工具。

当前仓库先按文档约束落地第一阶段代码骨架：

- `watch spec` 配置契约
- 统一事件模型
- 监控目标数据结构
- macOS 窗口发现最小实现

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
