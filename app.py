import os
import secrets
import time
import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# ----------------------
# CORS
# ----------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Google Sheets setup (from ENV)
# ----------------------
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

creds_dict = {
    "type": os.getenv("GS_TYPE"),
    "project_id": os.getenv("GS_PROJECT_ID"),
    "private_key_id": os.getenv("GS_PRIVATE_KEY_ID"),
    "private_key": os.getenv("GS_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.getenv("GS_CLIENT_EMAIL"),
    "client_id": os.getenv("GS_CLIENT_ID"),
    "auth_uri": os.getenv("GS_AUTH_URI"),
    "token_uri": os.getenv("GS_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.getenv("GS_AUTH_PROVIDER_CERT_URL"),
    "client_x509_cert_url": os.getenv("GS_CLIENT_CERT_URL"),
    "universe_domain": os.getenv("GS_UNIVERSE_DOMAIN"),
}

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(creds)

# Open by spreadsheet ID
SPREADSHEET_ID = "1Xu3iwUKsgwP3pr5ObtRb6cUQEYjJdkxUgeyGw-wYSv4"
sheet = client.open_by_key(SPREADSHEET_ID).sheet1  # first sheet (AttendanceLog)

# ----------------------
# Token system
# ----------------------
tokens = {}
TOKEN_TTL = 30  # seconds

@app.get("/")
def home():
    return {"message": "Attendance API is running 🚀"}

@app.get("/generate")
def generate_token():
    token = secrets.token_urlsafe(8)
    expiry = time.time() + TOKEN_TTL
    tokens[token] = expiry
    return {"token": token, "expires_in": TOKEN_TTL}

@app.get("/validate/{token}")
def validate_token(token: str, student_id: str = Query(...)):
    expiry = tokens.get(token)
    if not expiry:
        raise HTTPException(status_code=400, detail="Invalid or already used token")

    if time.time() > expiry:
        del tokens[token]
        raise HTTPException(status_code=400, detail="Token expired")

    # One-time use
    del tokens[token]

    # Append to Google Sheet
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([student_id, timestamp, "Present"])

    return {"status": "success", "message": f"Attendance recorded for {student_id}"}
