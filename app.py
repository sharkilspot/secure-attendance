import os
import secrets
import time
import datetime
import asyncio
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

# Load .env file if running locally
load_dotenv()

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
# Google Sheets setup
# ----------------------
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

def get_env_var(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set!")
    return value

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

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
client = gspread.authorize(creds)

# Open by spreadsheet ID
SPREADSHEET_ID = get_env_var("SPREADSHEET_ID")  # Set your sheet ID in .env
sheet = client.open_by_key(SPREADSHEET_ID).sheet1

# ----------------------
# Token system
# ----------------------
tokens = {}
TOKEN_TTL = 30  # seconds

# ----------------------
# Background async append
# ----------------------
async def append_row_async(row):
    try:
        await asyncio.to_thread(sheet.append_row, row)
    except Exception as e:
        print("Google Sheets append error:", e)

# ----------------------
# Routes
# ----------------------
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
async def validate_token(token: str, student_id: str = Query(...), background_tasks: BackgroundTasks = None):
    expiry = tokens.get(token)
    if not expiry:
        raise HTTPException(status_code=400, detail="Invalid or already used token")

    if time.time() > expiry:
        del tokens[token]
        raise HTTPException(status_code=400, detail="Token expired")

    del tokens[token]
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Schedule background task
    if background_tasks:
        background_tasks.add_task(append_row_async, [student_id, timestamp, "Present"])
    else:
        # fallback synchronous append if no BackgroundTasks
        await append_row_async([student_id, timestamp, "Present"])

    return {"status": "success", "message": f"Attendance recorded for {student_id}"}
