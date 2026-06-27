# Windows 卸载

停止服务和托盘后删除安装目录：

```powershell
Stop-Process -Name python -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:USERPROFILE\.codex\skills\ayes-local"
```

如果要保留历史任务数据，先备份：

```powershell
Copy-Item -Recurse "$env:USERPROFILE\.codex\skills\ayes-local\runtime" "$env:USERPROFILE\Desktop\ayes-runtime-backup"
```
