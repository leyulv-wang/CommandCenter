from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError


SchemaT = TypeVar("SchemaT", bound=BaseModel)
Completion = Callable[[list[dict[str, str]]], str]


class StructuredModel:
    def __init__(self, completion: Completion):
        self._completion = completion

    @classmethod
    def from_environment(cls, config_path: Path | None = None) -> StructuredModel:
        path = config_path or Path(os.getenv("COMMAND_CENTER_AI_ENV_FILE", ".env.ai"))
        load_dotenv(path, override=True)
        base_url = _required_env("AI_CONFIG_MODEL_BASE_URL")
        api_key = _required_env("AI_CONFIG_API_KEY")
        model_name = _required_env("AI_CONFIG_MODEL_NAME")
        timeout = float(os.getenv("AI_CONFIG_TIMEOUT_SECONDS", "60"))
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)

        def complete(messages: list[dict[str, str]]) -> str:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("模型没有返回内容")
            return content

        return cls(complete)

    def generate(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        payload: Any,
    ) -> SchemaT:
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n只输出 JSON。输出必须符合以下 JSON Schema：\n"
                    f"{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(_jsonable(payload), ensure_ascii=False),
            },
        ]
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return schema.model_validate_json(self._completion(messages))
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": f"上一次输出校验失败：{exc}。请只返回修正后的 JSON。",
                        }
                    )
        raise ValueError(f"模型结构化输出连续两次校验失败：{last_error}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"缺少环境变量：{name}")
    return value
