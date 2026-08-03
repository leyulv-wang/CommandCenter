from pathlib import Path
import re

import pytest
from pydantic import ValidationError

from app.command_center.system_profiles import SystemProfile, load_system_profile


def valid_profile_payload() -> dict[str, object]:
    return {
        "system_code": "yifeng_mes",
        "display_name": "益丰 MES",
        "allowed_hosts": ["yifeng.dtsum.com"],
        "openapi_url": "http://yifeng.dtsum.com/jeecg-boot/v2/api-docs",
        "base_url": "http://yifeng.dtsum.com",
        "api_path_prefix": "/jeecg-boot/",
        "credential_header": "X-Access-Token",
        "limits": {
            "request_timeout_seconds": 10,
            "max_response_bytes": 1_048_576,
            "max_requests_per_minute": 30,
        },
        "value_capture_policy": "fingerprint_by_default",
        "sensitive_field_patterns": ["password", "token"],
        "tool_permissions": [
            {
                "method": "GET",
                "path": "/jeecg-boot/purchase/apply/list",
                "side_effect": "read",
            }
        ],
    }


def test_yifeng_profile_only_allows_three_read_operations():
    profile = load_system_profile(Path("app/data/system_profiles/yifeng_mes.json"))

    assert profile.system_code == "yifeng_mes"
    assert profile.allowed_hosts == {"yifeng.dtsum.com"}
    assert profile.permission_for(
        "GET", "/jeecg-boot/purchase/apply/list"
    ).side_effect == "read"
    assert {
        (permission.method, permission.path, permission.side_effect)
        for permission in profile.tool_permissions
    } == {
        ("GET", "/jeecg-boot/purchase/apply/list", "read"),
        ("GET", "/jeecg-boot/purchase/apply/queryById", "read"),
        (
            "GET",
            "/jeecg-boot/purchase/apply/queryPurchaseApplyDetailByMainId",
            "read",
        ),
    }
    assert profile.permission_for("GET", "/jeecg-boot/purchase/apply/audit") is None
    assert profile.permission_for("POST", "/jeecg-boot/purchase/apply/add") is None
    assert any(
        re.search(pattern, "captchaCode")
        for pattern in profile.sensitive_field_patterns
    )


def test_profile_rejects_wildcard_permissions():
    payload = valid_profile_payload()
    payload["tool_permissions"] = [
        {"method": "GET", "path": "/jeecg-boot/*", "side_effect": "read"}
    ]

    with pytest.raises(ValidationError):
        SystemProfile.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("request_timeout_seconds", 0),
        ("max_response_bytes", -1),
        ("max_requests_per_minute", "30"),
    ],
)
def test_profile_rejects_non_positive_or_coerced_limits(
    field_name: str, invalid_value: object
):
    payload = valid_profile_payload()
    payload["limits"][field_name] = invalid_value

    with pytest.raises(ValidationError):
        SystemProfile.model_validate(payload)
