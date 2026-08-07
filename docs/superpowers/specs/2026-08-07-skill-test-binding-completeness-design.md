# Skill 自动测试绑定完整性设计

## 背景

真实 MES 录制已完成网络观察、Tool 匹配、字段映射和 Skill 编译。候选 Skill 将
`query.applyBy` 绑定到 `task.content.purchaseDepartment`，但测试设计智能体生成的测试任务
没有该字段。`ReadOnlySkillTestService` 未隔离绑定解析异常，导致整个 LangGraph 分析任务以
系统错误结束。

## 决策

1. 测试设计智能体必须逐个检查候选 Skill 的输入绑定。
2. `task.*` 绑定所需值放入测试用例 `fixture.source_task`；`literal.*` 所需值放入
   `invocation`；`steps.*` 必须能由候选 Skill 的前序步骤输出提供。
3. 测试值由智能体依据 Skill 输入定义和测试类别生成，不通过字段关键词或 MES 特例填充。
4. 测试器把无法解析绑定归类为“测试数据不完整”，返回结构化失败结果，不得让后台分析线程
   崩溃。
5. 代码只负责检查绑定是否可解析、限制异常外泄和维持测试生命周期；不替代智能体决定测试值
   或字段业务含义。

## 数据流

测试设计智能体接收完整 `SkillDefinition`，生成 normal、parameter_variation、idempotency
三类测试。每个用例进入测试器后，先使用相同的 `BindingResolver` 对全部步骤绑定进行解析；
解析成功才执行只读 Tool。解析失败则返回 `status=failed`、安全摘要和空副作用，不发送 API。

## 错误边界

- `KeyError`、绑定路径格式错误和测试 fixture 缺失属于测试设计失败。
- Tool 网络错误仍属于查询执行失败。
- 写 Tool 或未知副作用继续被只读测试边界拒绝。
- 返回结果不得包含异常中的业务值、凭证或模型原始响应。

## 验收

1. 提示测试证明测试设计智能体同时覆盖 `task.*`、`literal.*` 和 `steps.*`。
2. 缺少 `task.content.department` 的用例返回结构化失败，不抛出异常，也不调用 Tool。
3. fixture 提供所需字段时，SkillRunner 能完成只读调用。
4. 现有扩展、后端、前端与本地端到端测试全部通过。
5. 对已保存的真实 MES 录制重新分析，不要求员工再次录制；最终至少得到明确测试结果，不再是
   `failure_stage=system`。

## 非目标

- 不为 `purchaseDepartment`、`applyBy` 或 MES 增加硬编码规则。
- 不把所有 `task.*` 绑定强制改写成 `literal.*`。
- 不自动把 invocation 内容复制到 task content。
