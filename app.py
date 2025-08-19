# app.py (additions/replacements)
import os
import time
import secrets
import uuid
from typing import Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI(title="Secure Attendance API")

# ---------- CORS (as you already fixed) ----------
def _env_list(name: str) -> List[str]:
    val = os.getenv(name, "").strip()
    return [x.strip() for x in val.split(",") if x.strip()] if val else []

EXTRA_ORIGINS = _env_list("FRONTEND_ORIGINS")
ALLOW_ORIGINS = ["https://sfc.vuejs.org", "https://play.vuejs.org", *EXTRA_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*vuejs\.org$",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ---------- Token & Session ----------
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "5"))
TOKENS: Dict[str, Tuple[float, str]] = {}  # token -> (expires_at, session_id)
CURRENT_SESSION_ID = uuid.uuid4().hex  # new session on server start

def _now() -> float:
    return time.time()

def _clean_expired():
    now = _now()
    for t, (exp, _) in list(TOKENS.items()):
        if exp < now:
            TOKENS.pop(t, None)

# ---------- Google Sheets ----------
def get_env_var(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Environment variable {name} is not set!")
    return v

def get_gsheet_client():
    creds_dict = {
        "type": get_env_var("GS_TYPE"),
        "project_id": get_env_var("GS_PROJECT_ID"),
        "private_key_id": get_env_var("GS_PRIVATE_KEY_ID"),
        "private_key": get_env_var("GS_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": get_env_var("GS_CLIENT_EMAIL"),
        "client_id": get_env_var("GS_CLIENT_ID"),
        "auth_uri": get_env_var("GS_AUTH_URI"),
        "token_uri": get_env_var("GS_TOKEN_URI"),
        "auth_provider_x509_cert_url": get_env_var("GS_AUTH_PROVIDER_CERT_URL"),
        "client_x509_cert_url": get_env_var("GS_CLIENT_CERT_URL"),
        "universe_domain": get_env_var("GS_UNIVERSE_DOMAIN"),
    }
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_attendance_sheet():
    client = get_gsheet_client()
    spreadsheet_id = get_env_var("SPREADSHEET_ID")
    ss = client.open_by_key(spreadsheet_id)

    # Use (or create) a worksheet named "Attendance"
    try:
        ws = ss.worksheet("Attendance")
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title="Attendance", rows=1000, cols=12)
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

    token_tail = token[-6:]  # short audit trail
    client_ip = (request.client.host if request.client else "") or ""
    user_agent = request.headers.get("user-agent", "")

    ws.append_row([
        ts, iso, session_id, token_tail, student_id.strip(), "OK", client_ip, user_agent
    ])

# ---------- Routes ----------
@app.get("/healthz")
def healthz():
    return {"ok": True, "ttl": TOKEN_TTL_SECONDS, "session_id": CURRENT_SESSION_ID}

@app.post("/session/start")
def start_session():
    """
    Teacher triggers a new attendance session (optional).
    If you call this from the Vue page once per class, you'll get a fresh session_id.
    """
    global CURRENT_SESSION_ID
    CURRENT_SESSION_ID = uuid.uuid4().hex
    return {"session_id": CURRENT_SESSION_ID}

@app.get("/")
def home():
    return {"message": "Secure Attendance API is running", "session_id": CURRENT_SESSION_ID}

@app.get("/generate")
def generate():
    """
    Issue a short-lived token for current session.
    Frontend encodes it in a URL that opens /scan/{token}.
    """
    _clean_expired()
    token = secrets.token_urlsafe(24)
    expires_at = _now() + TOKEN_TTL_SECONDS
    TOKENS[token] = (expires_at, CURRENT_SESSION_ID)
    return {"token": token, "expires_in": TOKEN_TTL_SECONDS, "session_id": CURRENT_SESSION_ID}

@app.get("/scan/{token}", response_class=HTMLResponse)
def scan_page(token: str):
    """
    Student lands here after scanning the QR.
    Renders a tiny HTML form (no CORS needed since it's same-origin).
    """
    _clean_expired()
    info = TOKENS.get(token)
    if not info:
        return HTMLResponse(
            content="<h2>Token invalid or expired.</h2>",
            status_code=401
        )
    # Minimal HTML form
    html = f"""
    <!doctype html>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Attendance Check-In</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 2rem; }}
      .card {{ max-width: 480px; margin: 0 auto; padding: 1.25rem; border: 1px solid #e5e7eb; border-radius: .75rem; }}
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
        <p class="muted">Session: {info[1][:8]}… · Token expires when submitted or in {int(info[0]-_now())}s</p>
      </form>
    </div>
    """
    return HTMLResponse(content=html)

@app.post("/check-in")
async def check_in(request: Request, token: str = Form(...), student_id: str = Form(...)):
    """
    Validate the token and record attendance. Token is consumed (one-time).
    """
    _clean_expired()
    info = TOKENS.get(token)
    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    expires_at, session_id = info
    if _now() > expires_at:
        TOKENS.pop(token, None)
        raise HTTPException(status_code=401, detail="Token expired")

    # Consume token first (prevent double submit)
    TOKENS.pop(token, None)

    try:
        append_attendance_row(session_id=session_id, token=token, student_id=student_id, request=request)
    except Exception as e:
        # You can choose to fail or still confirm; here we surface the error
        raise HTTPException(status_code=500, detail=f"Logged-in failed: {e}")

    # Success page
    return HTMLResponse(
        content=f"<h2>Check-in successful for {student_id} ✅</h2><p>Session {session_id[:8]}…</p>",
        status_code=200
    )

# (keep your /validate/{token} and /test-sheet if you still need them)
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

@app.get("/test-sheet")
def test_sheet():
    try:
        ws = get_attendance_sheet()
        return {"title": ws.title, "rows_head": ws.row_values(1)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
