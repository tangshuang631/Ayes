# Windows 托盘手测清单

1. 运行：

```powershell
& "$env:USERPROFILE\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1"
```

2. 系统托盘应出现 Ayes 图标。

3. 菜单应包含：状态、确保服务启动、开始/继续、暂停、继续上次、设置、打开数据目录、退出。

4. 打开设置，修改采样间隔和提问快捷键，保存后应写入 `/api/control/settings`。

5. 打开数据目录应进入安装目录下的 `runtime\`。
