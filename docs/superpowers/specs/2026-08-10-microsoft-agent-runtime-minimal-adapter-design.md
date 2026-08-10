# Microsoft Agent Framework 最小 Runtime Adapter 设计

状态：待用户书面确认

日期：2026-08-10

适用范围：`D:\python\CommandCenter`

## 1. 目的

在不重写现有 LangGraph 业务流程的前提下，为 CommandCenter 增加可替换的 Agent Runtime 边界，并只把 `AgentSuite.match_request` 迁移到 Microsoft Agent Framework。

这次改造要用一条真实业务路径证明以下能力：

1. 模型可在一次匹配任务中进行多轮推理与工具调用；
2. 模型根据上下文动态决定是否查询 Skill 列表或详情；
3. 同一次调用内的消息、工具结果和最终输出由 Runtime 会话管理；
4. 最终业务判断仍通过现有 Pydantic Schema 校验；
5. Runtime 可通过配置切换，后续可以逐个迁移其他智能体角色。

## 2. 当前问题

当前 `StructuredModel.generate(...)` 是一次请求、一次结构化响应的封装。它适合结构化判断，但不提供通用的工具循环、会话、动态工具选择、审批、恢复和统一追踪能力。

`AgentSuite`、LangGraph、Skill 定义和 Tool 执行边界已经承载 CommandCenter 的业务语义，不应为了引入 Runtime 而整体替换。需要替换的是通用智能体运行基础设施，而不是业务架构。

## 3. 范围

### 3.1 本次包含

- 新增稳定的 `AgentRuntime` 项目接口；
- 保留现有实现作为 `LegacyStructuredModelRuntime`；
- 新增 `MicrosoftAgentFrameworkRuntime`；
- 仅迁移 `AgentSuite.match_request`；
- 为该角色暴露调用级、只读的 Skill 查询工具；
- 支持单次匹配调用内的多轮会话；
- 记录最小运行指标和工具事件；
- 用配置选择 Runtime；
- 为新边界和迁移路径补充测试。

### 3.2 本次不包含

- 不迁移其他 `AgentSuite` 方法；
- 不替换现有 LangGraph 学习图或执行图；
- 不修改 Skill、ToolCatalog、ToolExecutor、数据库或前端的数据模型；
- 不引入跨员工请求的长期记忆或向量数据库；
- 不开放写 Tool、外部 API、文件、Shell 或凭据给匹配智能体；
- 不实现 Agent 委派、人工审批 UI、持久化 checkpoint、评测平台或成本仪表盘；
- 不直接嵌入 OpenCode；
- 不一次性采用 Microsoft Agent Framework 的完整工作流抽象。

## 4. 设计原则

1. **业务接口稳定**：`AgentSuite` 继续表达智能体角色，LangGraph 继续表达业务状态机。
2. **Runtime 可替换**：项目代码依赖内部 Protocol，不依赖 Microsoft 类型作为领域模型。
3. **智能体负责判断**：Skill 匹配仍由模型结合上下文判断，代码只约束候选范围和输出协议。
4. **最小权限**：首个 Runtime Agent 只能查看本次调用提供的候选 Skill。
5. **失败可见**：新 Runtime 启动后失败，不静默切回旧实现重新判断。
6. **渐进迁移**：每个角色独立迁移、测试和回滚，不要求同时改造整个系统。

## 5. 架构

```text
LangGraph execution graph
        |
        v
AgentSuite.match_request(user_request, tasks, skills)
        |
        v
AgentRuntime Protocol
   |                         |
   v                         v
LegacyStructuredModelRuntime MicrosoftAgentFrameworkRuntime
                                  |
                                  v
                    call-scoped read-only Skill tools
```

### 5.1 `AgentRuntime` 边界

内部 Runtime 接口接受：

- 逻辑角色和系统指令；
- 用户输入及必要业务上下文；
- Pydantic 输出类型；
- 允许的工具集合；
- 可选会话标识和运行元数据。

接口返回统一结果：

- 已校验的结构化输出；
- Runtime、模型和供应商标识；
- 模型调用次数；
- 工具调用事件；
- 可获得时的 token 用量和成本基础数据；
- 总耗时和 trace ID；
- 不包含模型隐式思维链的错误摘要。

项目领域层不暴露 Microsoft Agent Framework 的 Agent、Session 或消息类型。框架升级和其他供应商 Runtime 的差异都封装在 Adapter 内。

### 5.2 两个 Adapter

`LegacyStructuredModelRuntime` 封装现有 `StructuredModel.generate(...)` 行为，用于兼容、对照测试和显式回滚。它不伪装成具备工具循环。

`MicrosoftAgentFrameworkRuntime` 使用 Microsoft Agent Framework 的 Python 核心包完成模型调用、工具循环、会话消息管理和可观测事件转换。具体依赖采用满足需求的最小包，实施时经当前 Python 环境兼容性验证后固定版本，不默认安装完整元包。

### 5.3 `AgentSuite` 兼容方式

`AgentSuite.match_request(user_request, tasks, skills)` 的公开调用形式保持不变，避免修改执行图及其状态模型。

`AgentSuite` 在内部把本次传入的 `skills` 封装为调用级只读工具，再交给选定 Runtime。旧 Runtime 可以继续一次性接收候选 Skill；Microsoft Runtime 则可以主动查询候选 Skill。

其他 `AgentSuite` 方法继续走现有 `StructuredModel` 路径。本次不为了统一外观而改动没有迁移的角色。

## 6. 首批工具

Microsoft Runtime 的匹配智能体只获得两个工具：

### 6.1 `list_available_skills`

返回本次调用候选 Skill 的紧凑摘要：

- `skill_id`；
- 名称；
- 描述；
- 状态和版本；
- 输入字段摘要；
- 触发示例摘要。

### 6.2 `get_available_skill`

按 `skill_id` 返回本次候选集合内某个 Skill 的完整匹配所需定义。不存在或不在候选集合时返回明确的受控错误。

### 6.3 工具边界

- 数据来自 `match_request` 已接收的候选列表，不新增数据库访问；
- 工具只读，不调用 `ToolExecutor`；
- 工具不能扩大候选集合；
- 工具参数和返回值使用明确 Schema；
- 工具输出按上下文预算截断或摘要，但 Skill ID、版本、输入要求和关键描述不得丢失；
- 最终选择仍必须属于候选集合，并由现有执行流程继续校验。

`tasks` 继续作为初始业务上下文传入，不在本次额外包装成工具。这样首个切片聚焦于 Skill 的动态发现，而不改变当前任务候选生成方式。

## 7. 会话与上下文

本次会话范围是单次 `match_request` 调用：从用户请求开始，包含所有模型消息、Skill 工具调用和最终 `TaskMatchDecision`。

该会话证明 Runtime 能维持工具循环中的短期记忆，但不会跨两个独立员工请求持久化。调用结束后会话可释放；数据库 Schema 不变。

上下文控制遵循：

1. 初始提示不注入全部 Skill 详情；
2. 列表工具返回紧凑摘要；
3. 智能体只按需要查询详情；
4. 设置最大模型轮数、最大工具调用数和超时；
5. 超限时返回受控失败，不继续无限循环；
6. 框架自带压缩能力只有在当前版本经过测试后才启用，本次验收不依赖跨调用压缩。

## 8. 配置与模型供应商

新增配置项：

```text
COMMAND_CENTER_AGENT_RUNTIME=legacy|microsoft
```

默认值为 `legacy`，保证安装依赖但尚未完成环境配置时不改变现有行为。开发、测试和试运行环境通过显式设置 `microsoft` 启用新路径；正式切换也必须是显式配置行为。

Microsoft Adapter 继续读取现有 `.env.ai` 中的模型配置：

```text
AI_CONFIG_MODEL_BASE_URL
AI_CONFIG_MODEL_NAME
AI_CONFIG_API_KEY
AI_CONFIG_TIMEOUT_SECONDS
```

Adapter 把项目配置转换为框架 Provider 配置。API Key 不写入源码、日志、事件或测试 fixture。内部 `AgentRuntime` Protocol 保持供应商无关，以便后续增加 OpenAI、Azure OpenAI、Anthropic 或本地兼容端点。

## 9. 结构化输出

最终输出仍为现有 `TaskMatchDecision`，不创建 Microsoft 专属业务 Schema。

处理顺序：

1. Runtime 完成必要的工具循环；
2. 生成最终结构化结果；
3. Adapter 转换为普通 Python 数据；
4. 使用现有 Pydantic 模型校验；
5. 检查选择的 Skill 是否属于本次候选集合；
6. 只有全部通过才返回执行图。

无效结构不进入后续 Tool 执行。是否允许一次“修复结构”模型轮次由统一上限控制，不能开启无界重试。

## 10. 失败和回滚

### 10.1 启动配置失败

应用启动时校验所选 Runtime、依赖和模型配置。配置选择 `microsoft` 但依赖或必要配置缺失时，应明确启动失败，不能静默使用 `legacy`。

### 10.2 运行失败

Microsoft Runtime 开始处理后，如果发生超时、工具错误、轮数超限或输出校验失败：

- 本次匹配失败并进入现有失败路径；
- 不在同一次业务请求中自动调用旧模型重做判断；
- 不执行任何业务写 Tool；
- 保存可诊断但已脱敏的运行摘要。

这样避免两个 Runtime 对同一请求产生不一致决策，也为未来包含副作用的 Agent 迁移保留安全语义。

### 10.3 回滚

运维可在下一次应用启动时把 `COMMAND_CENTER_AGENT_RUNTIME` 显式改为 `legacy`。回滚不修改数据库、Skill 版本或前端。

## 11. 安全边界

- Runtime 只看到调用所需的任务和候选 Skill；
- 不向 Microsoft Agent Framework 或追踪后端发送 API Key、Authorization Header 或其他凭据；
- 首批工具为内存只读函数，不具备网络和文件副作用；
- 任何未来写 Tool 都必须经过 CommandCenter Tool/Operator 接口、权限、Schema、幂等和审计边界，不能直接注册原始函数；
- telemetry 默认保存摘要和标识，不保存完整敏感业务载荷；
- 不保存或展示模型隐式思维链。

## 12. 可观测性

本次只建立统一事件数据，不建设新页面。每次 Runtime 调用至少记录：

- runtime、provider、model 和逻辑角色；
- trace ID、开始时间、结束时间和耗时；
- 模型调用次数；
- 工具名称、调用顺序、状态和耗时；
- 可获得时的输入/输出 token；
- 成功、超时、协议错误或工具错误分类；
- 最终选择的 Skill ID，不记录隐式推理文本。

如果供应商没有返回 token 或价格信息，字段保持未知，不估造成本。成本金额计算留给后续基于可配置价格表的观测层。

## 13. 测试策略

所有自动测试默认使用 fake model/client，不访问真实模型服务。

### 13.1 Runtime 单元测试

- Legacy Adapter 保持现有结构化调用行为；
- Microsoft Adapter 可执行“列出 Skill → 查询某个详情 → 返回结果”的多轮循环；
- 模型可根据输入选择只调用列表、继续查询详情或直接结束；
- 未注册工具和非法参数被拒绝；
- 超过轮数、工具次数或超时后受控失败；
- 事件和 usage 被转换为统一结果；
- Pydantic 校验失败不产生有效决策。

### 13.2 `match_request` 测试

- 保持原有方法签名和返回类型；
- 选择结果必须来自候选 Skill；
- 查询不存在的 Skill 返回受控工具错误；
- 候选为空时产生明确的无匹配结果或现有协议规定的失败；
- 任务上下文正确进入初始输入；
- 两个独立调用不共享短期会话内容；
- 匹配过程中没有写 Tool 暴露或执行。

### 13.3 配置和回归测试

- `legacy` 和 `microsoft` 可分别构造正确 Adapter；
- 未知 Runtime 值、缺失依赖或缺失配置明确失败；
- 现有 `test_structured_agents.py` 和执行图测试继续通过；
- 后端完整 pytest 通过；
- 本次不要求前端改动。

## 14. 验收标准

以下条件全部满足，最小改造才算完成：

1. 项目存在不依赖 Microsoft 领域类型的 `AgentRuntime` Protocol；
2. 旧结构化模型路径可通过 Adapter 继续工作；
3. `match_request` 可通过 Microsoft Agent Framework 完成真实多轮工具循环；
4. 工具由模型动态选择，且仅限本次候选 Skill 的只读查询；
5. 单次调用内会话能保留先前工具结果，独立调用之间不串数据；
6. 最终输出通过现有 `TaskMatchDecision` 校验和候选范围校验；
7. 失败时不静默回退、不触发业务写操作；
8. 配置、凭据和日志符合项目安全要求；
9. Runtime 事件至少覆盖调用、工具、用量和耗时；
10. 新增测试及现有后端测试全部通过。

## 15. 后续迁移顺序

本切片稳定后，再逐个评估：

1. 把需要检索和动态工具选择的角色迁入 Runtime；
2. 为长流程接入持久化 session/checkpoint 和中断恢复；
3. 为高风险 Tool 增加人工确认；
4. 接入统一 OpenTelemetry、评测数据集和可配置成本统计；
5. 在有清晰角色边界时增加 Agent 委派；
6. 最后再决定哪些 LangGraph 节点适合由框架 Workflow 替代。

每一步都保持 CommandCenter 的 Skill、Tool 和 Operator 接口为稳定领域边界，避免任何单一 Runtime 成为不可替换的业务数据模型。
