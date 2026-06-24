# Ayes Local 命令清单

以下命令默认使用安装后的本地包装：

```bash
$HOME/.codex/skills/ayes-local/scripts/ayes-agent-local
```

为简洁，下文用 `ayes-agent-local` 代指该脚本。

## 1. 服务与契约

```bash
ayes-agent-local ensure-service
ayes-agent-local contracts
ayes-agent-local status
```

用途：

- `ensure-service`：确保本地服务可达，默认地址为 `http://127.0.0.1:8770`
- `contracts`：查看当前 HTTP 接口契约
- `status`：查看当前任务、运行状态、最近健康摘要

## 2. 目标与任务

```bash
ayes-agent-local targets
ayes-agent-local task --task-id task_web
```

用途：

- `targets`：读取当前可选屏幕/进程目标摘要
- `task`：读取持久化任务配置快照

## 3. 近期证据链路

```bash
ayes-agent-local screenshot --task-id task_web
ayes-agent-local recent --task-id task_web --minutes 5 --limit 20
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local memory-items --task-id task_web --minutes 5 --limit 20
ayes-agent-local logs --task-id task_web --minutes 15
ayes-agent-local run-once
```

用途：

- `screenshot`：读取最近截图路径与 ROI 覆盖信息
- `recent`：读取最近时间线事件
- `alerts`：读取最近告警审计结果
- `memory-items`：读取短期记忆事件明细
- `logs`：读取近期日志
- `run-once`：执行一次即时采样，适合安装后 smoke 或人工核验

## 4. 提问

最近几分钟问答：

```bash
ayes-agent-local ask --task-id task_web --minutes 5 --question "最近几分钟发生了什么"
```

长期摘要问答：

```bash
ayes-agent-local ask --task-id task_web --hours 24 --question "今天这个进程最低大概是什么时候"
```

说明：

- `minutes` 主要走短期详细链路
- `hours` 主要走长期摘要链路
- 若用户问“最近 xx 小时”，应显式带 `--hours`

如果用户问“刚才有没有真的通知出去”或“为什么没通知”，优先读取：

```bash
ayes-agent-local alerts --task-id task_web --minutes 15 --limit 20
ayes-agent-local logs --task-id task_web --minutes 15
```

## 5. 启停监控

```bash
ayes-agent-local start
ayes-agent-local stop
```

注意：

- `start` 前应已有已装载任务
- `stop` 会停止当前持续监控

## 6. 装载最小 watch spec

屏幕观察任务：

```bash
ayes-agent-local load-spec \
  --task-id task_web \
  --mode observe \
  --target-type screen \
  --screen-id 1
```

按进程装载 triggered 任务：

```bash
ayes-agent-local load-spec \
  --task-id task_price \
  --mode triggered \
  --target-type process \
  --process-name "Google Chrome" \
  --query "价格低于 299" \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" \
  --screenshot-interval-ms 500 \
  --ocr-interval-ms 500 \
  --change-detection-interval-ms 500
```

启用本地视觉辅助：

```bash
ayes-agent-local load-spec \
  --task-id task_chart \
  --mode observe \
  --target-type process \
  --process-name "Google Chrome" \
  --enable-vision \
  --vision-provider ollama \
  --vision-model molmo
```
