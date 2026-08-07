# 浏览器录制双通道架构

## 决策

浏览器演示的成功不再依赖于一次请求内完成 API 归因和验证。

1. 扩展默认使用页面语义录制，只采集脱敏后的点击、输入、选择、提交和页面上下文。
2. 停止录制时先持久化证据并返回 `202 Accepted`，模型分析在后台继续。
3. 有可靠网络证据时优先生成并验证 API Skill。
4. 没有网络证据或 API 归因失败时生成 `browser_candidate`。
5. `browser_candidate` 只能在隔离浏览器上下文中验证；不得自动回放用户当前登录的标签页。
6. API 观察采用 Browser-BC 的页面上下文网络钩子，记录 `fetch`、XHR、Beacon、
   WebSocket 和 EventSource 证据；不依赖 `chrome.debugger` 权限。

## 状态

录制处理状态通过录制记录持久化：

`recorded -> queued -> learning -> completed`

浏览器候选使用：

`recorded -> queued -> learning -> awaiting_browser_verification`

后台失败使用 `failed`，同时保留已经落盘的录制证据，允许后续重新分析。

## Browser-BC 采用边界

当前研究原型决定采用 Browser-BC 提交 `5afc6d4` 的 `extension/` 作为浏览器录制器
技术底座，完整替换原有轻量扩展。保留其录制、脱敏、IndexedDB 存储和可靠上传模块，
通过独立适配层连接 CommandCenter 现有录制 API。

不引入 Browser-BC 的本地 Python 服务、Claude Skill 安装器和控制面板。API 归因、Skill
生成、测试和发布仍由 CommandCenter 多智能体闭环负责。当前仓库未发现明确许可证，原型
阶段保留上游来源和提交号；正式产品化前重新评估许可证和商业使用边界。

## 尚未完成

下一阶段需要实现隔离的 Playwright Browser Operator、浏览器候选验证报告和人工批准入口。任何写操作仍必须经过权限、幂等和副作用边界检查。
