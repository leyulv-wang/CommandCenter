import pytest

from app.command_center.redaction import TraceRedactor


def test_redactor_removes_credentials_and_fingerprints_sensitive_values():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    assert redactor.redact_headers(
        {"X-Access-Token": "secret", "Content-Type": "application/json"}
    ) == {"Content-Type": "application/json"}
    assert redactor.redact_payload(
        {"password": "pw", "supplierName": "江苏测试公司"},
        sensitive_paths={"supplierName"},
    ) == {
        "password": "[REDACTED]",
        "supplierName": {"fingerprint": redactor.fingerprint("江苏测试公司")},
    }


def test_redactor_recursively_sanitizes_generic_structures_case_insensitively():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    result = redactor.redact_payload(
        {
            "query": {"Captcha": "answer", "page": 2},
            "body": {
                "PASSWORD": "pw",
                "nested": [
                    {"authorization": "Bearer token"},
                    {"fileContents": "private bytes"},
                    {"LOCAL_STORAGE": {"session": "private"}},
                ],
            },
            "cookie": "session=private",
        }
    )

    assert result == {
        "query": {"Captcha": "[REDACTED]", "page": 2},
        "body": {
            "PASSWORD": "[REDACTED]",
            "nested": [
                {"authorization": "[REDACTED]"},
                {"fileContents": "[REDACTED]"},
                {"LOCAL_STORAGE": "[REDACTED]"},
            ],
        },
        "cookie": "[REDACTED]",
    }


def test_redactor_sanitizes_sensitive_key_variants():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    assert redactor.redact_payload(
        {
            "newPassword": "secret",
            "captchaCode": "secret",
            "file_content_base64": "secret",
            "local-storage-state": "secret",
            "cookieJar": "secret",
            "xAccessTokenValue": "secret",
        }
    ) == {
        "newPassword": "[REDACTED]",
        "captchaCode": "[REDACTED]",
        "file_content_base64": "[REDACTED]",
        "local-storage-state": "[REDACTED]",
        "cookieJar": "[REDACTED]",
        "xAccessTokenValue": "[REDACTED]",
    }


def test_redactor_removes_all_sensitive_headers_case_insensitively():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    assert redactor.redact_headers(
        {
            "authorization": "Bearer secret",
            "COOKIE": "session=secret",
            "Set-Cookie": "session=secret",
            "x-ACCESS-token": "secret",
            "Accept": "application/json",
        }
    ) == {"Accept": "application/json"}


def test_redactor_applies_profile_limits_without_exposing_rejected_values():
    redactor = TraceRedactor(
        fingerprint_key=b"test-key",
        max_depth=2,
        max_array_items=2,
        max_string_length=4,
    )

    assert redactor.redact_payload(
        {"items": ["abcdef", "ghijkl", "discarded-secret"]}
    ) == {"items": ["abcd", "ghij"]}

    with pytest.raises(ValueError) as error:
        redactor.redact_payload({"outer": {"inner": {"value": "never-log-me"}}})

    assert "never-log-me" not in str(error.value)


def test_fingerprint_is_stable_keyed_and_does_not_contain_plaintext():
    first = TraceRedactor(fingerprint_key=b"first-key")
    same_key = TraceRedactor(fingerprint_key=b"first-key")
    other_key = TraceRedactor(fingerprint_key=b"other-key")

    fingerprint = first.fingerprint("sensitive-value")

    assert fingerprint == same_key.fingerprint("sensitive-value")
    assert fingerprint != first.fingerprint("different-value")
    assert fingerprint != other_key.fingerprint("sensitive-value")
    assert "sensitive-value" not in fingerprint
