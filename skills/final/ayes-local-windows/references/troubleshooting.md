# Windows 排障

## 服务无法启动

先运行：

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1" ensure-service
```

如果失败，检查：

- Python 是否来自安装时的 venv。
- 是否已安装 `requirements.txt`。
- 端口 `127.0.0.1:8770` 是否被占用。
- `runtime\ayes-server.log` 中的错误。

## 托盘无法打开

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1"
```

如果提示缺依赖，重新执行：

```powershell
pip install -r requirements.txt
```

`pystray` 负责系统托盘，`tkinter` 负责设置弹窗。

## 截图为空或窗口不对

Windows 第一版窗口/进程监控是窗口矩形裁剪。窗口被遮挡、最小化、移动到虚拟桌面外时，可能无法得到真实窗口画面。优先切换到全屏监控或让目标窗口保持可见。

## 普通提问 token 太大

普通回忆只用：

```powershell
ayes-agent-local query --minutes 240 --question "..."
```

不要默认查 `logs`、raw memory、OCR blocks、bbox 或完整截图列表。
