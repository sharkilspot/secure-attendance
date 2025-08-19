from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import secrets, time, os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ---- Token Management ----
tokens = {}
TOKEN_EXPIRY = 30  # seconds

# ---- Google Sheets Setup ----
def init_gsheet():
    creds_dict = {
        "type": os.environ["GS_TYPE"],
        "project_id": os.environ["GS_PROJECT_ID"],
        "private_key_id": os.environ["GS_PRIVATE_KEY_ID"],
        "private_key": os.environ["GS_PRIVATE_KEY"].replace("\\n", "\n"),
        "client_email": os.environ["GS_CLIENT_EMAIL"],
        "client_id": os.environ["GS_CLIENT_ID"],
        "auth_uri": os.environ["GS_AUTH_URI"],
        "token_uri": os.environ["GS_TOKEN_URI"],
        "auth_provider_x509_cert_url": os.environ["GS_AUTH_PROVIDER_CERT_URL"],
        "client_x509_cert_url": os.environ["GS_CLIENT_CERT_URL"],
        "universe_domain": os.environ["GS_UNIVERSE_DOMAIN"]
    }

    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_url(os.environ["GS_SHEET_URL"]).sheet1
    return sheet

sheet = init_gsheet()

# ---- Generate token ----
@app.get("/generate")
def generate_token():
    token = secrets.token_urlsafe(8)
    expiry = int(time.time()) + TOKEN_EXPIRY
    tokens[token] = expiry
    return {"token": token, "expires_in": TOKEN_EXPIRY}

# ---- Validate token and log presence ----
class ScanResult(BaseModel):
    student_id: str

@app.get("/validate/{token}")
def validate_token(token: str, student_id: str):
    now = int(time.time())
    expiry = tokens.get(token)
    if not expiry:
        return {"status": "invalid"}
    if now > expiry:
        return {"status": "expired"}

    # Log to Google Sheets
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    sheet.append_row([student_id, timestamp, token])
    
    return {"status": "valid", "logged_at": timestamp}
