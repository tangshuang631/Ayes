# Ayes Local Windows 命令清单

默认使用安装后的 PowerShell 包装：

```powershell
%USERPROFILE%\.codex\skills\ayes-local\scripts\ayes-agent-local.ps1
```

为简洁，下文用 `ayes-agent-local` 代指该脚本。

## 服务与托盘

```powershell
ayes-agent-local ensure-service
ayes-agent-local contracts
ayes-agent-local status
%USERPROFILE%\.codex\skills\ayes-local\scripts\ayes-tray-local.ps1
```

- `ensure-service`：确保本地服务可达，默认 `http://127.0.0.1:8770`。
- `contracts`：查看 HTTP 接口契约。
- `status`：查看当前任务、运行状态和健康摘要。
- `ayes-tray-local.ps1`：启动 Windows 托盘控制面，可开始、暂停、继续、打开设置、打开数据目录。

## 默认查询策略

普通回忆问题默认只用：

```powershell
ayes-agent-local query --minutes 240 --question "刚才发生了什么"
```

需要细节时再用：

```powershell
ayes-agent-local memory-items --task-id <task_id> --minutes 5 --limit 5
```

需要截图证据时用：

```powershell
ayes-agent-local screenshot --task-id <task_id>
ayes-agent-local screenshot --task-id <task_id> --fresh
```

排障或用户明确要求日志时才用：

```powershell
ayes-agent-local logs --task-id <task_id> --minutes 15
```

不要为普通回忆默认读取 raw JSONL、OCR blocks、bbox、截图列表、完整配置或日志。

## 任务控制

```powershell
ayes-agent-local targets
ayes-agent-local tasks
ayes-agent-local switch-task --task-id <task_id>
ayes-agent-local start
ayes-agent-local stop
ayes-agent-local control status
ayes-agent-local control pause-all
ayes-agent-local control resume-all
```

创建任务：

```powershell
ayes-agent-local plan-spec --task-id task_chrome --prompt "帮我监控 Chrome" --target-type process --process-name chrome.exe
ayes-agent-local confirm-plan --plan-file C:\Temp\task_chrome.plan.json
ayes-agent-local start
```

## 采样、存储、ROI

```powershell
ayes-agent-local sampling
ayes-agent-local sampling --interval-sec 6 --quality standard --save-ocr-screenshots false
ayes-agent-local storage status
ayes-agent-local storage cleanup --legacy --vacuum
ayes-agent-local roi list --task-id <task_id>
ayes-agent-local roi create --task-id <task_id> --roi-name 价格监控 --region "roi_price|价格监控|120|240|360|160|target"
ayes-agent-local roi update --task-id <task_id> --roi-task-id <roi_task_id> --enabled false
ayes-agent-local roi delete --task-id <task_id> --roi-task-id <roi_task_id>
```

Windows 第一版窗口/进程监控使用窗口矩形裁剪；如果窗口被遮挡或最小化，结果可能不可观测或包含遮挡内容。

## 视觉增强和提醒

本地视觉增强是可选功能。没有 Ollama 或视觉模型时，Ayes 仍使用 OCR 和记忆索引；需要启用时先从 https://ollama.com 安装并启动 Ollama，再拉取默认视觉模型，或直接对 agent 说“启用 Ayes 本地模型增强”。

```powershell
ayes-agent-local vision models
ollama pull qwen2.5vl:7b
ayes-agent-local vision enable --provider ollama --model qwen2.5vl:7b --auto-use-when-available true
ayes-agent-local task-alert --task-id <task_id> --enabled true --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
```
