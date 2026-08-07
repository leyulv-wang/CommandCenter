# HTTP MES 网络观察兼容验证

## 故障现象

真实 MES 录制能够采集页面点击，但没有 API exchange。扩展控制台显示内容脚本读取
`crypto.subtle.digest` 失败。MES 使用普通 HTTP 页面，内容脚本所在上下文无法保证 Web
Crypto SubtleCrypto 可用；仅依赖页面注入的 `fetch`/XHR 包装也不能覆盖所有请求来源。

## 修复边界

1. 哈希函数在 `crypto.subtle` 不可用时使用等价的纯 TypeScript SHA-256，不降低指纹格式。
2. 扩展后台通过 Chrome `webRequest` 观察活动录制标签页和允许 origin 内的网络元数据。
3. 兜底证据仅包含 URL、方法、状态码和耗时，不采集请求头、响应头、Cookie、Token 或正文。
4. 页面主通道存在 HTTP 请求时丢弃兜底 HTTP 事件；仅当主通道完全缺失时使用兜底。
5. 选择规则是协议层确定性不变量，不包含 MES 路径、按钮名称、关键词或时间阈值。
6. 局部导航不确定性由智能体保留和解释；核心 API 证据充分时仍可继续归因和学习。

## 自动验证结果

- 扩展单元测试：33 个文件、168 个测试通过。
- 扩展 TypeScript 类型检查通过。
- Chrome MV3 生产构建通过，产物声明 `webRequest`，未声明 `debugger`。
- 本地真实扩展端到端测试通过：采集 `GET /api/submissions`，完成 API Skill 学习与验证。
- 端到端测试比较操作前后采购申请数据，确认只读录制和验证未产生写入。
- 后端测试：245 个通过。
- 前端测试：14 个通过；生产构建通过。

## 查询参数指纹补充验证

- 相同页面输入值与 API query 值产生相同 HMAC 指纹。
- 重复 query 参数保留多个独立指纹，空值不生成值指纹。
- 上传 payload 不包含测试查询原值；后端拒绝非法参数名和非 HMAC 指纹。
- 字段映射提示要求智能体综合等值、语义、时序、归因和 Tool schema，不允许仅凭名称猜测。
- API 学习已有结构化失败原因时，后续浏览器候选异常不会再把它覆盖成通用错误。
- 重启后端加载新 schema 后，本地真实扩展只读 E2E 通过，采购数据前后未变化。

## Skill 测试绑定与真实 MES 重新分析

真实 MES 首次进入无害测试时，候选 Skill 使用
`task.content.purchaseDepartment`，测试设计智能体未在 fixture 中提供对应字段，导致
`BindingResolver` 抛出 `KeyError` 并使后台分析成为系统失败。

修复后：

- 测试设计智能体必须为 `task.*`、`literal.*` 和合法前序 `steps.*` 绑定提供完整上下文。
- 只读测试器在调用 Tool 前预检外部绑定；绑定缺失返回结构化测试失败且不发送请求。
- 重新分析会清除旧的 `failure_stage` 和 `failure_reasons`，不保留过期系统状态。
- 已保存录制 `68f5c5bc-607e-47a5-9c91-3cae8df4f19f` 无需重新操作 MES 即可重新分析。
- 重新分析已成功完成 Skill 编译并进入三类 Tool 测试；三个测试均因
  `MissingCredential` 失败，而不是绑定异常或系统崩溃。

## 第一条路径范围收敛与最终验收

当前版本只验收“页面录制 + API 证据 → 智能体对齐 → 生成 API Skill”，不实现凭据桥、
浏览器复现或真实 MES 代执行。缺少执行凭据不代表学习失败：当候选已经成功编译，且三类
只读测试仅被 `MissingCredential` 阻塞时，系统保留 `api_candidate`，标记
`execution_verification=pending_system_connection`，不降级为浏览器 Skill。

重复分析还暴露了测试结果唯一键冲突：同一 Skill 版本、同一测试类别原先会重复插入。
存储层现已按 `(skill_id, skill_version, category)` 更新结果，使保存的录制可以安全重分析。

已保存的真实 MES 录制 `68f5c5bc-607e-47a5-9c91-3cae8df4f19f` 最终验证结果：

- 状态：`api_candidate`；分析阶段：`completed`。
- Skill：`查询采购申请列表`；候选状态：`candidate`。
- 执行验证：`pending_system_connection`。
- 无 `failure_stage`，无 `failure_reasons`，未生成浏览器 Skill。
- 不需要重新操作 MES，也没有对 MES 进行写入。

此结果代表第一条路径的学习闭环完成。真实调用与发布属于以后接入业务系统执行连接后的
独立阶段，不再混入当前录制学习验收。
