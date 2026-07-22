import pytest

from app.bridge_diagnostics import classify_bridge_error


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("Apps Script bridge is not configured", "bridge_not_configured"),
        ({"code": "bridge_not_configured"}, "bridge_not_configured"),
        ("Unsupported action READ_SHEET_ROWS", "bridge_version_outdated"),
        ("File is outside AI_OS root", "register_outside_root"),
        ("Sheet not found", "sheet_not_found"),
        ("Register must be a native Google Sheet", "register_not_native"),
        ("Unauthorized", "bridge_auth_failed"),
        ({"error": "UNAUTHORIZED"}, "bridge_auth_failed"),
        ("Request timed out", "bridge_timeout"),
        ("Apps Script returned an unsafe redirect", "bridge_unsafe_redirect"),
        ("Apps Script request failed: HTTP 500", "bridge_transport_error"),
        ({"message": "unexpected provider failure"}, "bridge_error"),
    ],
)
def test_classify_bridge_error(detail, expected):
    assert classify_bridge_error(detail) == expected


def test_classifier_never_returns_raw_sensitive_detail():
    secret_bearing = "unexpected token super-secret-value"
    result = classify_bridge_error(secret_bearing)
    assert result == "bridge_error"
    assert "secret" not in result
