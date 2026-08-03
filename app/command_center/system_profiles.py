"""Typed, static boundaries for externally observed systems."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator


class ProfileLimits(BaseModel):
    """Bounded resource settings for requests made through a system profile."""

    model_config = ConfigDict(extra="forbid")

    request_timeout_seconds: int
    max_response_bytes: int
    max_requests_per_minute: int


class ToolPermission(BaseModel):
    """Permission for one exact API operation."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    path: str
    side_effect: Literal["read", "write"]

    @field_validator("path")
    @classmethod
    def exact_path_only(cls, value: str) -> str:
        if not value.startswith("/") or "*" in value:
            raise ValueError("tool permission must use an exact absolute path")
        return value


class SystemProfile(BaseModel):
    """Trusted configuration that bounds an external system's Tools."""

    model_config = ConfigDict(extra="forbid")

    system_code: str
    display_name: str
    allowed_hosts: set[str]
    openapi_url: HttpUrl
    base_url: HttpUrl
    api_path_prefix: str
    credential_header: Literal["X-Access-Token"]
    limits: ProfileLimits
    value_capture_policy: Literal["fingerprint_by_default"]
    sensitive_field_patterns: list[str]
    tool_permissions: list[ToolPermission]

    def permission_for(self, method: str, path: str) -> ToolPermission | None:
        return next(
            (
                item
                for item in self.tool_permissions
                if item.method == method.upper() and item.path == path
            ),
            None,
        )

    def is_allowed(self, method: str, path: str) -> bool:
        return self.permission_for(method, path) is not None


def load_system_profile(path: Path) -> SystemProfile:
    """Load and validate one trusted JSON system profile."""

    return SystemProfile.model_validate_json(path.read_text(encoding="utf-8"))
