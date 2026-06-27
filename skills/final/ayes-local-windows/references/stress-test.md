# Windows 长跑压测建议

建议在 Windows 真机执行 2-8 小时：

- 默认 6 秒采样。
- `save_ocr_screenshots=false`。
- 观察 `runtime\` 增长。
- 检查 `query` 是否能在不读日志的情况下回答最近活动。
- 检查托盘设置、暂停、继续是否稳定。
