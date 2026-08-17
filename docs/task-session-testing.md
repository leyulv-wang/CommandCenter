# TaskSession 通用任务运行时验证指南

本指南用于验证“自然语言任务 → Skill 选择 → 参数补充 → 写操作确认 → 可恢复执行”的通用闭环。所有示例均使用本地测试 Skill 和模拟系统，不使用生产账号、Cookie、Token 或真实业务数据。

## 1. 启动项目

在项目根目录启动后端：

```powershell
conda run -n langgraph uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```powershell
Set-Location frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

打开 <http://127.0.0.1:5174>。本指南中的 HR、财务 fixture Skill 仅供自动化和本地验证，不应发布到生产目录。

## 2. 页面验收流程

1. 加载或发布 HR 只读 fixture Skill。
2. 输入“查看员工 E-9 的剩余年假”。
3. 确认系统直接返回“员工 E-9 剩余年假 5 天”，过程中不出现写操作确认。
4. 加载或发布财务 fixture Skill。
5. 输入“提交一张包含两条费用的报销单”。
6. 确认页面显示动态数组表单，填写“差旅 / 88”和“餐费 / 32”两行。
7. 提交表单，确认页必须列出准确的目标对象、业务系统、写步骤和参数。
8. 确认一次，记录返回的外部记录 ID。
9. 重复提交同一确认或请求，确认没有产生第二条目标记录；受幂等保护的重试应对应同一个外部 ID。
10. 在已展示计划后修改金额，确认旧的 `plan_revision`、`plan_hash` 和确认令牌被拒绝。
11. 执行现有采购列表查询，再测试“查看详情”和“追踪采购进度”，确认旧查询能力仍可兼容使用。

## 3. API 验证

以下命令逐步保存服务返回的最新 `version`，不要复用旧版本号。

### 创建会话

```powershell
$base = 'http://127.0.0.1:8000'
$session = Invoke-RestMethod -Method Post -Uri "$base/task-sessions" `
  -ContentType 'application/json' `
  -Body (@{ goal = '提交一张包含两条费用的报销单' } | ConvertTo-Json)
$session | ConvertTo-Json -Depth 20
```

若缺少复杂参数，`next_interaction.type` 应为 `form`。

### 提交动态表单

```powershell
$body = @{
  version = $session.version
  values = @{
    items = @(
      @{ category = '差旅'; amount = 88 }
      @{ category = '餐费'; amount = 32 }
    )
  }
} | ConvertTo-Json -Depth 10

$pending = Invoke-RestMethod -Method Post `
  -Uri "$base/task-sessions/$($session.session_id)/inputs" `
  -ContentType 'application/json' -Body $body
$pending | ConvertTo-Json -Depth 20
```

响应应处于 `awaiting_confirmation`，并包含本次计划绑定的 `plan_revision`、`plan_hash` 和 `next_interaction.confirmation_token`。

### 确认写操作

```powershell
$confirmation = @{
  version = $pending.version
  plan_revision = $pending.plan_revision
  plan_hash = $pending.plan_hash
  confirmation_token = $pending.next_interaction.confirmation_token
  approved = $true
} | ConvertTo-Json

$completed = Invoke-RestMethod -Method Post `
  -Uri "$base/task-sessions/$($pending.session_id)/confirmations" `
  -ContentType 'application/json' -Body $confirmation
$completed | ConvertTo-Json -Depth 20
```

写操作只允许在确认信息与当前计划完全一致时执行。旧版本、旧计划哈希、已消费令牌或被修改的目标都应被拒绝。

### 刷新会话

```powershell
Invoke-RestMethod -Method Get -Uri "$base/task-sessions/$($pending.session_id)" |
  ConvertTo-Json -Depth 20
```

## 4. 自动化回归

```powershell
conda run -n langgraph python -m pytest tests/test_task_session_contracts.py -q
conda run -n langgraph python -m pytest -q
Set-Location frontend
npm test -- --run
npm run build
```

契约测试覆盖 HR 只读直达、财务结构化表单、计划绑定确认、重复确认、幂等超时重试、业务失败、部分失败、重启续跑和无幂等保护时的未知结果。

## 5. 结果判断

- 只读任务不要求确认，但仍受 Tool 白名单和权限约束。
- 写任务必须在完整计划展示后确认，确认只对当前版本和计划有效。
- 网络超时仅在 Tool 明确声明幂等保障时自动重试。
- 已成功持久化的步骤在服务恢复时不会重复执行。
- 没有匹配到已发布 Skill 时，前端才显示旧查询兼容入口。
- 日志和会话快照不得保存 Cookie、Authorization、密码或 API Key 明文。
