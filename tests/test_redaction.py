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


def test_redactor_sanitizes_sensitive_keys_split_across_recursive_paths():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    assert redactor.redact_payload(
        {
            "x": {"access": {"token": "secret"}},
            "local": {"storage": {"session": "secret"}},
            "file": {"content": "secret"},
        }
    ) == {
        "x": {"access": {"token": "[REDACTED]"}},
        "local": {"storage": "[REDACTED]"},
        "file": {"content": "[REDACTED]"},
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
        {"data": ["abcdef", "ghijkl", "discarded-secret"]}
    ) == {"data": ["abcd", "ghij"]}

    with pytest.raises(ValueError) as error:
        redactor.redact_payload({"outer": {"inner": {"value": "never-log-me"}}})

    assert "never-log-me" not in str(error.value)


def test_redactor_accepts_mapping_at_configured_item_limit():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_mapping_items=2)

    assert redactor.redact_payload({"a": 1, "b": 2}) == {"a": 1, "b": 2}
    assert redactor.redact_headers({"A": "1", "B": "2"}) == {"A": "1", "B": "2"}


def test_redactor_rejects_mapping_over_configured_item_limit():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_mapping_items=1)

    with pytest.raises(ValueError) as error:
        redactor.redact_payload({"first": "private-one", "second": "private-two"})

    assert str(error.value) == "mapping exceeds configured maximum items"


def test_redactor_rejects_header_mapping_over_configured_item_limit():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_mapping_items=1)

    with pytest.raises(ValueError) as error:
        redactor.redact_headers(
            {"Authorization": "private-token", "Accept": "application/json"}
        )

    assert str(error.value) == "mapping exceeds configured maximum items"


def test_redactor_rejects_oversized_mapping_keys_without_echoing_them():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_string_length=4)
    oversized_key = "private-key-name"

    with pytest.raises(ValueError) as error:
        redactor.redact_payload({oversized_key: "value"})

    assert oversized_key not in str(error.value)


def test_redactor_rejects_non_string_mapping_keys_without_echoing_them():
    redactor = TraceRedactor(fingerprint_key=b"test-key")

    with pytest.raises(TypeError) as error:
        redactor.redact_payload({42: "value"})

    assert "42" not in str(error.value)


def test_redactor_bounds_sensitive_value_before_hmac():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_string_length=4)

    assert redactor.redact_payload(
        {"name": "sensitive-value"},
        sensitive_paths={"name"},
    ) == {"name": {"fingerprint": redactor.fingerprint("sens")}}
    assert redactor.fingerprint("sensitive-value") == redactor.fingerprint("sens")


def test_redactor_rejects_oversized_sensitive_path_segments_without_echoing_them():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_string_length=4)
    oversized_path = "root.private-segment"

    with pytest.raises(ValueError) as error:
        redactor.redact_payload({}, sensitive_paths={oversized_path})

    assert oversized_path not in str(error.value)


def test_redactor_rejects_sensitive_paths_deeper_than_profile_without_echoing_them():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_depth=2)
    deep_path = "one.two.three"

    with pytest.raises(ValueError) as error:
        redactor.redact_payload({}, sensitive_paths={deep_path})

    assert deep_path not in str(error.value)


def test_redactor_accepts_sensitive_paths_at_configured_item_limit():
    redactor = TraceRedactor(fingerprint_key=b"test-key", max_sensitive_paths=2)

    assert redactor.redact_payload(
        {"a": "one", "b": "two"},
        sensitive_paths={"a", "b"},
    ) == {
        "a": {"fingerprint": redactor.fingerprint("one")},
        "b": {"fingerprint": redactor.fingerprint("two")},
    }


def test_redactor_rejects_sensitive_paths_over_limit_before_normalizing_them():
    redactor = TraceRedactor(
        fingerprint_key=b"test-key",
        max_sensitive_paths=1,
        max_string_length=4,
    )

    with pytest.raises(ValueError) as error:
        redactor.redact_payload(
            {},
            sensitive_paths={"a", "private-segment"},
        )

    assert str(error.value) == "sensitive paths exceed configured maximum items"


@pytest.mark.parametrize(
    "limit_name",
    [
        "max_depth",
        "max_array_items",
        "max_mapping_items",
        "max_sensitive_paths",
        "max_string_length",
    ],
)
@pytest.mark.parametrize("invalid_value", [0, -1, True, "1"])
def test_redactor_rejects_non_positive_or_non_integer_profile_limits(
    limit_name,
    invalid_value,
):
    with pytest.raises(ValueError) as error:
        TraceRedactor(
            fingerprint_key=b"test-key",
            **{limit_name: invalid_value},
        )

    assert str(error.value) == "redaction limits must be positive integers"


def test_fingerprint_is_stable_keyed_and_does_not_contain_plaintext():
    first = TraceRedactor(fingerprint_key=b"first-key")
    same_key = TraceRedactor(fingerprint_key=b"first-key")
    other_key = TraceRedactor(fingerprint_key=b"other-key")

    fingerprint = first.fingerprint("sensitive-value")

    assert fingerprint == same_key.fingerprint("sensitive-value")
    assert fingerprint != first.fingerprint("different-value")
    assert fingerprint != other_key.fingerprint("sensitive-value")
    assert "sensitive-value" not in fingerprint
