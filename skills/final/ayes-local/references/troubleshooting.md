# Ayes Local 排障说明

## 1. `ensure-service` 失败

先执行：

```bash
ayes-agent-local ensure-service
```

如果失败，优先检查：

1. 本地端口 `127.0.0.1:8770` 是否可监听
2. `runtime/ayes-server.log` 是否有最近报错
3. 当前机器是否允许本地服务正常绑定监听端口

如果命令返回里带了“最近日志”，先以该日志为第一诊断线索。

## 2. 有服务但没有任务

典型表现：

- `status` 返回无当前任务
- `start` 报“当前没有已装载监控任务”

这在最终无状态 skill 刚安装完时是正常现象，不代表安装失败。

处理方式：

1. 优先通过 agent 对话创建任务，并让 agent 先跑 `plan-spec`
2. 根据 `questions[] / setup_guidance[]` 补齐目标、webhook、ROI、刷新点击或视觉增强
3. 再由 agent 执行 `confirm-plan`
4. 最后执行 `start`

## 3. 有任务但截图为空

优先检查：

- 目标是不是选错了
- 当前目标是否真有画面
- ROI 是否框偏了
- 进程窗口是否可被当前采集方式观测

这类问题不要硬靠问答补救，应先回工作台核验预览图。

## 4. OCR 信息太稀疏

优先处理顺序：

1. 缩小 ROI
2. 提高截图 / OCR 频率
3. 检查画面分辨率与文字大小
4. 必要时打开本地视觉模型辅助

如果是图表、图片化 UI、复杂图像语义，可在 watch spec 中启用本地视觉辅助，但主链路仍以 OCR 为主。

只有当用户明确要求开启本地 Ollama 视觉增强时，才应执行：

```bash
ayes-agent-local vision prepare --requested-by agent_enable_local_vision
```

如果 `vision prepare` 返回缺 Ollama、缺服务或缺默认模型，再按提示执行安装、启动或拉取。

默认模型应使用：

```bash
ollama pull qwen2.5vl:7b
```

如果想先验证 webhook 发送链路本身，而不直接依赖真实企业微信网络，可在用户本机执行：

```bash
cd <ayes-local-repo>
python3 scripts/smoke_webhook_flow.py
```

它用于验证本地 round-trip 是否成立。若当前环境不允许监听本地端口，这一步应回到用户自己的机器执行。

如果用户已经明确授权真实企业微信 webhook，并想验证真实外发链路，则改用：

```bash
cd <ayes-local-repo>
python3 scripts/smoke_ayes_local_skill.py \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
```

如果还要验证自定义消息标题和正文模板，可继续追加：

```bash
python3 scripts/smoke_ayes_local_skill.py \
  --webhook-url "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx" \
  --alert-message-title "库存提醒" \
  --alert-message-template "任务 {task_id} 命中：{summary}"
```

这类真实 webhook 只应用于用户本机测试与实际使用，不应回写进正式发布的 skill 模板。

如果 region bind 阶段报“缺少截图信息”，优先处理顺序是：

1. 先执行 `run-once` 或 `observe-live` 让当前任务生成最近截图
2. 再直接重试 `region-bind-request --plan-file ...`
3. 只有最近截图不可用时，才手工传 `--capture-id --image-path --image-width --image-height`

## 5. 智能体回答缺少时间范围

这是调用方式不规范，不是用户问题。

修正方式：

- 最近几分钟问题，优先调用 `activity`；需要细节时再调用默认紧凑输出的 `memory-items --limit 5`，不要直接读取原始 JSONL
- 最近几小时问题，优先调用 `ask --hours` 或 `long-term --hours`
- 回答中必须明确任务、时间范围、关键证据和结论

## 6. 监控命中了但 Codex 没有立刻回复

这不应影响告警是否送达。

正确预期是：

- webhook 通知由后台服务直接发送
- Codex / OpenClaw 只是后续查询和解释通道

排查顺序：

1. 先看 `alerts --minutes 15`
2. 再看 `logs --minutes 15`
3. 再问 `ask --minutes 5` 或 `ask --hours 24`

如果 `alerts` 里已有 `alert_sent`，说明工具已经通知成功，只是智能体当时没有在线回复。

如果安装后 smoke 偶发卡在 `ensure-service`，优先判断是不是刚回收完旧本地服务、而旧 PID 尚未完全退出。当前 smoke 已内建“等待旧 PID 退出后再重启”的处理；若仍失败，优先检查：

1. `runtime/ayes-server.log` 最后几十行是否停在 `Shutting down`
2. `runtime/ayes-server.pid` 指向的进程是否仍存活
3. `127.0.0.1:8770` 是否被其他非 Ayes 进程占用

如果用户要求企业微信发送自定义消息内容，而不是默认摘要，应先检查任务配置里是否已写入自定义标题或模板；若没有，应重新走一次 `confirm-plan` 并补上：

- `--alert-message-title`
- `--alert-message-template`

## 7. 重启后长期记忆看不到

先确认：

- 问题是否指定了更短时间窗口
- 当前读取的是不是同一个 `task_id`
- 长期摘要保留时长是否覆盖当前问题时间范围

如果只是服务重启，但持久化文件仍在，长期摘要不应默认清零。

## 8. 截图快捷键没有反应

先确认菜单栏控制面正在运行，并检查：

```bash
tail -n 80 ~/.codex/skills/ayes-local/runtime/ayes-menubar.log
```

判断方式：

- 看到 `hotkey_registered`：说明快捷键配置已被菜单栏进程读取
- 按下快捷键后没有 `hotkey_matched`：通常是 macOS 没把全局键盘事件交给菜单栏进程；优先在“系统设置 -> 隐私与安全性 -> 辅助功能”里允许当前 Python / Ayes 菜单栏进程
- 看到 `hotkey_matched` 但随后 `paste_latest_failed`：说明快捷键进入了 Ayes，但复制或模拟粘贴失败；优先看同一行的 `result` 和 `error`
- 看到 `paste_latest_completed` 但对话框没有图片：说明图片已进剪贴板并发出了 Cmd+V，焦点可能不在当前对话输入框，或目标应用不接受图片粘贴

菜单栏里“复制并粘贴最新采样图”使用同一条动作链路，适合用来区分快捷键监听失败和复制/粘贴动作失败。

## 9. 长时间监控占用空间或担心 SSD 写入

先查看当前采样策略：

```bash
ayes-agent-local sampling
```

长期监控建议：

- 默认采样间隔是 6 秒，已经比高频监控更保守
- 默认不保存逐事件证据截图；如果之前开启过并且磁盘增长过快，执行 `ayes-agent-local sampling --save-ocr-screenshots false`
- 关闭后仍会保留少量 `screenshots/latest/` 临时最新帧，截图快捷键和 `/api/screenshot` 不受影响
- 如果只需要主要语义，执行 `ayes-agent-local sampling --quality space_saver`
- 如果仍需要逐事件原图证据，才开启 `save_ocr_screenshots=true`，并确认磁盘占用和清理策略可接受

持续写入 PNG 会增加 SSD 写入量。现代 SSD 通常可以承受普通日常写入，但 24 小时高分辨率、高频、多 ROI 监控会明显增加 TBW 消耗和磁盘占用。产品默认应优先使用 `standard` 质量和 6 秒间隔；用户确认需要高精度证据时再使用 `original` 或更短间隔。
