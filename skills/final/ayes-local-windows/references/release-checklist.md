# Windows 发行检查

- Windows 包目录为 `skills/final/ayes-local-windows/`。
- 包内不包含 `runtime/`、数据库、历史截图、日志、真实 webhook。
- `requirements.txt` 不包含 pyobjc。
- `scripts/ayes-agent-local.ps1` 指向安装后的 `src` 和 `runtime`。
- `scripts/ayes-tray-local.ps1` 能打开托盘。
- `query` 是普通回忆默认入口。
- 已说明窗口/进程捕获使用 best-effort 矩形裁剪。
