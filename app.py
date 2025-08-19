# app.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import secrets
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI(title="Secure Attendance API")

# ----------------------------
# CORS middleware
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for simplicity
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

# ----------------------------
# In-memory token store
# ----------------------------
# Structure: {token_string: expiration_timestamp}
token_store = {}

# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def home():
    return {"message": "Secure Attendance API is running"}

@app.get("/generate")
def generate_token():
    token = secrets.token_urlsafe(8)
    expires_in = 30  # token valid for 30 seconds
    expiration = time.time() + expires_in
    token_store[token] = expiration
    return {"token": token, "expires_in": expires_in}

@app.get("/validate/{token}")
def validate(token: str):
    now = time.time()
    exp = token_store.get(token)
    if exp and now < exp:
        # token is valid; optionally remove it if single-use
        del token_store[token]
        return {"status": "success", "token": token}
    raise HTTPException(status_code=401, detail="Invalid or expired token")

@app.get("/test-sheet")
def test_sheet():
    try:
        client = get_gsheet_client()
        SPREADSHEET_ID = get_env_var("SPREADSHEET_ID")
        sheet = client.open_by_key(SPREADSHEET_ID).sheet1
        return {"title": sheet.title, "rows": sheet.get_all_records()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
