# app.py
import os
import time
import secrets
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI(title="Secure Attendance API")

# ----------------------------
# CORS (IMPORTANT)
# ----------------------------
# Starlette does NOT support wildcards like "https://*.vuejs.org" in allow_origins.
# Use allow_origin_regex for subdomains, and explicit origins for others.
def _env_list(name: str) -> List[str]:
    val = os.getenv(name, "").strip()
    return [x.strip() for x in val.split(",") if x.strip()] if val else []

EXTRA_ORIGINS = _env_list("FRONTEND_ORIGINS")  # optional, comma-separated
# Known good origins: SFC Playground + Play
DEFAULT_EXPLICIT_ORIGINS = [
    "https://sfc.vuejs.org",
    "https://play.vuejs.org",
]

# Build final explicit origins (filter empties to avoid 'null' origin checks).
ALLOW_ORIGINS = [*DEFAULT_EXPLICIT_ORIGINS, *EXTRA_ORIGINS]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,                 # explicit list
    allow_origin_regex=r"^https://([a-z0-9-]+\.)*vuejs\.org$",  # any subdomain of vuejs.org
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,  # you aren't using cookies; keep this False for simpler CORS
)

# ----------------------------
# Token store (in-memory)
# ----------------------------
TOKENS: Dict[str, float] = {}  # token -> expires_at (epoch seconds)
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", "5"))

def _now() -> float:
    return time.time()

def _clean_expired():
    now = _now()
    for t, exp in list(TOKENS.items()):
        if exp < now:
            TOKENS.pop(t, None)

# ----------------------------
# ENV helper
# ----------------------------
def get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set!")
    return value

# ----------------------------
# Google Sheets client
# ----------------------------
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

# ----------------------------
# Routes
# ----------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True, "ttl": TOKEN_TTL_SECONDS}

@app.get("/")
def home():
    return {"message": "Secure Attendance API is running"}

@app.get("/generate")
def generate():
    """
    Issue a short-lived token for QR. Frontend embeds it in /validate/{token}.
    """
    _clean_expired()
    token = secrets.token_urlsafe(24)
    expires_at = _now() + TOKEN_TTL_SECONDS
    TOKENS[token] = expires_at
    return {"token": token, "expires_in": TOKEN_TTL_SECONDS}

@app.get("/validate/{token}")
def validate(token: str, consume: bool = True):
    """
    Validate a token. If consume=True, make it one-time-use.
    """
    _clean_expired()
    expires_at = TOKENS.get(token)
    if not expires_at:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if consume:
        TOKENS.pop(token, None)
    return {"status": "success", "token": token, "expires_at": int(expires_at)}

@app.get("/test-sheet")
def test_sheet():
    try:
        client = get_gsheet_client()
        SPREADSHEET_ID = get_env_var("SPREADSHEET_ID")
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        return {"title": sheet.title, "rows": sheet.get_all_records()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
