from __future__ import annotations

import os
import math
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.command_center.agent_runtime import (
    AgentRuntime,
    LegacyStructuredModelRuntime,
    RuntimeConfigurationError,
)


def _load_microsoft_runtime_class() -> type[Any]:
    from app.command_center.microsoft_agent_runtime import (
        MicrosoftAgentFrameworkRuntime,
    )

    return MicrosoftAgentFrameworkRuntime


def build_agent_runtime(
    model: Any,
    config_path: Path | None = None,
) -> AgentRuntime:
    runtime_name = os.getenv("COMMAND_CENTER_AGENT_RUNTIME", "legacy").strip().lower()
    if runtime_name == "legacy":
        return LegacyStructuredModelRuntime(model)
    if runtime_name != "microsoft":
        raise RuntimeConfigurationError(
            "COMMAND_CENTER_AGENT_RUNTIME must be legacy or microsoft"
        )

    path = config_path or Path(os.getenv("COMMAND_CENTER_AI_ENV_FILE", ".env.ai"))
    load_dotenv(path, override=True)
    base_url = _required_env("AI_CONFIG_MODEL_BASE_URL")
    model_name = _required_env("AI_CONFIG_MODEL_NAME")
    api_key = _required_env("AI_CONFIG_API_KEY")
    timeout_value = _required_env("AI_CONFIG_TIMEOUT_SECONDS")
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as exc:
        raise RuntimeConfigurationError(
            "AI_CONFIG_TIMEOUT_SECONDS must be a number"
        ) from exc
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise RuntimeConfigurationError(
            "AI_CONFIG_TIMEOUT_SECONDS must be a finite number greater than zero"
        )

    try:
        microsoft_runtime = _load_microsoft_runtime_class()
    except ImportError as exc:
        raise RuntimeConfigurationError(
            "microsoft runtime requires agent-framework-core==1.13.0 and "
            "agent-framework-openai==1.12.0"
        ) from exc

    return microsoft_runtime.from_openai_compatible(
        base_url=base_url,
        api_key=api_key,
        model=model_name,
        timeout_seconds=timeout_seconds,
    )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeConfigurationError(f"missing required configuration: {name}")
    return value
