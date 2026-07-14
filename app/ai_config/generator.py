import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from app.ai_config.schemas import GenerateFormConfigRequest, GenerateFormConfigResponse
from app.forms.schemas import FormTemplate


SYSTEM_PROMPT = """你是企业表单配置生成助手。只输出 JSON，不要输出 Markdown。
根据接口说明生成如下结构：
{
  "draft_config": FormTemplate,
  "warnings": [string]
}
FormTemplate 字段必须包含 form_code, form_name, endpoint_type, endpoint, fields。
endpoint_type 只能是 workflow 或 custom_url。
endpoint.url 必须是完整 URL。
workflow 接口需要 endpoint.fdTemplateId。
custom_url 接口默认 operator_param 为 docOperator，values_param 为 formValues。
真实业务接口的 endpoint.submit_mode 使用 http。
字段 type 只能是 text, number, textarea, select, datetime, list。
每个字段必须使用 label 和 key，不要使用 field、label_text、field_code、field_name。
list 字段的子字段必须放在 item_fields 中。
如果你输出了 fields 作为 list 子字段，系统会尝试兼容，但你应该优先使用 item_fields。
如果字段中文名、字段类型、必填规则或 form_code 不确定，要在 warnings 说明。
"""


def generate_form_config(
    request: GenerateFormConfigRequest,
) -> GenerateFormConfigResponse:
    load_dotenv(Path(".env.ai"), override=True)
    client = OpenAI(
        base_url=_required_env("AI_CONFIG_MODEL_BASE_URL"),
        api_key=_required_env("AI_CONFIG_API_KEY"),
        timeout=float(os.getenv("AI_CONFIG_TIMEOUT_SECONDS", "60")),
    )
    response = client.chat.completions.create(
        model=_required_env("AI_CONFIG_MODEL_NAME"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(request)},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("模型没有返回内容")
    parsed = json.loads(content)
    draft_config = normalize_draft_config(parsed["draft_config"])
    return GenerateFormConfigResponse(
        draft_config=draft_config,
        warnings=list(parsed.get("warnings", [])),
    )


def normalize_draft_config(raw_config: dict[str, Any]) -> FormTemplate:
    normalized = _normalize_fields_aliases(raw_config)
    if normalized.get("endpoint_type") in {"workflow", "custom_url"}:
        endpoint = normalized.setdefault("endpoint", {})
        if isinstance(endpoint, dict) and "submit_mode" not in endpoint:
            endpoint["submit_mode"] = "http"
    return FormTemplate.model_validate(normalized)


def _normalize_fields_aliases(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_fields_aliases(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized = {key: _normalize_fields_aliases(item) for key, item in value.items()}
    if "key" not in normalized and "field_code" in normalized:
        normalized["key"] = normalized["field_code"]
    if "key" not in normalized and "field" in normalized:
        normalized["key"] = normalized["field"]
    if "key" not in normalized and "label" in normalized and "name" in normalized:
        normalized["key"] = normalized["name"]
    if "label" not in normalized:
        for alias in ("field_name", "label_text", "name", "title"):
            if alias in normalized:
                normalized["label"] = normalized[alias]
                break
    if normalized.get("type") == "list" and "item_fields" not in normalized:
        nested_fields = normalized.get("fields")
        if isinstance(nested_fields, list):
            normalized["item_fields"] = _normalize_fields_aliases(nested_fields)
    return normalized


def _build_user_prompt(request: GenerateFormConfigRequest) -> str:
    return f"""表单名称：{request.form_name}

接口说明或字段说明：
{request.description}

请生成本项目可用的表单配置草稿，并把不确定项写入 warnings。
"""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"缺少环境变量：{name}")
    return value
