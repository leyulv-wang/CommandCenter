# MES 只读执行连接设计

## 目标

在当前“浏览器演示 → API Skill”学习闭环之后，补齐测试阶段的真实执行连接：用户不需要
寻找或复制 `X-Access-Token`，浏览器扩展在明确授权后从正常 MES 请求中自动同步凭据，
中控加密保存并用于 Skill 验证和自然语言只读查询。

第一版完成以下纵向闭环：

```text
扩展授权连接
→ MES 正常查询携带 Token
→ 中控加密保存
→ 自动验证已有 API Skill
→ 用户在中控输入自然语言
→ 智能体选择 Skill 和参数
→ 中控调用 MES GET API
→ 展示查询结果
```

## 用户流程

1. 用户登录 MES，打开浏览器扩展。
2. 用户点击“允许此 MES 登录会话连接中控”。
3. 扩展保存授权开关，但不保存 Token。
4. 用户在 MES 正常执行任意一次查询。
5. 扩展只读取匹配系统配置的 `X-Access-Token`，发送到本机中控。
6. 中控通过 Windows 凭据管理器加密保存，并返回“益丰 MES 已连接”。
7. 中控使用该连接重新运行最新 `api_candidate` 的既有只读测试计划，不重新调用模型生成 Skill。
8. 验证通过后，Skill 进入 `verified_candidate`，可以在测试台执行。
9. 用户在中控输入“查询采购申请列表”等自然语言任务。
10. 智能体选择 Skill、提取查询参数，中控调用 MES API 并展示结果。

浏览器关闭或中控重启后，已经保存且仍有效的 Token 可以继续使用。Token 失效时，扩展在
用户仍授权的前提下从后续正常 MES 请求自动更新，不要求用户手动复制。

## 扩展授权与凭据捕获

扩展配置增加声明式 `credentialHeader`，当前 MES 配置为 `X-Access-Token`。只有同时满足以下
条件时才读取请求头：

1. 用户已为该系统开启持久连接授权；
2. 请求属于该系统配置的精确 origin；
3. 请求由当前配置匹配的业务标签页发出；
4. 请求头名称与配置中的 `credentialHeader` 大小写无关精确一致；
5. 凭据非空且不包含换行符。

扩展使用 `webRequest.onBeforeSendHeaders` 观察请求头。它不读取 Cookie、Authorization、
请求正文、响应正文或其他请求头。Token 不进入 IndexedDB、录制事件、上传队列、控制台日志
或错误文本。扩展本地只保存“允许连接”的布尔状态和系统代码。

连接授权可以在扩展中手动关闭。关闭后扩展停止捕获，并要求中控删除该系统凭据。

## 连接握手

中控提供系统连接 API：

- `POST /system-connections/{system_code}/begin`：创建短期连接握手，返回随机连接令牌；
- `PUT /system-connections/{system_code}/credential`：扩展携带连接令牌提交允许的凭据；
- `GET /system-connections/{system_code}`：只返回连接、过期或未连接状态；
- `DELETE /system-connections/{system_code}`：删除保存的凭据并断开连接；
- `POST /system-connections/{system_code}/verify-latest-skill`：验证最新 API 候选 Skill。

连接令牌仅用于扩展到本机中控的握手，不是 MES Token，不写数据库。所有端点只接受已存在
的系统配置；提交的请求头名称必须等于系统配置声明的凭据头。

## 凭据保存

定义可替换的 `SystemCredentialStore` 接口：

- `put(system_code, header, secret)`；
- `headers_for(system_code)`；
- `delete(system_code)`；
- `has(system_code)`。

当前 Windows 测试环境使用 Python `keyring` 调用 Windows 凭据管理器。服务名称固定为
`CommandCenter`，账号键由系统代码和凭据头组成。数据库、JSON、`.env`、Skill 和录制记录中
均不保存 Token。

若操作系统没有安全凭据后端，中控不得降级为明文文件，只报告当前环境不支持持久保存。

当 MES 返回 401 或 403 时，中控删除已保存凭据并将连接标记为需要重新登录。普通网络错误
不会删除仍可能有效的凭据。

## Skill 重新验证

最新录制已经保存 `candidate_skill` 和 `test_plan`，连接建立后直接复用这些结构化结果：

1. 读取来源系统一致、状态为 `api_candidate` 的最新录制；
2. 验证 Skill 所有步骤均为系统配置允许的 `read` Tool；
3. 使用保存的测试计划执行三类测试；
4. 所有测试通过后调用仓库的 `mark_verified_candidate`；
5. 更新录制状态、测试结果和执行验证状态；
6. 任一测试失败则保留候选状态，并显示结构化失败原因。

这里不重新蒸馏或修改 Skill，也不因为拥有 Token 就绕过既有测试门禁。

## 自然语言执行

执行图从“只支持本地采购系统”改为按 Skill Tool 动态选择系统目录和凭据：

1. 执行上下文加载 `verified_candidate` 和 `published` Skill；
2. 匹配智能体根据用户请求、Skill 描述和输入 schema 选择 Skill；
3. 匹配智能体提取查询参数，并为缺省分页参数生成合理值；
4. 确定性执行器根据 `tool_id` 定位系统目录；
5. 执行器再次检查 Tool 白名单和 `side_effect=read`；
6. 从 `SystemCredentialStore` 读取该系统凭据并调用 API；
7. 验证智能体检查响应是否符合 Skill 成功条件；
8. 中控只展示经过大小限制和敏感字段过滤的查询结果。

语义匹配、参数理解和结果解释由智能体负责。代码只负责 Skill 状态、系统边界、凭据、Tool
白名单、只读限制、响应大小、超时和审计元数据。

## 前端变化

单页测试台增加一个紧凑的“业务系统连接”状态：

- 未连接：提示用户打开 MES 扩展并授权；
- 已连接：显示系统名称和“可验证只读 Skill”，不显示 Token；
- 需要重新登录：说明 MES 凭据已失效；
- 提供“验证最新 Skill”和“断开连接”。

自然语言执行区继续使用现有 `/task-runs`，但结果区增加结构化查询输出展示。前端不决定 Skill
是否可执行，也不把 `api_candidate` 伪装为已验证。

## 安全与可观测性

- 第一版只允许 `yifeng_mes` 配置中三个精确 GET 路径；
- 不允许新增、编辑、保存、提交、审核、完成、反审核、反完成或删除；
- Token、Cookie 和密码不得进入日志、异常、测试快照或响应；
- 日志只记录系统代码、Tool ID、HTTP 状态、耗时和脱敏错误码；
- 响应遵守系统配置的超时、频率和最大字节限制；
- 断开连接必须同时删除操作系统凭据和内存副本；
- 持久授权状态不等于执行授权，执行仍受 verified Skill 和只读 Tool 门禁约束。

## 测试策略

先使用本地模拟系统验证完整连接协议，不接触真实 MES：

1. 扩展只在显式授权和精确 origin 下捕获配置头；
2. Token 不进入 IndexedDB、录制证据、日志和 UI；
3. Windows 凭据存储可写入、读取、覆盖和删除；
4. 连接 API 不返回 Token；
5. 保存的测试计划可以将 `api_candidate` 提升为 `verified_candidate`；
6. 自然语言执行能够选择 verified Skill 并调用对应系统 Tool；
7. 非白名单或写操作在请求发出前被拒绝；
8. 401/403 清除凭据，普通网络错误不清除；
9. 中控前端正确显示连接、验证、执行成功和错误状态。

自动测试通过后，真实 MES 只执行采购申请列表查询。验收要求返回查询结果、MES 数据前后无
变化，并确认日志和数据库中不存在凭据。

## 非目标

- 不实现企业账号体系、租户隔离或细粒度用户授权；
- 不保存 MES 用户名和密码；
- 不实现写操作 Skill；
- 不实现浏览器动作回放；
- 不实现服务器级 Vault、SSO 或服务账号轮换；
- 不让候选 Skill 绕过验证直接执行。
