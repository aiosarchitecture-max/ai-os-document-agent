"""Safe classification for public Apps Script bridge diagnostics.

Only stable, non-sensitive codes leave this module. Raw URLs, credentials and
provider error messages must never be returned by the public status endpoint.
"""

def classify_bridge_error(detail: object) -> str:
    if isinstance(detail, dict):
        error = " ".join(str(detail.get(key, "")) for key in ("error", "message", "code"))
    else:
        error = str(detail)

    normalized = error.casefold()
    patterns = (
        ("apps script bridge is not configured", "bridge_not_configured"),
        ("bridge_not_configured", "bridge_not_configured"),
        ("bridge_http_error", "bridge_http_error"),
        ("bridge_invalid_response", "bridge_invalid_response"),
        ("bridge_upstream_error", "bridge_upstream_error"),
        ("bridge_transport_error", "bridge_transport_error"),
        ("bridge_timeout", "bridge_timeout"),
        ("bridge_auth_failed", "bridge_auth_failed"),
        ("bridge_secret_not_configured", "bridge_secret_not_configured"),
        ("root_not_configured", "root_not_configured"),
        ("drive_item_not_found", "drive_item_not_found"),
        ("workspace_permission_denied", "workspace_permission_denied"),
        ("bridge_invalid_request", "bridge_invalid_request"),
        ("apps_script_internal_error", "apps_script_internal_error"),
        ("unsupported action", "bridge_version_outdated"),
        ("outside ai_os root", "register_outside_root"),
        ("sheet not found", "sheet_not_found"),
        ("native google sheet", "register_not_native"),
        ("unauthorized", "bridge_auth_failed"),
        ("timed out", "bridge_timeout"),
        ("timeout", "bridge_timeout"),
        ("unsafe redirect", "bridge_unsafe_redirect"),
        ("apps script request failed", "bridge_transport_error"),
    )
    for needle, code in patterns:
        if needle in normalized:
            return code
    return "bridge_error"
