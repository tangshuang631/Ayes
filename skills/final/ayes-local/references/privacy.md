# Ayes Local 隐私与数据说明

## 适用范围

当前这个发行目录只支持 macOS 本地使用。`ayes-local` 会让本地 Ayes 服务读取屏幕、窗口或进程画面，并把 OCR、事件、记忆和少量最新截图写入本机安装目录。

## 默认数据流

默认情况下，Ayes 数据只写入本机：

```text
$HOME/.codex/skills/ayes-local/runtime/
```

主要目录：

- `tasks/<date>/<task_id>/screenshots/latest/`：少量最新帧缓存，默认最多保留少量文件，用于截图证据、ROI 框选和快捷键粘贴。
- `tasks/<date>/<task_id>/screenshots/evidence/`：逐事件证据图，默认关闭，只有 `save_ocr_screenshots=true` 时写入。
- `tasks/<date>/<task_id>/memory/short/`：短期紧凑明细，默认 7 天，最高 14 天。
- `tasks/<date>/<task_id>/memory/long/`：长期简略摘要，默认 14 天，最高 30 天。
- `tasks/<date>/<task_id>/logs/`：任务相关日志。
- `data/`：SQLite 数据库和服务状态。

## 默认不上云

Ayes 默认不会把截图、OCR 文本、记忆或日志上传到远端服务。

例外情况：

- 用户启用企业微信 webhook 时，命中的告警摘要会发送到用户提供的 webhook。
- 用户启用本地 Ollama 视觉增强时，截图会发送给本机 Ollama 服务；如果 Ollama 被用户配置成远端服务，则数据流取决于用户自己的 Ollama 配置。
- 用户把截图复制到剪贴板或粘贴到其他应用后，后续数据处理由目标应用决定。

## 权限

macOS 可能要求以下权限：

- 屏幕录制：用于采集屏幕、窗口或进程画面。
- 辅助功能：用于菜单栏快捷键模拟粘贴最新截图。
- 本地网络：用于访问 `127.0.0.1:8770` 的本地 Ayes 服务。

如果截图为空、快捷键无反应或无法粘贴，应优先检查系统设置里的权限。

## 硬盘写入

默认策略已经按低写入设计：

- 默认采样间隔 6 秒。
- 默认采样质量 `standard`。
- 默认 `save_ocr_screenshots=false`，不保存逐事件证据截图。
- `screenshots/latest/` 只保留少量最新帧。

高写入模式包括：

- `sampling --interval-sec 0.5`
- `sampling --quality original`
- `sampling --save-ocr-screenshots true`
- 多任务或多 ROI 长时间并行运行

开启这些模式前，应告知用户会增加磁盘占用和 SSD 写入量。

## 删除数据

删除单个任务：

```bash
ayes-agent-local delete-task --task-id <task_id>
```

执行记忆清理：

```bash
ayes-agent-local memory-cleanup --task-id <task_id>
```

完整卸载和数据删除见 `references/uninstall.md`。
