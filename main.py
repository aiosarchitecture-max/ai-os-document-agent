import base64
import datetime as dt
import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


APP_NAME = "AI_OS_DOCUMENT_AGENT_V0_1"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

app = FastAPI(title=APP_NAME, version="0.1.0")


class WriteRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise HTTPException(status_code=500, detail=f"Missing environment variable: {name}")
    return value


def _check_token(request: Request) -> None:
    expected = os.getenv("API_TOKEN")
    if not expected:
        raise HTTPException(status_code=500, detail="Missing environment variable: API_TOKEN")

    supplied = request.headers.get("x-ai-os-token") or request.query_params.get("token")
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _service_account_info() -> dict:
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    b64_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON_B64")

    if b64_json:
        try:
            return json.loads(base64.b64decode(b64_json).decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Invalid GOOGLE_SERVICE_ACCOUNT_JSON_B64: {exc}")

    if raw_json:
        try:
            return json.loads(raw_json)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Invalid GOOGLE_SERVICE_ACCOUNT_JSON: {exc}")

    raise HTTPException(
        status_code=500,
        detail="Missing GOOGLE_SERVICE_ACCOUNT_JSON_B64 or GOOGLE_SERVICE_ACCOUNT_JSON",
    )


def _credentials():
    info = _service_account_info()
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


def _drive():
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def _docs():
    return build("docs", "v1", credentials=_credentials(), cache_discovery=False)


def _sheets():
    return build("sheets", "v4", credentials=_credentials(), cache_discovery=False)


def _root_folder_id() -> str:
    return _require_env("AI_OS_ROOT_FOLDER_ID")


def _now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_query_string(value: str) -> str:
    return value.replace("'", "\\'")


def _find_change_log_sheet(drive_service) -> Optional[dict]:
    root_id = _root_folder_id()
    q = (
        f"'{_safe_query_string(root_id)}' in parents and "
        "mimeType='application/vnd.google-apps.spreadsheet' and "
        "name='AI_OS_CHANGE_LOG' and trashed=false"
    )
    result = drive_service.files().list(
        q=q,
        fields="files(id,name,webViewLink)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = result.get("files", [])
    return files[0] if files else None


def _create_change_log_sheet(drive_service, sheets_service) -> dict:
    root_id = _root_folder_id()
    file_metadata = {
        "name": "AI_OS_CHANGE_LOG",
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [root_id],
    }
    created = drive_service.files().create(
        body=file_metadata,
        fields="id,name,webViewLink",
        supportsAllDrives=True,
    ).execute()

    headers = [[
        "timestamp_utc",
        "agent",
        "action",
        "target_document",
        "target_document_id",
        "status",
        "note",
        "link",
    ]]

    sheets_service.spreadsheets().values().update(
        spreadsheetId=created["id"],
        range="A1:H1",
        valueInputOption="RAW",
        body={"values": headers},
    ).execute()
    return created


def _get_or_create_change_log(drive_service, sheets_service) -> dict:
    existing = _find_change_log_sheet(drive_service)
    if existing:
        return existing
    return _create_change_log_sheet(drive_service, sheets_service)


def _append_change_log_row(
    sheets_service,
    spreadsheet_id: str,
    action: str,
    target_document: str,
    target_document_id: str,
    status: str,
    note: str,
    link: str,
) -> None:
    values = [[
        _now_iso(),
        APP_NAME,
        action,
        target_document,
        target_document_id,
        status,
        note,
        link,
    ]]
    sheets_service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range="A:H",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()


def _create_google_doc(title: str, content: str) -> dict:
    root_id = _root_folder_id()
    drive_service = _drive()
    docs_service = _docs()
    sheets_service = _sheets()

    metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [root_id],
    }

    file = drive_service.files().create(
        body=metadata,
        fields="id,name,webViewLink",
        supportsAllDrives=True,
    ).execute()

    document_id = file["id"]

    docs_service.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text": content,
                    }
                }
            ]
        },
    ).execute()

    change_log = _get_or_create_change_log(drive_service, sheets_service)
    _append_change_log_row(
        sheets_service=sheets_service,
        spreadsheet_id=change_log["id"],
        action="CREATE_TEST_DOCUMENT",
        target_document=file["name"],
        target_document_id=document_id,
        status="SUCCESS",
        note="Document Agent v0.1 test write.",
        link=file.get("webViewLink", ""),
    )

    return {
        "document_id": document_id,
        "document_name": file["name"],
        "document_url": file.get("webViewLink"),
        "change_log_id": change_log["id"],
        "change_log_url": change_log.get("webViewLink"),
    }


@app.get("/")
def root():
    return {
        "service": APP_NAME,
        "status": "running",
        "message": "AI OS Document Agent v0.1 is online.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": APP_NAME,
        "time_utc": _now_iso(),
    }


@app.get("/root-check")
def root_check(request: Request):
    _check_token(request)
    try:
        drive_service = _drive()
        root_id = _root_folder_id()

        result = drive_service.files().list(
            q=f"'{_safe_query_string(root_id)}' in parents and trashed=false",
            fields="files(id,name,mimeType,webViewLink)",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        return {
            "status": "success",
            "root_folder_id": root_id,
            "items": result.get("files", []),
        }
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/test-write")
def test_write_get(request: Request):
    _check_token(request)
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    title = f"AI_OS_SYSTEM_TEST_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    content = (
        "AI_OS_SYSTEM_TEST\n\n"
        f"Created by: {APP_NAME}\n"
        f"Created at: {timestamp}\n\n"
        "Result: Google Drive + Google Docs + Google Sheets integration works.\n"
    )

    try:
        result = _create_google_doc(title=title, content=content)
        return {"status": "success", **result}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/test-write")
async def test_write_post(request: Request, payload: WriteRequest):
    _check_token(request)
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    title = payload.title or f"AI_OS_SYSTEM_TEST_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    content = payload.content or (
        "AI_OS_SYSTEM_TEST\n\n"
        f"Created by: {APP_NAME}\n"
        f"Created at: {timestamp}\n\n"
        "Result: Google Drive + Google Docs + Google Sheets integration works.\n"
    )

    try:
        result = _create_google_doc(title=title, content=content)
        return {"status": "success", **result}
    except HttpError as exc:
        raise HTTPException(status_code=500, detail=str(exc))