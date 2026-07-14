from app.ai_config.generator import normalize_draft_config


def test_normalizes_llm_list_fields_alias_to_item_fields():
    raw = {
        "form_code": "tower_order",
        "form_name": "铁塔订单新增",
        "endpoint_type": "custom_url",
        "endpoint": {
            "url": "https://oa.example.com/api/orders",
        },
        "fields": [
            {
                "label": "商品明细",
                "key": "fd_detail_list",
                "type": "list",
                "required": True,
                "fields": [
                    {
                        "label": "商品编码",
                        "key": "goodsCode",
                        "type": "text",
                        "required": True,
                    }
                ],
            }
        ],
    }

    template = normalize_draft_config(raw)

    assert template.fields[0].item_fields[0].key == "goodsCode"


def test_normalizes_llm_field_code_and_field_name_aliases():
    raw = {
        "form_code": "tower_order",
        "form_name": "铁塔订单新增",
        "endpoint_type": "custom_url",
        "endpoint": {
            "url": "https://oa.example.com/api/orders",
        },
        "fields": [
            {
                "field_name": "订单号",
                "field_code": "orderNo",
                "type": "text",
                "required": True,
            }
        ],
    }

    template = normalize_draft_config(raw)

    assert template.fields[0].label == "订单号"
    assert template.fields[0].key == "orderNo"


def test_normalizes_name_as_key_when_label_exists():
    raw = {
        "form_code": "tower_order",
        "form_name": "铁塔订单新增",
        "endpoint_type": "custom_url",
        "endpoint": {
            "url": "https://oa.example.com/api/orders",
        },
        "fields": [
            {
                "name": "orderNo",
                "label": "订单号",
                "type": "text",
                "required": True,
            }
        ],
    }

    template = normalize_draft_config(raw)

    assert template.fields[0].label == "订单号"
    assert template.fields[0].key == "orderNo"


def test_normalizes_field_and_label_text_aliases():
    raw = {
        "form_code": "office_supply",
        "form_name": "办公用品系统",
        "endpoint_type": "custom_url",
        "endpoint": {
            "url": "http://127.0.0.1:8102/api/forms/submit",
        },
        "fields": [
            {
                "field": "itemName",
                "label_text": "申请物品",
                "type": "text",
                "required": True,
            },
            {
                "field": "quantity",
                "label_text": "数量",
                "type": "number",
                "required": True,
            },
        ],
    }

    template = normalize_draft_config(raw)

    assert template.fields[0].key == "itemName"
    assert template.fields[0].label == "申请物品"
    assert template.fields[1].key == "quantity"
    assert template.fields[1].label == "数量"


def test_custom_url_draft_defaults_to_http_submit_mode():
    raw = {
        "form_code": "office_supply_request",
        "form_name": "办公用品申请",
        "endpoint_type": "custom_url",
        "endpoint": {
            "url": "http://127.0.0.1:8102/api/forms/submit",
        },
        "fields": [
            {
                "label": "申请物品",
                "key": "itemName",
                "type": "text",
                "required": True,
            }
        ],
    }

    template = normalize_draft_config(raw)

    assert template.endpoint.submit_mode == "http"


def test_workflow_draft_defaults_to_http_submit_mode():
    raw = {
        "form_code": "purchase_request",
        "form_name": "采购申请",
        "endpoint_type": "workflow",
        "endpoint": {
            "url": "http://127.0.0.1:8101/api/workflows/start",
            "fdTemplateId": "purchase_request_001",
        },
        "fields": [
            {
                "label": "采购物品",
                "key": "fd_item_name",
                "type": "text",
                "required": True,
            }
        ],
    }

    template = normalize_draft_config(raw)

    assert template.endpoint.submit_mode == "http"
