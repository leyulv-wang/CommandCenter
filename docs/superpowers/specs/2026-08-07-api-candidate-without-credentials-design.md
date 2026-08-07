# 无执行凭证时保留 API Skill 设计

## 决策

第一条路径的 V1 成功边界是：录制 API 证据、匹配允许 Tool、完成字段映射并编译 API Skill。
真实系统未配置执行凭证时，不继续实时 API 测试，不降级为浏览器 Skill，也不标记分析失败。

当且仅当所有无害测试失败均由 `MissingCredential` 导致，且候选 Skill 的全部步骤均为目录中
允许的只读 Tool，中控把录制标记为 `api_candidate`，把 Skill 状态恢复为 `candidate`，并记录
`execution_verification=pending_system_connection`。不得把该状态表述为已通过实时测试或已发布。

本地测试系统或已经配置凭证的系统继续执行三类真实测试；只有三类测试全部通过时才进入
`verified_candidate` 或 `published`。

## 安全与泛化边界

- `MissingCredential` 是稳定的执行基础设施状态，由确定性代码识别。
- 任何其他执行失败、写 Tool、未知副作用或混合失败不得转为 `api_candidate`。
- 不捕获浏览器 Token，不增加 MES 路径、参数或按钮特例。
- `api_candidate` 不进入员工可执行 Skill 列表。

## 展示

中控观察页将 `api_candidate` 显示为“API Skill 已生成”，说明“已完成录制学习，待业务系统
配置执行连接后再做实时验证”。它属于 API 路径，不显示浏览器候选文案。

## 验收

保存的 MES 录制重新分析后状态为 `api_candidate`，保留 API Skill，且不再生成
`browser_candidate`。本地采购系统闭环、后端、扩展和前端测试继续通过。
