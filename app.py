import secrets
import time
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ----------------------
# CORS (so Vue can call it)
# ----------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for dev, allow everything
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# In-memory token store
# ----------------------
tokens = {}  # { token: expiry_time }
TOKEN_TTL = 30  # seconds

# ----------------------
# Generate token
# ----------------------
@app.get("/generate")
def generate_token():
    token = secrets.token_urlsafe(8)  # secure random string
    expiry = time.time() + TOKEN_TTL
    tokens[token] = expiry
    return {"token": token, "expires_in": TOKEN_TTL}

# ----------------------
# Validate token
# ----------------------
@app.get("/validate/{token}")
def validate_token(token: str):
    expiry = tokens.get(token)

    if not expiry:
        raise HTTPException(status_code=400, detail="Invalid or already used token")

    if time.time() > expiry:
        del tokens[token]  # remove expired
        raise HTTPException(status_code=400, detail="Token expired")

    # One-time use: remove after validation
    del tokens[token]
    return {"status": "success", "message": "Attendance recorded!"}
