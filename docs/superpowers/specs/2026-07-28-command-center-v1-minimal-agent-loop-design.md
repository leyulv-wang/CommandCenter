# CommandCenter V1 最小智能体闭环设计

状态：已被单系统 V1 规格取代

> 本文保留为设计演进记录，不再作为 V1 实施依据。当前规格见
> `2026-07-28-command-center-v1-single-system-skill-design.md`：只使用采购业务系统和中控系统，学习“创建采购申请”单步骤 Skill。

日期：2026-07-28

适用范围：`D:\python\CommandCenter`

上位设计：`2026-07-23-command-center-platform-skeleton-design.md`

## 1. 文档目的

本文是 CommandCenter V1 的具体实现事实来源。

V1 不建设完整企业指挥中心，只在当前两个测试 Web 业务系统和中控系统中完成一条最小纵向闭环：

```text
员工演示一次跨系统操作
→ 中控观察页面操作和真实 API 请求
→ 多个智能体生成 API Skill
→ 智能体自动进行无害测试
→ 测试通过后自动发布
→ 员工通过自然语言调用 Skill
→ LangGraph 指挥智能体执行 API Tool
→ 智能体验证最终业务结果
```

本文同时定义智能体之间交换的数据 Schema。用户不需要编辑或理解这些 Schema，但实现必须遵守它们，以保证模型输出可校验、可追踪和可测试。

## 2. V1 目标

第一版只证明五件事：

1. 中控能从员工在两个测试系统中的真实页面操作中识别业务 API 调用。
2. 中控能把一次演示抽象为参数化、可再次执行的 API Skill。
3. 智能体能在隔离测试数据上自动验证候选 Skill。
4. 通过测试的 Skill 能自动发布。
5. 员工能通过自然语言调用 Skill，完成新的跨系统业务任务。

## 3. 样板业务流程

固定样板流程：

```text
办公用品系统出现库存不足任务
→ 员工查看任务内容
→ 在采购系统创建采购申请
→ 取得采购单号
→ 将采购单号回写办公用品系统
→ 将办公用品任务更新为“采购中”
```

核心业务数据：

- 来源任务 ID；
- 申请人；
- 物品名称；
- 采购数量；
- 采购原因；
- 采购单号；
- 办公用品任务状态。

## 4. V1 非目标

以下内容不进入 V1：

- 无 API 系统的浏览器自动化执行；
- Windows 桌面软件；
- UFO、UI-TARS 等桌面或纯视觉 Operator；
- 浏览器扩展；
- 后台持续观察员工；
- Process Discovery；
- 多次演示比较和分支学习；
- 自动修复已发布 Skill；
- 管理员观察台；
- 人工 Skill 编辑器；
- 账号、权限、租户和部门系统；
- 通用流程设计器；
- 通用多智能体平台；
- 生产级任务队列和分布式部署。

V1 可以保存未来扩展所需的数据，但不实现上述产品能力。

## 5. 用户角色与界面

### 5.1 员工

员工承担两件事：

1. 在演示工作台完成一次真实演示。
2. 在普通任务中心用自然语言发起任务。

### 5.2 管理员

V1 不建设管理员工作流。

现有 AI 配置和外部系统页面可以保留，但不新增 Skill 审核、测试或观察页面。开发阶段通过日志、数据库和 API 检查内部状态。

### 5.3 页面

V1 只新增或重点改造两个页面：

#### 演示工作台

员工能够：

- 选择一条库存不足任务；
- 填写本次演示目标；
- 点击“开始演示”；
- 在受控浏览器中完成操作；
- 点击“结束演示”；
- 查看“分析中、自动测试中、已发布、需要重新演示”等状态。

#### 普通任务中心

员工能够：

- 输入自然语言任务；
- 在多个候选业务对象中选择一个；
- 查看当前执行步骤；
- 查看最终采购单号和任务状态；
- 查看失败发生在哪一步以及是否产生业务写入。

## 6. 核心设计原则

### 6.1 智能体优先

业务判断尽量由智能体完成：

- 理解演示目标；
- 区分业务操作和无关页面操作；
- 关联页面动作与 API 请求；
- 识别 Skill 参数；
- 建立跨步骤字段映射；
- 生成测试用例；
- 理解员工自然语言；
- 匹配 Skill；
- 解释失败；
- 验证业务结果。

禁止为样板流程编写大量专用 `if/else` 规则。

### 6.2 代码只守硬边界

以下内容必须由确定性代码保证：

- 只允许调用 API 目录中的 Tool；
- Tool 参数通过 Pydantic 校验；
- 测试环境和正式演示数据隔离；
- 写操作带幂等键；
- 已发布版本不可在运行时修改；
- 多个业务对象匹配时由员工选择；
- 每一步输入、输出、错误和证据留痕；
- 自动测试失败的 Skill 不发布。

### 6.3 API 目录不等于操作映射

两个测试系统继续提供 API，但不能直接告诉中控：

> 这次按钮点击对应某个指定 Tool。

中控只能得到：

- 浏览器中实际发生的 UI 操作；
- 浏览器中实际发出的 HTTP 请求；
- 管理员允许使用的 API 目录。

中控自己完成关联和 Skill 抽象。

### 6.4 演示使用页面，执行使用 API

员工按自然工作方式操作页面。

发布后的 V1 Skill 不回放页面操作，而是直接调用在演示中识别出的 API Tool。

## 7. 技术方案

### 7.1 保留的现有技术

- 后端：FastAPI；
- Schema：Pydantic；
- 智能体编排：LangGraph；
- 模型调用：现有 LangChain OpenAI 兼容配置；
- API 调用：httpx；
- 前端：Vue 3、TypeScript、Vite、Element Plus；
- 数据库：SQLite；
- 测试：pytest。

### 7.2 新增技术

- Playwright Python：受控浏览器、页面事件注入、网络请求观察和 Trace；
- JSON Schema / Pydantic structured output：约束每个智能体的输出。

### 7.3 不直接依赖 Playwright 内部 Codegen API

Playwright Codegen 的内部 Recorder 主要位于 Node/TypeScript 实现，Python 公共 API不直接暴露完整 Recorder。

V1 不引入 Node Recorder Sidecar，而是在 Python Playwright 上实现最小录制适配器：

1. 使用 `browser_context.add_init_script()` 注入轻量页面观察脚本；
2. 记录可信点击、输入、选择、页面切换和表单提交事件；
3. 为目标保存 role、accessible name、label、test id、URL 和 frame 等语义信息；
4. 使用 Playwright request / response 事件记录允许域名中的 API 流量；
5. 使用 Playwright Trace 保存调试证据。

V1 发布后只执行 API，因此不需要生成可长期重放的 Web Locator 脚本。这显著降低录制器复杂度。

## 8. API Tool 目录

### 8.1 来源

每个测试业务系统的 FastAPI `/openapi.json` 是接口结构来源。

CommandCenter 维护一份明确允许的 `operationId` 清单。只有清单内的接口可以成为 Tool。

### 8.2 Tool 定义

每个 Tool 至少包含：

```yaml
tool_id: purchase.create_request
system_code: connected_system
operation_id: create_purchase_request
method: POST
path: /api/workflows/start
input_schema: {}
output_schema: {}
side_effect: write
idempotency_supported: true
```

### 8.3 请求匹配

录制期间的真实 HTTP 请求先由确定性代码按以下条件匹配：

- 目标系统；
- HTTP method；
- 标准化 path；
- OpenAPI operation；
- 允许清单。

确定性匹配成功后，智能体再判断它在业务演示中的含义。

未匹配请求可以保存为证据，但不能进入可执行 Skill。

## 9. 智能体角色

V1 使用五个逻辑智能体角色。

它们可以共享同一个模型和模型配置，但在 LangGraph 中使用不同系统提示、输入 Schema 和输出 Schema。

### 9.1 演示理解智能体

输入：

- 员工目标；
- 来源任务；
- 页面操作摘要；
- 已匹配 API 请求；
- 请求响应摘要；
- 截图和证据引用。

输出：

- 有序业务动作；
- 无关动作；
- 每个业务动作对应的 Tool；
- 输入值来源；
- 输出值去向；
- 不确定项。

### 9.2 Skill 编译智能体

输入：

- 演示理解结果；
- API Tool Schema；
- 原始演示值；
- 来源业务对象。

输出：

- Skill 名称和说明；
- 输入参数；
- 输出参数；
- 有序 Tool 步骤；
- 跨步骤数据映射；
- 成功条件；
- 幂等业务键；
- 可测试性结论。

### 9.3 测试智能体

输入：

- 候选 Skill；
- 测试系统可创建的数据范围；
- 来源任务模板；
- Tool Schema。

输出：

- 正常测试；
- 参数变化测试；
- 幂等测试；
- 每个测试的预期业务结果。

### 9.4 任务执行智能体

输入：

- 员工自然语言；
- 可用 Skill；
- Tool 目录；
- 当前任务执行状态。

职责：

- 查询并定位业务对象；
- 匹配 Skill；
- 绑定参数；
- 按 Skill 骨架生成当前 Tool 命令；
- 调用 Tool；
- 保存输出；
- 决定继续、请求员工选择或停止。

执行智能体不能增加、删除或改变已发布 Skill 的关键写步骤。

### 9.5 验证智能体

输入：

- Skill 成功条件；
- 全部步骤结果；
- 两个系统的最终读取结果；
- API 响应和证据。

输出：

- `passed`、`failed` 或 `inconclusive`；
- 每条成功条件的判断；
- 业务副作用；
- 失败原因；
- 面向员工的结果摘要。

## 10. 智能体交互公共信封

所有智能体输出都包装在统一信封中：

```yaml
schema_version: "1.0"
run_id: uuid
correlation_id: uuid
agent_role: demonstration_analyst
stage: analyze_demonstration
status: succeeded
payload: {}
evidence_refs: []
warnings: []
```

字段要求：

- `schema_version`：支持未来升级；
- `run_id`：本次学习、测试或执行实例；
- `correlation_id`：关联演示、Skill 和测试；
- `agent_role`：产生结果的逻辑智能体；
- `stage`：LangGraph 当前阶段；
- `status`：`succeeded | failed | needs_input`；
- `payload`：角色专用结构化输出；
- `evidence_refs`：只传证据引用，不在智能体间复制大文件；
- `warnings`：不阻断但需要保留的信息。

模型输出必须通过 Pydantic 校验。校验失败时允许重新提示模型一次；第二次仍失败则终止本次流程。

## 11. 录制轨迹 Schema

### 11.1 OperationTrace

```yaml
trace_id: uuid
recording_id: uuid
objective: string
source_task:
  system_code: onboarding_system
  object_type: office_supply_task
  object_id: string
  snapshot: {}
started_at: datetime
ended_at: datetime
ui_events: []
api_exchanges: []
evidence_refs: []
```

### 11.2 UIEvent

```yaml
event_id: uuid
sequence: integer
timestamp: datetime
page:
  url: string
  title: string
  frame_url: string | null
action:
  type: click | input | select | submit | navigation
  value_ref: string | null
target:
  tag: string
  role: string | null
  accessible_name: string | null
  label: string | null
  test_id: string | null
  attributes: {}
screenshot_ref: string | null
```

敏感值不写入 `value_ref` 对应的普通日志；当前测试系统不包含真实密码和敏感身份数据。

### 11.3 APIExchange

```yaml
exchange_id: uuid
sequence: integer
started_at: datetime
completed_at: datetime
system_code: string
request:
  method: string
  url: string
  path: string
  headers_summary: {}
  body: {}
response:
  status_code: integer
  body: {}
matched_tool_id: string | null
match_status: matched | not_allowed | unknown
```

## 12. 演示理解 Schema

### 12.1 DemonstrationAnalysis

```yaml
summary: string
business_actions:
  - action_id: string
    sequence: integer
    intent: string
    source_ui_event_ids: []
    source_exchange_ids: []
    tool_id: string
    input_bindings:
      - tool_field: string
        source_kind: task_field | literal | previous_output
        source_path: string
    output_observations:
      - name: string
        response_path: string
        later_used_by_action_id: string | null
ignored_ui_event_ids: []
uncertainties:
  - description: string
    blocking: boolean
compilable: boolean
```

只要存在阻断性不确定项，`compilable` 必须为 `false`，流程要求员工重新演示。

## 13. Skill Schema

### 13.1 SkillDefinition

```yaml
skill_id: uuid
version: integer
name: string
description: string
status: candidate | testing | published | rejected | runtime_failed
trigger_examples: []
source_recording_id: uuid
inputs:
  - name: string
    type: string | integer | number | boolean
    description: string
    required: boolean
    source_hint: string | null
outputs:
  - name: string
    type: string
    description: string
steps:
  - step_id: string
    name: string
    tool_id: string
    input_bindings: {}
    output_bindings: {}
    side_effect: read | write
    idempotency_key_template: string | null
success_conditions:
  - condition_id: string
    description: string
    verification_tool_id: string
    assertion: {}
created_at: datetime
published_at: datetime | null
```

### 13.2 BindingExpression

V1 只允许三类引用：

```text
task.<field>
steps.<step_id>.output.<field>
literal.<name>
```

不引入任意代码表达式。

智能体负责选择引用；执行器负责解析和类型校验。

### 13.3 Skill 不保存什么

Skill 不保存：

- Cookie；
- API Key；
- 员工密码；
- Playwright 浏览器会话；
- 原始完整 Trace；
- 模型思维过程；
- 可执行任意 Python 代码。

## 14. 测试 Schema

### 14.1 TestPlan

```yaml
skill_id: uuid
skill_version: integer
cases:
  - case_id: string
    category: normal | parameter_variation | idempotency
    description: string
    fixture:
      source_task: {}
    invocation: {}
    expected:
      assertions: []
```

V1 固定要求三个类别各至少一个测试。

测试内容由智能体生成，不在代码中硬编码物品名称和数量。

### 14.2 TestCaseResult

```yaml
case_id: string
status: passed | failed | inconclusive
execution_run_id: uuid
step_results: []
verification: {}
side_effect_summary: {}
evidence_refs: []
```

### 14.3 自动发布门槛

候选 Skill 只有同时满足以下条件才自动发布：

1. 三类测试均完成；
2. 所有测试为 `passed`；
3. 所有写步骤使用幂等键；
4. 验证智能体没有报告未知副作用；
5. 所有调用均来自允许的 API Tool 目录；
6. 没有 `inconclusive` 结果。

任何一项不满足，状态为 `rejected`，演示工作台提示重新演示。

## 15. 执行命令 Schema

### 15.1 ExecutionCommand

```yaml
run_id: uuid
skill_id: uuid
skill_version: integer
step_id: string
tool_id: string
arguments: {}
idempotency_key: string | null
reason: string
```

`reason` 是面向日志的简短解释，不保存模型隐式思维链。

### 15.2 StepResult

```yaml
run_id: uuid
step_id: string
tool_id: string
status: succeeded | failed | skipped
started_at: datetime
ended_at: datetime
request_summary: {}
response_summary: {}
normalized_output: {}
side_effect:
  occurred: boolean
  business_object_type: string | null
  business_object_id: string | null
error:
  code: string | null
  message: string | null
retry_safe: boolean
evidence_refs: []
```

## 16. 验证 Schema

### 16.1 VerificationResult

```yaml
status: passed | failed | inconclusive
conditions:
  - condition_id: string
    status: passed | failed | inconclusive
    observed: {}
    evidence_refs: []
side_effects:
  purchase_request_ids: []
  updated_task_ids: []
duplicate_detected: boolean
summary: string
```

HTTP 2xx 只能作为步骤成功证据，不能单独证明整个业务完成。

## 17. LangGraph：学习与发布图

学习图节点：

```text
finalize_recording
→ load_api_catalog
→ analyze_demonstration
→ validate_analysis
→ compile_skill
→ validate_skill
→ generate_test_plan
→ prepare_test_fixture
→ execute_test_case
→ verify_test_case
→ more_cases?
→ publish_skill / reject_skill
```

### 17.1 节点职责

- `finalize_recording`：结束 Playwright Trace 并固定 OperationTrace；
- `load_api_catalog`：读取本次使用的 Tool 版本；
- `analyze_demonstration`：调用演示理解智能体；
- `validate_analysis`：检查所有业务 API 是否允许且可编译；
- `compile_skill`：调用 Skill 编译智能体；
- `validate_skill`：Schema 和硬边界校验；
- `generate_test_plan`：调用测试智能体；
- `prepare_test_fixture`：重置并创建测试任务；
- `execute_test_case`：调用执行智能体；
- `verify_test_case`：调用验证智能体；
- `publish_skill`：写入不可变发布版本；
- `reject_skill`：保存原因并提示员工重新演示。

### 17.2 学习图状态

```yaml
recording_id:
trace_id:
api_catalog_version:
analysis:
candidate_skill:
test_plan:
current_test_index:
test_results:
final_status:
errors:
```

## 18. LangGraph：自然语言执行图

执行图节点：

```text
understand_request
→ search_business_objects
→ resolve_ambiguity
→ match_skill
→ bind_skill_inputs
→ select_next_step
→ build_execution_command
→ execute_tool
→ record_step_result
→ more_steps?
→ collect_verification_state
→ verify_business_result
→ return_success / return_failure
```

### 18.1 智能体的自由度

智能体可以：

- 改写和理解员工表达；
- 决定查询哪些只读 Tool 来定位任务；
- 从查询结果中提取 Skill 参数；
- 在多个 Skill 中选择最匹配者；
- 为当前固定步骤生成 Tool 参数；
- 根据错误判断是否立即停止。

智能体不可以：

- 跳过已发布 Skill 的写步骤；
- 新增未定义写步骤；
- 改变 Tool；
- 调用目录外 API；
- 在多个业务对象中私自选择；
- 修改已发布 Skill。

### 18.2 执行图状态

```yaml
run_id:
user_request:
candidate_objects:
selected_object:
candidate_skills:
selected_skill:
bound_inputs:
current_step_index:
step_results:
verification_result:
final_response:
errors:
```

## 19. 两条用户流程

### 19.1 员工演示流程

1. 员工进入演示工作台。
2. 选择一条库存不足任务。
3. 输入目标。
4. 点击开始演示。
5. 中控启动 Playwright 受控浏览器。
6. 员工在办公用品系统查看任务。
7. 员工在采购系统创建采购申请。
8. 员工取得采购单号。
9. 员工回到办公用品系统回写单号并更新状态。
10. 员工点击结束演示。
11. 页面显示“正在分析”。
12. 多个智能体生成 Skill 并自动测试。
13. 测试通过，页面显示“Skill 已发布”。
14. 测试失败，页面显示失败摘要并要求重新演示。

### 19.2 普通员工执行流程

1. 员工进入普通任务中心。
2. 输入自然语言任务。
3. 智能体查询并定位任务。
4. 若存在多个候选，页面让员工选择。
5. 智能体匹配已发布 Skill。
6. LangGraph 指挥执行智能体逐步调用 API Tool。
7. 页面显示当前步骤。
8. 验证智能体查询两个系统的最终状态。
9. 成功时返回采购单号和完成状态。
10. 失败时返回失败步骤、已产生的业务对象和是否可以重新发起。

## 20. 无害测试环境

### 20.1 V1 定义

V1 的“无害”指：

- 只访问本机两个测试系统；
- 只使用测试数据库；
- 使用带测试标记的数据；
- 每个测试前重置或创建隔离数据；
- 不访问外部真实系统；
- 测试结果可以删除或整体重置。

### 20.2 数据准备

测试智能体只生成业务值。

确定性 Fixture Service 负责：

- 重置测试数据库；
- 创建指定内容的库存不足任务；
- 返回任务 ID；
- 在测试结束后保留证据并恢复基础数据。

Fixture Service 是测试基础设施，不包含 Skill 业务判断。

## 21. 幂等策略

### 21.1 目标

对同一来源任务重复执行时，不能创建两个采购申请。

### 21.2 幂等键

每个写步骤的幂等键由确定性代码生成：

```text
skill_id + skill_version + source_system + source_object_id + step_id
```

### 21.3 测试系统支持

测试业务 API 接受 `Idempotency-Key` Header。

外部系统保存：

- 幂等键；
- 首次响应；
- 对应业务对象。

相同键再次调用时返回首次结果，不重复写入。

### 21.4 智能体职责

智能体负责理解“哪个业务对象是本次执行的来源对象”。

代码负责按模板生成幂等键，模型不能自己发明幂等键。

## 22. 失败处理

### 22.1 演示无法编译

情况：

- 关键请求未匹配 API 目录；
- 无法确定字段来源；
- 缺少采购单号回写；
- 轨迹不完整。

处理：

- 不生成可执行 Skill；
- 保存原因；
- 提示员工重新演示。

### 22.2 自动测试失败

处理：

- 不发布；
- 不自动修复；
- 保存测试、步骤和验证证据；
- 提示员工重新演示。

### 22.3 正式运行失败

处理：

- 停止后续写步骤；
- 保存已完成步骤；
- 查询是否已经产生采购申请；
- 返回明确失败信息；
- 不自动修改 Skill；
- V1 不进行自动恢复或自动发版。

### 22.4 模型输出无效

每个模型节点：

1. 使用结构化输出；
2. Pydantic 校验失败后，携带校验错误重试一次；
3. 第二次失败则停止图；
4. 不使用无法验证的自由文本继续执行。

### 22.5 模型或网络超时

- 只读操作可以由 LangGraph 节点按固定次数重试；
- 写操作是否重试由幂等支持决定；
- 不具备幂等保证的写操作不自动重试；
- V1 页面显示“执行中断”，而不是伪造成功。

## 23. 日志与证据

虽然 V1 不建设观察台，但必须保存：

- Recording；
- OperationTrace；
- API 目录版本；
- 智能体结构化输入输出；
- Skill 候选与发布版本；
- TestPlan 和 TestCaseResult；
- ExecutionRun 和 StepResult；
- VerificationResult；
- Playwright Trace；
- 关键截图；
- 模型调用错误；
- API 请求响应摘要。

不保存：

- 模型隐式思维链；
- API Key；
- Cookie；
- 密码；
- Authorization Header；
- 不受控的完整敏感 Header。

## 24. 存储边界

V1 使用 SQLite 和本地文件：

### SQLite

保存结构化数据：

- recordings；
- agent_runs；
- skill_versions；
- skill_tests；
- execution_runs；
- execution_steps；
- verification_results。

### 本地文件

保存大证据：

- Playwright Trace ZIP；
- 截图；
- 原始脱敏轨迹 JSON。

数据库只保存文件引用和 SHA-256。

## 25. 后端接口边界

建议的 V1 API：

```text
POST /recordings
POST /recordings/{id}/start
POST /recordings/{id}/stop
GET  /recordings/{id}

GET  /skills
GET  /skills/{id}

POST /task-runs
POST /task-runs/{id}/select-object
GET  /task-runs/{id}
GET  /task-runs/{id}/events
```

说明：

- `stop` 后异步或后台启动学习图；
- `GET /recordings/{id}` 返回学习、测试和发布状态；
- `POST /task-runs` 接受自然语言；
- `select-object` 只在出现多个候选时使用；
- `events` 用于前端显示步骤进度。

V1 可以使用 FastAPI BackgroundTasks 或应用内 asyncio task，不引入 Celery。

## 26. 前端状态

### 26.1 演示工作台状态

```text
idle
recording
analyzing
testing
published
needs_reteach
```

### 26.2 普通任务运行状态

```text
understanding
needs_object_selection
matching_skill
executing
verifying
succeeded
failed
```

前端不解释智能体内部 Schema，只显示员工可理解的状态和摘要。

## 27. 自动测试要求

### 27.1 单元测试

- Tool 目录 OpenAPI 匹配；
- BindingExpression 解析；
- Pydantic Schema 校验；
- 幂等键生成；
- 自动发布门槛；
- 敏感 Header 脱敏。

### 27.2 集成测试

- 录制期间捕获 UIEvent；
- 捕获并匹配 APIExchange；
- OperationTrace 生成；
- LangGraph 学习图完整运行；
- 候选 Skill 三类测试；
- 自动发布；
- 自然语言执行图；
- 多业务对象选择；
- 运行失败停止。

### 27.3 端到端验收

必须通过以下场景：

1. 员工完成一次样板演示。
2. 系统自动生成候选 Skill。
3. 正常、参数变化和幂等测试全部通过。
4. Skill 自动发布。
5. 员工使用自然语言处理另一条库存不足任务。
6. 系统只创建一条采购申请。
7. 采购单号被正确回写。
8. 办公用品任务状态变为“采购中”。
9. 重复发起同一任务不产生重复申请。
10. 模拟一个 API 失败后，运行停止且日志能说明已完成步骤和副作用。

## 28. V1 完成定义

只有以下条件全部满足，V1 才算完成：

- 演示工作台可完成一次录制；
- 页面动作和 API 请求形成 OperationTrace；
- 智能体生成的 Skill 通过 Schema 校验；
- 智能体自动生成并完成三类无害测试；
- 通过测试的 Skill 自动发布；
- 普通任务中心支持自然语言发起；
- LangGraph 指挥智能体调用已发布 Skill；
- 最终业务状态由验证智能体确认；
- 幂等测试证明没有重复采购申请；
- 失败场景保存可诊断日志；
- 后端 pytest 通过；
- 前端构建通过。

## 29. 后续演进接口

V1 完成后，可在不改变 Skill 核心边界的前提下增加：

- Playwright Web UI 执行步骤；
- 多次演示融合；
- 自动修复候选版本；
- 管理员观察台；
- OpenAdapt 桌面录制；
- UFO UIA Operator；
- UI-TARS 视觉 Operator；
- Process Discovery；
- 权限和租户治理。

这些能力不应提前进入 V1 实现计划。
