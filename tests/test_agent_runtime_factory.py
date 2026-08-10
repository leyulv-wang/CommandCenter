import pytest

from app.command_center.agent_runtime import (
    LegacyStructuredModelRuntime,
    RuntimeConfigurationError,
)
from app.command_center.agent_runtime_factory import build_agent_runtime


def test_runtime_factory_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("COMMAND_CENTER_AGENT_RUNTIME", raising=False)
    runtime = build_agent_runtime(model=object())
    assert isinstance(runtime, LegacyStructuredModelRuntime)


def test_runtime_factory_rejects_unknown_name(monkeypatch):
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "other")
    with pytest.raises(RuntimeConfigurationError, match="legacy or microsoft"):
        build_agent_runtime(model=object())


def test_microsoft_runtime_maps_existing_ai_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=http://provider/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=SECRET-KEY\n"
        "AI_CONFIG_TIMEOUT_SECONDS=12.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "microsoft")
    for name in (
        "AI_CONFIG_MODEL_BASE_URL",
        "AI_CONFIG_MODEL_NAME",
        "AI_CONFIG_API_KEY",
        "AI_CONFIG_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    captured = {}

    class FakeMicrosoftRuntime:
        @classmethod
        def from_openai_compatible(cls, **kwargs):
            captured.update(kwargs)
            return cls()

    monkeypatch.setattr(
        "app.command_center.agent_runtime_factory._load_microsoft_runtime_class",
        lambda: FakeMicrosoftRuntime,
    )
    runtime = build_agent_runtime(model=object(), config_path=env_file)
    assert isinstance(runtime, FakeMicrosoftRuntime)
    assert captured == {
        "base_url": "http://provider/v1",
        "model": "test-model",
        "api_key": "SECRET-KEY",
        "timeout_seconds": 12.5,
    }
    assert "SECRET-KEY" not in repr(runtime)


def test_microsoft_runtime_requires_provider_values(monkeypatch, tmp_path):
    env_file = tmp_path / ".env.ai"
    env_file.write_text("AI_CONFIG_MODEL_NAME=test-model\n", encoding="utf-8")
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "microsoft")
    for name in (
        "AI_CONFIG_MODEL_BASE_URL",
        "AI_CONFIG_API_KEY",
        "AI_CONFIG_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeConfigurationError, match="AI_CONFIG_MODEL_BASE_URL"):
        build_agent_runtime(model=object(), config_path=env_file)


def test_microsoft_runtime_translates_optional_dependency_import_error(
    monkeypatch, tmp_path
):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=http://provider/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=test-key\n"
        "AI_CONFIG_TIMEOUT_SECONDS=12.5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "microsoft")

    def missing_framework():
        raise ImportError("agent_framework")

    monkeypatch.setattr(
        "app.command_center.agent_runtime_factory._load_microsoft_runtime_class",
        missing_framework,
    )
    with pytest.raises(
        RuntimeConfigurationError,
        match="agent-framework-core==1.13.0.*agent-framework-openai==1.12.0",
    ):
        build_agent_runtime(model=object(), config_path=env_file)


def test_legacy_does_not_require_provider_values(monkeypatch, tmp_path):
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "legacy")
    missing = tmp_path / "missing.env.ai"
    assert isinstance(
        build_agent_runtime(model=object(), config_path=missing),
        LegacyStructuredModelRuntime,
    )


@pytest.mark.parametrize("timeout_value", ["0", "-1", "nan", "inf", "-inf"])
def test_microsoft_runtime_rejects_non_positive_or_non_finite_timeout(
    monkeypatch, tmp_path, timeout_value
):
    env_file = tmp_path / ".env.ai"
    env_file.write_text(
        "AI_CONFIG_MODEL_BASE_URL=http://provider/v1\n"
        "AI_CONFIG_MODEL_NAME=test-model\n"
        "AI_CONFIG_API_KEY=test-key\n"
        f"AI_CONFIG_TIMEOUT_SECONDS={timeout_value}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COMMAND_CENTER_AGENT_RUNTIME", "microsoft")
    for name in (
        "AI_CONFIG_MODEL_BASE_URL",
        "AI_CONFIG_MODEL_NAME",
        "AI_CONFIG_API_KEY",
        "AI_CONFIG_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(
        RuntimeConfigurationError, match="finite number greater than zero"
    ):
        build_agent_runtime(model=object(), config_path=env_file)
