import asyncio
from fastapi import BackgroundTasks

# Keep your imports and setup as-is

async def append_row_async(row):
    """Append row to Google Sheets in background to prevent blocking."""
    try:
        await asyncio.to_thread(sheet.append_row, row)
    except Exception as e:
        print("Google Sheets append error:", e)

@app.get("/validate/{token}")
async def validate_token(token: str, student_id: str = Query(...), background_tasks: BackgroundTasks):
    expiry = tokens.get(token)
    if not expiry:
        raise HTTPException(status_code=400, detail="Invalid or already used token")

    if time.time() > expiry:
        del tokens[token]
        raise HTTPException(status_code=400, detail="Token expired")

    del tokens[token]
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Schedule background task to append to Google Sheets
    background_tasks.add_task(append_row_async, [student_id, timestamp, "Present"])

    return {"status": "success", "message": f"Attendance recorded for {student_id}"}
