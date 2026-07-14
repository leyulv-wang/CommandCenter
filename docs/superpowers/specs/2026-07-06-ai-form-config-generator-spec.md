# AI 表单配置生成模块 Spec

## 1. 模块定位

本模块用于把客户提供的接口说明、字段说明或示例参数，转换成系统可用的表单配置草稿。

它不是直接创建正式表单，而是生成一份可检查、可修改、可测试的配置草稿。管理员确认后，配置才进入正式表单模板。

## 2. 目标

第一版目标：

1. 接收客户提供的接口说明文本。
2. 调用配置好的大模型。
3. 判断接口类型：`workflow` 或 `custom_url`。
4. 提取接口 URL、`fdTemplateId`、字段 key、字段类型、必填信息。
5. 识别明细列表字段。
6. 生成符合当前系统格式的表单配置 JSON 草稿。
7. 返回风险提示和不确定项。

## 3. 环境变量

模型配置放在项目根目录：

```text
.env.ai
```

字段：

```text
AI_CONFIG_MODEL_BASE_URL=
AI_CONFIG_MODEL_NAME=
AI_CONFIG_API_KEY=
AI_CONFIG_TIMEOUT_SECONDS=60
```

说明：

1. `AI_CONFIG_MODEL_BASE_URL`：模型服务地址。
2. `AI_CONFIG_MODEL_NAME`：模型名称。
3. `AI_CONFIG_API_KEY`：模型 API Key。
4. `AI_CONFIG_TIMEOUT_SECONDS`：请求超时时间。

API Key 不写入代码和 spec。

## 4. 接口设计

新增接口：

```text
POST /ai/form-config/generate
```

请求示例：

```json
{
  "form_name": "铁塔订单新增",
  "description": "POST https://oa.example.com/api/orders，入参 docOperator 和 formValues，formValues 示例为 {\"orderNo\":\"测试001\",\"contractNum\":\"合同002\",\"fd_detail_list\":[{\"goodsCode\":\"sp001\"}]}"
}
```

返回示例：

```json
{
  "draft_config": {
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
  },
  "warnings": [
    "字段是否必填未在说明中明确，已根据示例暂定为 true",
    "字段中文名称由 key 推断，建议管理员确认"
  ]
}
```

## 5. 核心流程

```text
客户粘贴接口说明
  ↓
系统读取 .env.ai 模型配置
  ↓
调用大模型生成配置草稿
  ↓
系统用 Pydantic 校验草稿结构
  ↓
返回配置草稿和风险提示
  ↓
管理员检查和修改
  ↓
测试提交
  ↓
确认后保存为正式表单配置
```

## 6. 生成规则

模型必须输出当前系统已支持的配置格式。

支持的接口类型：

1. `workflow`：统一流程启动接口，通过 `fdTemplateId` 区分单据。
2. `custom_url`：每个表单单独 URL，入参为 `docOperator` 和 `formValues`。

支持的字段类型：

1. `text`
2. `number`
3. `textarea`
4. `select`
5. `datetime`
6. `list`

如果模型无法确认字段类型，默认使用 `text`，并在 `warnings` 中提示。

如果模型无法确认是否必填，默认使用 `true`，并在 `warnings` 中提示。

## 7. 安全原则

第一版不允许 AI 直接启用新表单。

必须经过：

1. 结构校验。
2. 管理员确认。
3. 测试提交。
4. 手动保存。

这样可以避免字段 key、接口 URL、`fdTemplateId` 或明细结构识别错误导致真实系统提交失败。

## 8. MVP 成功标准

第一版完成后，需要能证明：

1. 系统能读取 `.env.ai` 中的模型配置。
2. 系统能接收接口说明文本。
3. 系统能返回表单配置草稿。
4. 草稿能通过现有 `FormTemplate` 结构校验。
5. 草稿能包含 `warnings`。
6. 草稿不自动保存为正式表单。
7. 管理员可以复制或确认后保存配置。

## 9. 后续扩展

后续可以增加：

1. 上传接口文档文件。
2. 图片 OCR 后生成配置。
3. 直接从 Swagger/OpenAPI 文档生成配置。
4. 配置草稿在线编辑页面。
5. 一键测试提交。
6. 管理员确认后一键保存为正式表单。
