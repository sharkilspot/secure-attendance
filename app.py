# app.py
import os
import json
import time
import uuid
import secrets
from typing import Dict, Tuple, List

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI(title="Secure Attendance API")

# ----------------------------
# CORS
# ----------------------------
def _env_list(name: str) -> List[str]:
    val = os.getenv(name, "").strip()
    return [x.strip() for x in val.split(",") if x.strip()] if val else []

EXTRA_ORIGINS = _env_list("FRONTEND_ORIGINS")
ALLOW_ORIGINS = ["https://sfc.vuejs.org", "https://play.vuejs.org", *EXTRA_ORIGINS]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,                               # explicit list
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*vuejs\.org$", # any subdomain of vuejs.org
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,  # no cookies needed; simpler CORS
)

# ----------------------------
# Config & token store
# ----------------------------
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "10"))  # default 10s
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # must be set
TOKENS: Dict[str, Tuple[float, str]] = {}  # token -> (expires_at, session_id)
CURRENT_SESSION_ID = uuid.uuid4().hex      # new session on server start

def _now() -> float:
    return time.time()

def _clean_expired():
    now = _now()
    for t, (exp, _) in list(TOKENS.items()):
        if exp < now:
            TOKENS.pop(t, None)

# ----------------------------
# Google Sheets helpers
# ----------------------------
def get_gsheet_client():
    raw = os.getenv("GS_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GS_CREDENTIALS_JSON is not set!")
    creds_dict = json.loads(raw)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_attendance_sheet():
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID is not set!")
    client = get_gsheet_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    try:
        ws = ss.worksheet("Attendance")
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title="Attendance", rows=2000, cols=12)
        ws.append_row([
            "timestamp_epoch", "timestamp_iso", "session_id",
            "token_tail", "student_id", "status", "client_ip", "user_agent"
        ])
    return ws

def append_attendance_row(session_id: str, token: str, student_id: str, request: Request):
    ws = get_attendance_sheet()
    ts = int(_now())
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    token_tail = token[-6:]
    client_ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")
    ws.append_row([ts, iso, session_id, token_tail, student_id.strip(), "OK", client_ip, user_agent])

# ----------------------------
# Routes
# ----------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True, "ttl": TOKEN_TTL_SECONDS, "session_id": CURRENT_SESSION_ID}

@app.post("/session/start")
def start_session():
    """Teacher starts a fresh attendance session."""
    global CURRENT_SESSION_ID
    CURRENT_SESSION_ID = uuid.uuid4().hex
    return {"session_id": CURRENT_SESSION_ID}

@app.get("/")
def home():
    return {"message": "Secure Attendance API is running", "session_id": CURRENT_SESSION_ID}

@app.get("/generate")
def generate():
    """
    Issue a short-lived, one-time token for the current session.
    Frontend encodes it into /scan/{token}.
    """
    _clean_expired()
    token = secrets.token_urlsafe(24)
    expires_at = _now() + TOKEN_TTL_SECONDS
    TOKENS[token] = (expires_at, CURRENT_SESSION_ID)
    return {"token": token, "expires_in": TOKEN_TTL_SECONDS, "session_id": CURRENT_SESSION_ID}

@app.get("/scan/{token}", response_class=HTMLResponse)
def scan_page(token: str):
    """
    Student lands here after scanning the QR. Simple HTML form posts to /check-in.
    """
    _clean_expired()
    info = TOKENS.get(token)
    if not info:
        return HTMLResponse("<h2>Token invalid or expired.</h2>", status_code=401)

    expires_at, session_id = info
    seconds_left = max(0, int(expires_at - _now()))
    html = f"""
    <!doctype html>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Attendance Check-In</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 2rem; }}
      .card {{ max-width: 520px; margin: 0 auto; padding: 1.25rem; border: 1px solid #e5e7eb; border-radius: .75rem; }}
      label {{ display:block; margin-bottom: .5rem; font-weight: 600; }}
      input, button {{ width: 100%; padding: .75rem; margin-top: .25rem; }}
      button {{ background: #2563eb; color: white; border: 0; border-radius: .5rem; cursor: pointer; }}
      .muted {{ color: #6b7280; font-size: .875rem; margin-top: .5rem; }}
    </style>
    <div class="card">
      <h2>Attendance Check-In</h2>
      <form method="POST" action="/check-in">
        <input type="hidden" name="token" value="{token}">
        <label>Student ID (NIM)
          <input name="student_id" required placeholder="e.g. 2103xxxx">
        </label>
        <button type="submit">Check In</button>
        <p class="muted">Session: {session_id[:8]}… · Token expires in ~{seconds_left}s</p>
      </form>
    </div>
    """
    return HTMLResponse(content=html, status_code=200)

@app.post("/check-in")
async def check_in(request: Request, token: str = Form(...), student_id: str = Form(...)):
    """
    Validate token, log attendance to Google Sheets, and consume the token (one-time).
    """
    _clean_expired()
    info = TOKENS.get(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    expires_at, session_id = info
    if _now() > expires_at:
        TOKENS.pop(token, None)
        raise HTTPException(status_code=401, detail="Token expired")

    # Consume token first to prevent double submission
    TOKENS.pop(token, None)

    try:
        append_attendance_row(session_id=session_id, token=token, student_id=student_id, request=request)
    except Exception as e:
        # Surface error (e.g., bad credentials, missing permissions)
        raise HTTPException(status_code=500, detail=f"Logging failed: {e}")

    return HTMLResponse(
        content=f"<h2>Check-in successful for {student_id} ✅</h2><p>Session {session_id[:8]}…</p>",
        status_code=200
    )

# Optional: keep /validate if you still want a JSON validator endpoint
@app.get("/validate/{token}")
def validate(token: str, consume: bool = True):
    _clean_expired()
    info = TOKENS.get(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    expires_at, session_id = info
    if consume:
        TOKENS.pop(token, None)
    return {"status": "success", "session_id": session_id, "token": token, "expires_at": int(expires_at)}

# Diagnostics: quick check that Sheets is reachable and tab exists
@app.get("/test-sheet")
def test_sheet():
    try:
        ws = get_attendance_sheet()
        return {"title": ws.title, "header": ws.row_values(1)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
