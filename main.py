"""
LLM Inference Logger - Ingestion API
FastAPI backend with SQLite storage, validation, and metadata extraction.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import sqlite3
import json
import uuid
import re
import os
import time
import asyncio
import httpx

app = FastAPI(title="LLM Inference Logger", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.environ.get("DB_PATH", "inference_logs.db")

# --- PII Redaction ---
PII_PATTERNS = [
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]'),
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]'),
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    (r'\b4[0-9]{12}(?:[0-9]{3})?\b', '[CARD]'),
    (r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b', '[IP]'),
]

def redact_pii(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in PII_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text

# --- Database Setup ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT,
            provider TEXT,
            model TEXT,
            created_at TEXT,
            updated_at TEXT,
            status TEXT DEFAULT 'active',
            message_count INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            content_preview TEXT,
            created_at TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inference_logs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            message_id TEXT,
            provider TEXT,
            model TEXT,
            latency_ms REAL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            input_preview TEXT,
            output_preview TEXT,
            status TEXT,
            error_message TEXT,
            timestamp TEXT,
            request_id TEXT,
            streaming INTEGER DEFAULT 0,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    conn.commit()
    conn.close()

init_db()

# --- Pydantic Models ---
class InferenceLog(BaseModel):
    conversation_id: str
    message_id: Optional[str] = None
    provider: str
    model: str
    latency_ms: float
    prompt_tokens: Optional[int] = 0
    completion_tokens: Optional[int] = 0
    total_tokens: Optional[int] = 0
    input_preview: Optional[str] = ""
    output_preview: Optional[str] = ""
    status: str = "success"
    error_message: Optional[str] = None
    timestamp: str
    request_id: Optional[str] = None
    streaming: bool = False

class MessageCreate(BaseModel):
    conversation_id: str
    role: str
    content: str

class ConversationCreate(BaseModel):
    title: Optional[str] = None
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    model: str = "claude-sonnet-4-20250514"
    provider: str = "anthropic"
    stream: bool = False

# --- Helpers ---
def get_db():
    return sqlite3.connect(DB_PATH)

def row_to_dict(cursor, row):
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))

# --- Ingestion Endpoint ---
@app.post("/api/logs/ingest")
async def ingest_log(log: InferenceLog):
    conn = get_db()
    c = conn.cursor()
    log_id = str(uuid.uuid4())

    # PII redaction
    input_preview = redact_pii(log.input_preview or "")
    output_preview = redact_pii(log.output_preview or "")

    c.execute("""
        INSERT INTO inference_logs
        (id, conversation_id, message_id, provider, model, latency_ms,
         prompt_tokens, completion_tokens, total_tokens,
         input_preview, output_preview, status, error_message,
         timestamp, request_id, streaming)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        log_id, log.conversation_id, log.message_id,
        log.provider, log.model, log.latency_ms,
        log.prompt_tokens, log.completion_tokens, log.total_tokens,
        input_preview, output_preview, log.status, log.error_message,
        log.timestamp, log.request_id or str(uuid.uuid4()),
        1 if log.streaming else 0
    ))
    conn.commit()
    conn.close()
    return {"log_id": log_id, "status": "ingested"}

# --- Conversation Endpoints ---
@app.post("/api/conversations")
async def create_conversation(body: ConversationCreate):
    conn = get_db()
    c = conn.cursor()
    conv_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    title = body.title or f"Chat {now[:10]}"
    c.execute("""
        INSERT INTO conversations (id, title, provider, model, created_at, updated_at, status)
        VALUES (?,?,?,?,?,?,?)
    """, (conv_id, title, body.provider, body.model, now, now, "active"))
    conn.commit()
    conn.close()
    return {"id": conv_id, "title": title, "provider": body.provider, "model": body.model,
            "created_at": now, "status": "active"}

@app.get("/api/conversations")
async def list_conversations():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
    rows = [row_to_dict(c, r) for r in c.fetchall()]
    conn.close()
    return rows

@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM conversations WHERE id=?", (conv_id,))
    row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv = row_to_dict(c, row)
    c.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (conv_id,))
    messages = [row_to_dict(c, r) for r in c.fetchall()]
    conn.close()
    return {**conv, "messages": messages}

@app.patch("/api/conversations/{conv_id}/cancel")
async def cancel_conversation(conv_id: str):
    conn = get_db()
    c = conn.cursor()
    now = datetime.utcnow().isoformat()
    c.execute("UPDATE conversations SET status='cancelled', updated_at=? WHERE id=?", (now, conv_id))
    conn.commit()
    conn.close()
    return {"status": "cancelled"}

# --- Messages ---
@app.post("/api/messages")
async def save_message(msg: MessageCreate):
    conn = get_db()
    c = conn.cursor()
    msg_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    content = redact_pii(msg.content)
    c.execute("INSERT INTO messages (id, conversation_id, role, content, content_preview, created_at) VALUES (?,?,?,?,?,?)",
              (msg_id, msg.conversation_id, msg.role, content, content[:200], now))
    c.execute("UPDATE conversations SET message_count=message_count+1, updated_at=? WHERE id=?", (now, msg.conversation_id))
    conn.commit()
    conn.close()
    return {"id": msg_id}

# --- Chat Endpoint (calls Anthropic API) ---
@app.post("/api/chat")
async def chat(req: ChatRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    conn = get_db()
    c = conn.cursor()

    # Create or get conversation
    if not req.conversation_id:
        conv_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        c.execute("INSERT INTO conversations (id, title, provider, model, created_at, updated_at, status) VALUES (?,?,?,?,?,?,?)",
                  (conv_id, f"Chat {now[:10]}", req.provider, req.model, now, now, "active"))
        conn.commit()
    else:
        conv_id = req.conversation_id
        c.execute("SELECT status FROM conversations WHERE id=?", (conv_id,))
        row = c.fetchone()
        if row and row[0] == "cancelled":
            conn.close()
            raise HTTPException(status_code=400, detail="Conversation is cancelled")

    # Get history
    c.execute("SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at", (conv_id,))
    history = [{"role": r[0], "content": r[1]} for r in c.fetchall()]
    conn.close()

    # Save user message
    user_msg_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO messages (id, conversation_id, role, content, content_preview, created_at) VALUES (?,?,?,?,?,?)",
              (user_msg_id, conv_id, "user", req.message, req.message[:200], now))
    c.execute("UPDATE conversations SET message_count=message_count+1, updated_at=? WHERE id=?", (now, conv_id))
    conn.commit()
    conn.close()

    messages = history + [{"role": "user", "content": req.message}]

    start_time = time.time()
    request_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()

    if req.stream:
        return StreamingResponse(
            stream_anthropic(api_key, req.model, messages, conv_id, request_id, timestamp, start_time, req.message),
            media_type="text/event-stream"
        )

    # Non-streaming
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": req.model,
                    "max_tokens": 1024,
                    "messages": messages
                },
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()

        latency_ms = (time.time() - start_time) * 1000
        assistant_text = data["content"][0]["text"]
        usage = data.get("usage", {})

        # Save assistant message
        conn = get_db()
        c = conn.cursor()
        asst_msg_id = str(uuid.uuid4())
        now2 = datetime.utcnow().isoformat()
        c.execute("INSERT INTO messages (id, conversation_id, role, content, content_preview, created_at) VALUES (?,?,?,?,?,?)",
                  (asst_msg_id, conv_id, "assistant", assistant_text, assistant_text[:200], now2))
        c.execute("UPDATE conversations SET message_count=message_count+1, updated_at=? WHERE id=?", (now2, conv_id))

        # Save inference log
        log_id = str(uuid.uuid4())
        c.execute("""INSERT INTO inference_logs
            (id,conversation_id,message_id,provider,model,latency_ms,
             prompt_tokens,completion_tokens,total_tokens,
             input_preview,output_preview,status,timestamp,request_id,streaming)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (log_id, conv_id, asst_msg_id, "anthropic", req.model, latency_ms,
             usage.get("input_tokens", 0), usage.get("output_tokens", 0),
             usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
             redact_pii(req.message[:200]), redact_pii(assistant_text[:200]),
             "success", timestamp, request_id, 0))
        conn.commit()
        conn.close()

        return {
            "conversation_id": conv_id,
            "message": assistant_text,
            "usage": usage,
            "latency_ms": latency_ms,
            "model": req.model
        }

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        conn = get_db()
        c = conn.cursor()
        log_id = str(uuid.uuid4())
        c.execute("""INSERT INTO inference_logs
            (id,conversation_id,provider,model,latency_ms,input_preview,status,error_message,timestamp,request_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (log_id, conv_id, "anthropic", req.model, latency_ms,
             redact_pii(req.message[:200]), "error", str(e), timestamp, request_id))
        conn.commit()
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))

async def stream_anthropic(api_key, model, messages, conv_id, request_id, timestamp, start_time, user_input):
    full_text = ""
    usage = {}
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": 1024,
                    "stream": True,
                    "messages": messages
                },
                timeout=60
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            if data.get("type") == "content_block_delta":
                                chunk = data.get("delta", {}).get("text", "")
                                full_text += chunk
                                yield f"data: {json.dumps({'chunk': chunk, 'conversation_id': conv_id})}\n\n"
                            elif data.get("type") == "message_delta":
                                usage = data.get("usage", {})
                        except:
                            pass

        latency_ms = (time.time() - start_time) * 1000

        # Save to DB
        conn = get_db()
        c = conn.cursor()
        asst_msg_id = str(uuid.uuid4())
        now2 = datetime.utcnow().isoformat()
        c.execute("INSERT INTO messages (id, conversation_id, role, content, content_preview, created_at) VALUES (?,?,?,?,?,?)",
                  (asst_msg_id, conv_id, "assistant", full_text, full_text[:200], now2))
        c.execute("UPDATE conversations SET message_count=message_count+1, updated_at=? WHERE id=?", (now2, conv_id))
        log_id = str(uuid.uuid4())
        c.execute("""INSERT INTO inference_logs
            (id,conversation_id,message_id,provider,model,latency_ms,
             prompt_tokens,completion_tokens,total_tokens,
             input_preview,output_preview,status,timestamp,request_id,streaming)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (log_id, conv_id, asst_msg_id, "anthropic", model, latency_ms,
             usage.get("input_tokens", 0), usage.get("output_tokens", 0),
             usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
             redact_pii(user_input[:200]), redact_pii(full_text[:200]),
             "success", timestamp, request_id, 1))
        conn.commit()
        conn.close()

        yield f"data: {json.dumps({'done': True, 'conversation_id': conv_id, 'latency_ms': latency_ms})}\n\n"

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        conn = get_db()
        c = conn.cursor()
        log_id = str(uuid.uuid4())
        c.execute("""INSERT INTO inference_logs
            (id,conversation_id,provider,model,latency_ms,input_preview,status,error_message,timestamp,request_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (log_id, conv_id, "anthropic", model, latency_ms,
             redact_pii(user_input[:200]), "error", str(e), timestamp, request_id))
        conn.commit()
        conn.close()
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

# --- Analytics / Dashboard ---
@app.get("/api/analytics/overview")
async def analytics_overview():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM inference_logs")
    total_requests = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM inference_logs WHERE status='error'")
    total_errors = c.fetchone()[0]

    c.execute("SELECT AVG(latency_ms), MIN(latency_ms), MAX(latency_ms) FROM inference_logs WHERE status='success'")
    lat = c.fetchone()

    c.execute("SELECT SUM(total_tokens) FROM inference_logs")
    total_tokens = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(*) FROM conversations")
    total_convs = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM conversations WHERE status='active'")
    active_convs = c.fetchone()[0]

    conn.close()
    return {
        "total_requests": total_requests,
        "total_errors": total_errors,
        "error_rate": round((total_errors / max(total_requests, 1)) * 100, 2),
        "avg_latency_ms": round(lat[0] or 0, 2),
        "min_latency_ms": round(lat[1] or 0, 2),
        "max_latency_ms": round(lat[2] or 0, 2),
        "total_tokens": total_tokens,
        "total_conversations": total_convs,
        "active_conversations": active_convs,
    }

@app.get("/api/analytics/latency")
async def analytics_latency():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT substr(timestamp,1,16) as minute, AVG(latency_ms), COUNT(*)
        FROM inference_logs
        WHERE status='success'
        GROUP BY minute
        ORDER BY minute DESC
        LIMIT 50
    """)
    rows = c.fetchall()
    conn.close()
    return [{"time": r[0], "avg_latency": round(r[1], 2), "count": r[2]} for r in reversed(rows)]

@app.get("/api/analytics/errors")
async def analytics_errors():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT substr(timestamp,1,16) as minute, COUNT(*) as errors
        FROM inference_logs WHERE status='error'
        GROUP BY minute ORDER BY minute DESC LIMIT 50
    """)
    rows = c.fetchall()
    conn.close()
    return [{"time": r[0], "errors": r[1]} for r in reversed(rows)]

@app.get("/api/analytics/throughput")
async def analytics_throughput():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT substr(timestamp,1,16) as minute, COUNT(*), SUM(total_tokens)
        FROM inference_logs
        GROUP BY minute ORDER BY minute DESC LIMIT 50
    """)
    rows = c.fetchall()
    conn.close()
    return [{"time": r[0], "requests": r[1], "tokens": r[2] or 0} for r in reversed(rows)]

@app.get("/api/logs")
async def get_logs(limit: int = 50):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM inference_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [row_to_dict(c, r) for r in c.fetchall()]
    conn.close()
    return rows

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}
