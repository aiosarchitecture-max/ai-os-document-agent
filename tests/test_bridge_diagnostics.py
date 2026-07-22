import pytest

from app.bridge_diagnostics import classify_bridge_error


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("Apps Script bridge is not configured", "bridge_not_configured"),
        ({"code": "bridge_not_configured"}, "bridge_not_configured"),
        ({"code": "bridge_http_error"}, "bridge_http_error"),
        ({"code": "bridge_invalid_response"}, "bridge_invalid_response"),
        ({"code": "bridge_upstream_error"}, "bridge_upstream_error"),
        ({"code": "bridge_transport_error"}, "bridge_transport_error"),
        ({"code": "bridge_timeout"}, "bridge_timeout"),
        ({"code": "bridge_auth_failed"}, "bridge_auth_failed"),
        ({"code": "bridge_secret_not_configured"}, "bridge_secret_not_configured"),
        ({"code": "root_not_configured"}, "root_not_configured"),
        ({"code": "drive_item_not_found"}, "drive_item_not_found"),
        ({"code": "workspace_permission_denied"}, "workspace_permission_denied"),
        ({"code": "bridge_invalid_request"}, "bridge_invalid_request"),
        ({"code": "apps_script_internal_error"}, "apps_script_internal_error"),
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
