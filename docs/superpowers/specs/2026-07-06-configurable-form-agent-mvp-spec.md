# 配置化表单执行智能体 MVP Spec

## 实现状态

状态：已实现第一版 mock 演示闭环。

已实现内容：

1. FastAPI 后端接口。
2. LangGraph 表单执行工作流。
3. JSON 表单模板配置。
4. 动态前端演示页面。
5. 流程类接口 payload 生成。
6. 自定义 URL 接口 payload 生成。
7. 明细列表字段支持。
8. Mock 外部提交。
9. 自动化测试。

未实现内容：

1. 真实外部接口提交。
2. 后台表单配置管理页面。
3. AI 自动生成表单配置。
4. 用户登录和真实操作人身份来源。

## 1. 项目定位

本项目第一版做一个配置化表单执行智能体。

它不是先做自然语言聊天，也不是先做复杂审批系统。第一版只解决一个核心问题：

> 新表单通过配置接入，用户选择表单并填写后，系统自动校验、生成 `formValues`，再按配置调用外部提交接口创建单子。

这样可以先证明最重要的能力：

1. 不同表单字段不写死。
2. 新表单优先靠配置接入。
3. 提交流程由统一智能体工作流执行。

## 2. 第一版目标

第一版只做最小闭环：

1. 管理员配置表单模板。
2. 用户选择表单。
3. 系统根据配置渲染动态表单。
4. 用户填写表单。
5. 系统校验必填字段和字段类型。
6. LangGraph 工作流生成 `formValues`。
7. 系统按接口类型组装外部提交参数。
8. 系统调用真实或模拟外部 API。
9. 系统返回提交结果和单号。

## 3. 第一版表单范围

第一版先支持三类示例表单：

1. 采购申请
2. 售后处理
3. 人事申请

这三类表单只是首批配置示例，不代表代码只能支持这三类。

## 4. 不做的内容

第一版不做：

1. 自然语言输入
2. AI 自动选表单
3. AI 自动预填字段
4. 复杂审批流
5. 自动催办
6. 数据大屏
7. 多租户
8. 复杂权限系统

这些能力以后可以加，但第一版先把配置化接入和统一提交做稳。

## 5. 核心流程

```text
管理员配置表单模板
  ↓
用户选择表单
  ↓
系统读取表单配置
  ↓
系统生成动态表单
  ↓
用户填写并提交
  ↓
LangGraph 工作流校验字段
  ↓
LangGraph 工作流生成 formValues
  ↓
LangGraph 工作流按接口类型组装外部提交参数
  ↓
统一 API 适配器提交
  ↓
返回单号或错误信息
```

## 6. 智能体概念

第一版的智能体不是聊天机器人，而是表单执行智能体。

它的职责是：

1. 读取表单配置。
2. 理解每个字段的 key、类型、必填规则。
3. 校验用户提交的数据。
4. 把用户填写的业务字段映射成外部系统需要的 `formValues`。
5. 调用目标外部提交接口。
6. 返回执行结果。

也就是说：

```text
表单配置 = 智能体的任务说明
用户填写 = 智能体的输入
LangGraph = 智能体执行流程
外部提交接口 = 智能体调用的工具
```

## 7. 技术架构

第一版使用：

1. FastAPI：提供后端接口。
2. LangGraph：编排表单执行工作流。
3. Pydantic：定义表单配置、提交数据、API payload。
4. SQLite、PostgreSQL 或 JSON 文件：保存表单模板配置。
5. HTTPX：调用外部提交接口。
6. Mock API：真实接口未准备好时模拟外部系统。

本项目本地开发环境使用 conda 环境：

```text
langgraph
```

运行 Python 命令时使用：

```powershell
conda run -n langgraph python ...
```

## 8. LangGraph 工作流节点

第一版工作流保持简单：

```text
load_form_config
  ↓
validate_submission
  ↓
build_form_values
  ↓
build_api_payload
  ↓
submit_external_api
  ↓
return_result
```

节点说明：

1. `load_form_config`：读取表单模板配置。
2. `validate_submission`：检查必填字段、字段类型和基础格式。
3. `build_form_values`：生成外部接口需要的 `formValues` JSON。
4. `build_api_payload`：根据接口类型组装外部提交参数。
5. `submit_external_api`：调用真实或模拟外部提交接口。
6. `return_result`：返回单号、状态或错误信息。

## 9. 表单配置模型

每个表单通过配置接入。

示例：

```json
{
  "form_code": "purchase_request",
  "form_name": "采购申请",
  "endpoint_type": "workflow",
  "endpoint": {
    "method": "POST",
    "url": "http://oa.example.com/api/km-review/addReview",
    "fdTemplateId": "template_purchase_001"
  },
  "fields": [
    {
      "label": "物品名称",
      "key": "fd_item_name",
      "type": "text",
      "required": true
    },
    {
      "label": "数量",
      "key": "fd_quantity",
      "type": "number",
      "required": true
    },
    {
      "label": "申请原因",
      "key": "fd_reason",
      "type": "textarea",
      "required": true
    }
  ]
}
```

其中：

1. `form_code` 是中控系统内部表单编码。
2. `form_name` 是用户看到的表单名称。
3. `endpoint_type` 是接口类型。
4. `endpoint` 是接口配置，不同接口类型需要的配置不同。
5. `fields` 是字段配置。
6. `fields[].key` 是外部系统 `formValues` 需要的字段 key。

## 10. 外部接口类型

根据客户补充，第一版先抽象两类接口。

### 10.1 流程类接口

流程类接口的特点：

1. 启动接口是同一个。
2. 所有表单都调用同一个 URL。
3. 不同单据通过 `fdTemplateId` 区分。
4. 不同单据的字段都放在 `formValues` 中。
5. 每个单据的 `formValues` 字段由表单配置决定。

流程类接口适合采购申请、人事申请、售后处理这类走统一流程引擎的单据。

第一版重点处理这些字段：

```text
docSubject      单据标题
fdTemplateId    流程模板 ID
docContent      正文内容，可选
formValues      表单字段 JSON 字符串
docCreator      发起人
docStatus       文档状态
flowParam       流程参数，可选
attachmentForms 附件，可选
identity        发起人身份，可选
```

流程类最小 payload：

```json
{
  "docSubject": "采购申请：20 个包装箱",
  "fdTemplateId": "template_purchase_001",
  "formValues": "{\"fd_item_name\":\"包装箱\",\"fd_quantity\":20,\"fd_reason\":\"仓库库存不足\"}",
  "docCreator": "test_user",
  "docStatus": "20"
}
```

流程类表单配置示例：

```json
{
  "form_code": "purchase_request",
  "form_name": "采购申请",
  "endpoint_type": "workflow",
  "endpoint": {
    "method": "POST",
    "url": "http://oa.example.com/api/km-review/addReview",
    "fdTemplateId": "template_purchase_001",
    "default_docStatus": "20"
  },
  "fields": [
    {
      "label": "物品名称",
      "key": "fd_item_name",
      "type": "text",
      "required": true
    }
  ]
}
```

### 10.2 自定义 URL 接口

自定义 URL 接口的特点：

1. 每个接口 URL 不同。
2. URL 由表单配置决定。
3. 入参固定只有两个：`docOperator` 和 `formValues`。
4. `docOperator` 只传操作人 ID。
5. `formValues` 传具体业务字段。

客户给出的示例接口：

```text
POST https://oa.example.com/api/orders
```

示例参数：

```json
{
  "docOperator": "{\"Id\":\"demo-user-001\"}",
  "formValues": "{\"orderNo\":\"测试001\",\"contractNum\":\"合同002\",\"fd_detail_list\":[{\"goodsCode\":\"sp001\"},{\"goodsCode\":\"sp002\"}]}"
}
```

其中 `formValues` 支持普通字段和明细列表字段。

自定义 URL 表单配置示例：

```json
{
  "form_code": "tower_order",
  "form_name": "铁塔订单新增",
  "endpoint_type": "custom_url",
  "endpoint": {
    "method": "POST",
    "url": "https://oa.example.com/api/orders",
    "operator_param": "docOperator",
    "values_param": "formValues"
  },
  "fields": [
    {
      "label": "订单号",
      "key": "orderNo",
      "type": "text",
      "required": true
    },
    {
      "label": "合同编号",
      "key": "contractNum",
      "type": "text",
      "required": true
    },
    {
      "label": "商品明细",
      "key": "fd_detail_list",
      "type": "list",
      "required": true,
      "item_fields": [
        {
          "label": "商品编码",
          "key": "goodsCode",
          "type": "text",
          "required": true
        }
      ]
    }
  ]
}
```

## 11. Payload 生成规则

系统提交时不直接写死接口参数，而是根据 `endpoint_type` 生成 payload。

流程类接口：

```text
docSubject
fdTemplateId
formValues
docCreator
docStatus
```

自定义 URL 接口：

```text
docOperator
formValues
```

两类接口共同点：

1. 用户填写的业务字段最终都进入 `formValues`。
2. `formValues` 的字段 key 由表单配置决定。
3. 系统只负责校验、映射和提交，不理解每个业务字段背后的复杂业务含义。

## 12. 快速接入新表单

新增表单时，优先不改代码。

接入步骤：

1. 判断接口类型：流程类接口或自定义 URL 接口。
2. 如果是流程类接口，获取统一启动 URL 和 `fdTemplateId`。
3. 如果是自定义 URL 接口，获取该表单自己的 URL。
4. 获取表单字段 key、字段名称、字段类型、必填规则。
5. 如果有明细列表，配置列表字段和子字段。
6. 在中控系统新增一份表单配置。
7. 在页面上自动出现新表单。
8. 用户填写后，系统按配置生成 `formValues` 并提交。

目标效果：

```text
新增表单 = 新增配置
不是新增页面代码
不是新增后端提交逻辑
```

## 13. 三类初始表单

### 13.1 采购申请

建议字段：

1. 物品名称
2. 数量
3. 规格
4. 申请原因
5. 使用部门

### 13.2 售后处理

建议字段：

1. 客户名称
2. 设备信息
3. 问题描述
4. 紧急程度
5. 联系人
6. 联系方式

### 13.3 人事申请

建议字段：

1. 申请类型
2. 申请人
3. 所属部门
4. 开始时间
5. 结束时间
6. 申请原因

真实字段以外部系统提供的字段 key 和模板配置为准。

## 14. MVP 成功标准

第一版完成后，需要能证明：

1. 可以配置采购、售后、人事三个表单。
2. 前端可以根据配置渲染不同字段。
3. 用户可以提交不同表单。
4. 后端可以校验字段。
5. LangGraph 工作流可以生成正确 `formValues`。
6. 系统可以组装流程类接口 payload。
7. 系统可以组装自定义 URL 接口 payload。
8. 系统可以调用 mock API 或真实 API。
9. 新增一个简单表单时，不需要写新的表单页面和提交逻辑。

## 15. 后续升级方向

第一版完成后，再考虑：

1. 自然语言输入。
2. AI 自动选择表单。
3. AI 根据用户描述预填字段。
4. 缺字段时 AI 自动追问。
5. 更复杂的分派和审批规则。
6. 企业微信、钉钉、飞书入口。
