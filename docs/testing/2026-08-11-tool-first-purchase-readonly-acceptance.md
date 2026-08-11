# Tool 优先采购只读闭环验收记录

日期：2026-08-11

## 验收范围

本次仅验收益丰 MES 已配置 API 的采购申请只读能力：自然语言列表查询、请购人筛选、分页查询、从已保存列表记录加载主表详情和明细列表。未执行新增、修改、提交、审核、完成、撤销或删除操作。

## 自动化验证

- 后端完整测试：`346 passed`。
- 前端完整测试：`29 passed`。
- 前端生产构建：成功。
- 直接 Tool 任务和详情子任务不会新增候选 Skill 或已发布 Skill。
- 原有浏览器录制、学习、自动测试、候选 Skill 保存与 Skill 执行测试保持通过。

## 真实 MES 只读验收

| 请求 | 运行 ID | 结果 | Tool | 记录数 |
| --- | --- | --- | --- | ---: |
| 查询采购申请列表第一页，每页10条 | `c5443cff-4395-4188-9f6b-506278b5c148` | 成功 | `yifeng_mes:queryPageListUsingGET_183` | 10 |
| 查询请购人孟明佳的采购申请列表 | `e0b0b3f1-e5b8-4e8f-8d01-2cbfdb6074e4` | 成功 | `yifeng_mes:queryPageListUsingGET_183` | 3 |
| 查询采购申请列表第二页，每页5条 | `e9c2f988-b559-4853-9f6d-9fae0c86c2c1` | 成功 | `yifeng_mes:queryPageListUsingGET_183` | 5 |
| 从第一页结果选择一条记录查看详情 | `8ae02d4b-d9c3-4a4a-a4ca-1f716d3ab3a3` | 成功 | `yifeng_mes:queryByIdUsingGET_143`、`yifeng_mes:queryPurchaseApplyDetailListByMainIdUsingGET` | 主表与明细均返回 |

四次运行的 `execution_mode` 均为 `tool`。详情运行保存了父运行 ID，并由后端从父运行结果中解析所选记录，浏览器没有提交完整 MES 记录。

## 安全与证据确认

- 真实业务调用全部为系统配置明确允许的 GET/只读 Tool。
- API 凭据由 Windows keyring 在执行时注入，未进入模型规划上下文。
- 任务运行证据仅保存 Tool ID、业务参数、请求方法与路径、HTTP 状态码。
- 验收记录未保存请求头、Cookie、Token、凭据值或完整原始响应。
- 本地采购测试系统在验收时未启动，组件以降级模式继续完成 MES 验收；该状态不影响真实 MES Tool 闭环。
