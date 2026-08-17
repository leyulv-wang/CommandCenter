from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.command_center.schemas import SkillDefinition, SkillInput
from app.command_center.task_session_schemas import (
    FormInteraction,
    ParameterSource,
    QuestionInteraction,
)


MAX_CONVERSATIONAL_FIELDS = 2
_UNSUPPORTED_SCHEMA_KEYS = {"$ref", "oneOf", "anyOf", "allOf"}


class InputSchemaError(ValueError):
    pass


class InputCollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complete: bool
    values: dict[str, Any]
    sources: dict[str, ParameterSource]
    interaction: QuestionInteraction | FormInteraction | None = None


def collect_skill_inputs(
    skill: SkillDefinition,
    *,
    supplied: dict[str, Any],
    trusted_context: dict[str, Any],
) -> InputCollectionResult:
    definitions = {item.name: item for item in skill.inputs}
    unknown = set(supplied) - set(definitions)
    if unknown:
        raise InputSchemaError(f"unknown Skill inputs: {sorted(unknown)}")

    values: dict[str, Any] = {}
    sources: dict[str, ParameterSource] = {}
    for name, raw in supplied.items():
        values[name] = validate_input_value(definitions[name], raw)
        sources[name] = ParameterSource(kind="user_input", reference=name)

    for item in skill.inputs:
        if item.name in values or not item.source_hint:
            continue
        found, raw = resolve_data_path(trusted_context, item.source_hint)
        if found:
            values[item.name] = validate_input_value(item, raw)
            sources[item.name] = ParameterSource(
                kind="trusted_context", reference=item.source_hint
            )

    missing = [
        item for item in skill.inputs if item.required and item.name not in values
    ]
    if not missing:
        return InputCollectionResult(
            complete=True, values=values, sources=sources
        )

    complex_gap = len(missing) > MAX_CONVERSATIONAL_FIELDS or any(
        _requires_form(item) for item in missing
    )
    interaction: QuestionInteraction | FormInteraction
    if complex_gap:
        interaction = _build_form_interaction(missing, values)
    else:
        interaction = QuestionInteraction(
            prompt="；".join(item.description for item in missing),
            field_names=[item.name for item in missing],
        )
    return InputCollectionResult(
        complete=False,
        values=values,
        sources=sources,
        interaction=interaction,
    )


def resolve_data_path(data: Any, path: str) -> tuple[bool, Any]:
    value = data
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, list) and part.isdigit():
            index = int(part)
            if 0 <= index < len(value):
                value = value[index]
                continue
        return False, None
    return True, value


def validate_input_value(definition: SkillInput, value: Any) -> Any:
    schema = definition.json_schema or {"type": definition.type}
    _validate_schema_shape(schema)
    return _validate_value(schema, value, path=definition.name)


def _validate_schema_shape(schema: Any) -> None:
    if not isinstance(schema, dict):
        raise InputSchemaError("JSON Schema must be an object")
    unsupported = set(schema) & _UNSUPPORTED_SCHEMA_KEYS
    if unsupported:
        raise InputSchemaError(
            f"unsupported JSON Schema constructs: {sorted(unsupported)}"
        )
    schema_type = schema.get("type")
    if schema_type not in {"object", "array", "string", "number", "integer", "boolean"}:
        raise InputSchemaError(f"unsupported JSON Schema type: {schema_type}")
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise InputSchemaError("object properties must be an object")
        for child in properties.values():
            _validate_schema_shape(child)
    if schema_type == "array":
        if "items" not in schema:
            raise InputSchemaError("array json_schema requires items")
        _validate_schema_shape(schema["items"])


def _validate_value(schema: dict[str, Any], value: Any, *, path: str) -> Any:
    if "enum" in schema and value not in schema["enum"]:
        raise InputSchemaError(f"{path} is not one of the allowed values")
    schema_type = schema["type"]
    if schema_type == "string":
        if not isinstance(value, str):
            raise InputSchemaError(f"{path} must be a string")
        format_name = schema.get("format")
        try:
            if format_name == "date":
                date.fromisoformat(value)
            elif format_name == "date-time":
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif format_name is not None:
                raise InputSchemaError(f"unsupported string format: {format_name}")
        except ValueError as exc:
            raise InputSchemaError(f"{path} has invalid {format_name} format") from exc
        return value
    if schema_type == "boolean":
        if not isinstance(value, bool):
            raise InputSchemaError(f"{path} must be a boolean")
        return value
    if schema_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InputSchemaError(f"{path} must be an integer")
        return value
    if schema_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputSchemaError(f"{path} must be a number")
        return value
    if schema_type == "array":
        if not isinstance(value, list):
            raise InputSchemaError(f"{path} must be an array")
        return [
            _validate_value(schema["items"], item, path=f"{path}.{index}")
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        raise InputSchemaError(f"{path} must be an object")
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    missing = required - set(value)
    if missing:
        raise InputSchemaError(f"{path} is missing required fields: {sorted(missing)}")
    unknown = set(value) - set(properties)
    if unknown:
        raise InputSchemaError(f"{path} has unknown fields: {sorted(unknown)}")
    return {
        name: _validate_value(properties[name], item, path=f"{path}.{name}")
        for name, item in value.items()
    }


def _requires_form(item: SkillInput) -> bool:
    if item.type in {"array", "object"}:
        if item.json_schema is None:
            raise InputSchemaError(
                f"complex Skill input {item.name} requires json_schema"
            )
        _validate_schema_shape(item.json_schema)
        return True
    schema = item.json_schema or {"type": item.type}
    _validate_schema_shape(schema)
    return bool(schema.get("enum") or schema.get("format") in {"date", "date-time"})


def _build_form_interaction(
    missing: list[SkillInput], values: dict[str, Any]
) -> FormInteraction:
    properties: dict[str, Any] = {}
    for item in missing:
        schema = dict(item.json_schema or {"type": item.type})
        _validate_schema_shape(schema)
        schema.setdefault("title", item.description)
        properties[item.name] = schema
    return FormInteraction.model_validate(
        {
            "type": "form",
            "title": "请补充任务信息",
            "schema": {
                "type": "object",
                "properties": properties,
                "required": [item.name for item in missing if item.required],
            },
            "values": values,
        }
    )
