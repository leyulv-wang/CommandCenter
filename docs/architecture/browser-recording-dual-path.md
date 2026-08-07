# 浏览器录制双通道架构

## 决策

浏览器演示的成功不再依赖于一次请求内完成 API 归因和验证。

1. 扩展默认使用页面语义录制，只采集脱敏后的点击、输入、选择、提交和页面上下文。
2. 停止录制时先持久化证据并返回 `202 Accepted`，模型分析在后台继续。
3. 有可靠网络证据时优先生成并验证 API Skill。
4. 没有网络证据或 API 归因失败时生成 `browser_candidate`。
5. `browser_candidate` 只能在隔离浏览器上下文中验证；不得自动回放用户当前登录的标签页。
6. API 观察需要用户在扩展中明确勾选并授予可选的 `debugger` 权限。

## 状态

录制处理状态通过录制记录持久化：

`recorded -> queued -> learning -> completed`

浏览器候选使用：

`recorded -> queued -> learning -> awaiting_browser_verification`

后台失败使用 `failed`，同时保留已经落盘的录制证据，允许后续重新分析。

## Browser-BC 参考边界

本地参考克隆位于 `.tmp/browser-bc-reference`。本项目借鉴其录制、存储、上传和提炼相互解耦的模块边界，以及 finalize 后异步处理的设计。

未将参考仓库源码复制进 CommandCenter。审阅时未发现明确的许可证文件，在许可证确认之前只能借鉴思路和接口边界。

## 尚未完成

下一阶段需要实现隔离的 Playwright Browser Operator、浏览器候选验证报告和人工批准入口。任何写操作仍必须经过权限、幂等和副作用边界检查。
