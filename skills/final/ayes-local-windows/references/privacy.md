# Windows 隐私说明

Ayes Windows 版在本机运行。默认数据目录：

```text
%USERPROFILE%\.codex\skills\ayes-local\runtime\
```

默认不上云，默认不保存逐事件 evidence 原图。`screenshots\latest\` 只保留少量最新帧，用于截图接口和快捷粘贴。

只有在用户明确配置企业微信 webhook 时，Ayes 才会向该 webhook 发送提醒。只有在用户启用 Ollama 本地视觉增强时，Ayes 才会把截图发给本机 Ollama 服务。

Windows 捕获能力：

- 全屏采样使用 `mss`。
- 窗口/进程采样使用窗口边界裁剪。
- 被遮挡、最小化或跨虚拟桌面的窗口可能无法可靠采集。
