# 本地采购系统真实扩展闭环验证

## 验证目标

在不修改采购业务数据的前提下，验证以下完整链路：

`真实浏览器操作 -> 扩展录制 -> 中控上传 -> 多智能体学习 -> API Skill -> 只读测试`

## 场景

1. Playwright 启动 Chromium，并加载 `browser_extension/dist/chrome-mv3`。
2. 打开本地采购业务系统 `http://127.0.0.1:8101/`。
3. 通过真实扩展运行时开始“查询采购申请”录制。
4. 切换到“申请记录”，点击“刷新申请记录”。
5. 扩展记录 UI 动作以及 `GET /api/submissions` 请求和响应。
6. 停止录制，上传脱敏证据并触发中控后台学习。
7. 中控生成无输入、只读的查询 Skill，并完成 normal、parameter_variation、idempotency
   三类验证。
8. 重载扩展弹窗，确认最终状态可以恢复。
9. 比较测试前后的 `/api/submissions` 响应，确认业务数据未变化。

## 运行方法

```powershell
cd D:\python\CommandCenter\browser_extension
pnpm install --frozen-lockfile
pnpm run build
pnpm run test:e2e:local
```

首次运行如缺少测试浏览器：

```powershell
pnpm exec playwright install chromium
```

## 2026-08-07 结果

真实扩展端到端测试 `1 passed`。最终生成的 API Skill 使用
`connected_system:list_submissions_api_submissions_get`，业务数据前后保持一致。

测试过程中发现并修复了三类通用问题：相对网络 URL 未标准化、多系统录制未显式传递
Profile、无认证系统被错误要求提供凭据。另增加 API 学习失败原因保留，便于区分智能体
判断、测试执行与浏览器候选回退。
