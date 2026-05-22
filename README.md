# ⚡ LLM Inference Logger

A lightweight, production-ready inference logging and observability system for LLM applications. Built with FastAPI, React, and SQLite — deployable via Docker Compose or Kubernetes.

![Dashboard Preview](docs/screenshot.png)

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                              │
│   ┌────────────────────┐   ┌──────────────────────────┐    │
│   │   Chat UI (React)  │   │  Dashboard (React)        │    │
│   │  Multi-turn chat   │   │  Latency / Throughput /  │    │
│   │  Stream support    │   │  Error rate charts        │    │
│   └────────┬───────────┘   └──────────┬───────────────┘    │
└────────────┼──────────────────────────┼────────────────────┘
             │  REST + SSE              │  REST
             ▼                          ▼
┌──────────────────────────────────────────────────────────────┐
│              FastAPI Backend  (port 8000)                    │
│                                                              │
│  /api/chat          ← Proxy to Anthropic + stream support   │
│  /api/logs/ingest   ← SDK logs ingestion endpoint           │
│  /api/conversations ← CRUD for conversations                │
│  /api/analytics/*   ← Aggregated metrics queries            │
│                                                              │
│  ┌──────────────────────────────────┐                        │
│  │     LLM Logger SDK (built-in)    │                        │
│  │  Captures: latency, tokens,      │                        │
│  │  status, previews, session ID    │                        │
│  │  PII redaction before storage    │                        │
│  └──────────────┬───────────────────┘                        │
└─────────────────┼────────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────┐
│  SQLite  (or swap Postgres)  │
│  conversations               │
│  messages                    │
│  inference_logs              │
└──────────────────────────────┘
```

### Ingestion Flow
1. User sends a message via the Chat UI
2. Backend `/api/chat` receives the request, proxies to Anthropic (streaming or not)
3. After completion, metadata (latency, tokens, timestamps, previews) is written directly to `inference_logs`
4. Standalone SDK (`sdk/llm_logger_sdk.py`) can also POST to `/api/logs/ingest` from any external process
5. Dashboard polls `/api/analytics/*` for aggregated metrics

---

## 🚀 Quick Start

### Option 1 — Docker Compose (recommended)

```bash
git clone https://github.com/YOUR_USERNAME/llm-inference-logger
cd llm-inference-logger

cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Option 2 — Local Dev

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-ant-... uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## 📐 Schema Design

### `conversations`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | UUID |
| title | TEXT | Auto-generated or user-set |
| provider | TEXT | anthropic / openai / etc. |
| model | TEXT | Full model string |
| created_at | TEXT | ISO8601 |
| updated_at | TEXT | Updated on each message |
| status | TEXT | active / cancelled |
| message_count | INTEGER | Denormalized for fast listing |

### `messages`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | UUID |
| conversation_id | TEXT FK | |
| role | TEXT | user / assistant |
| content | TEXT | Full content (PII-redacted) |
| content_preview | TEXT | First 200 chars |
| created_at | TEXT | ISO8601 |

### `inference_logs`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | UUID |
| conversation_id | TEXT FK | |
| message_id | TEXT FK | Links to assistant message |
| provider | TEXT | anthropic / openai / gemini |
| model | TEXT | Full model string |
| latency_ms | REAL | End-to-end wall time |
| prompt_tokens | INTEGER | |
| completion_tokens | INTEGER | |
| total_tokens | INTEGER | Denormalized sum |
| input_preview | TEXT | First 200 chars, PII-redacted |
| output_preview | TEXT | First 200 chars, PII-redacted |
| status | TEXT | success / error |
| error_message | TEXT | Null on success |
| timestamp | TEXT | ISO8601 of request start |
| request_id | TEXT | Unique per API call |
| streaming | INTEGER | 0/1 boolean |

**Design decisions:**
- Separate `conversations`, `messages`, and `inference_logs` tables — clean separation of concerns; a message is a logical unit, a log is an observability unit
- `content_preview` denormalization avoids full-table scans in the dashboard
- `total_tokens` denormalized — avoids runtime addition in analytics queries
- SQLite chosen for zero-config local dev; swap to Postgres by changing one env var and the connection string

---

## ⚖️ Tradeoffs Made

| Decision | Choice | Why |
|---|---|---|
| DB | SQLite | Zero config, single binary. Swap to Postgres for prod with 1 change |
| Async logs | Fire-and-forget `create_task` | Doesn't block chat response; acceptable risk of rare loss |
| PII redaction | Regex at ingest time | Lightweight, no ML dependency. Misses contextual PII |
| Streaming | SSE via FastAPI | Works without WebSocket; simpler infra |
| Auth | None | Out of scope for this demo; add OAuth2/JWT middleware |
| Multi-provider | SDK abstraction | Easy to add OpenAI/Gemini by adding a provider-specific method |

---

## 🔮 What I'd Improve With More Time

1. **Postgres + Alembic** — production DB with migrations, proper indexes, and read replicas
2. **Message queue** — Kafka or Redis Streams for the ingestion pipeline instead of direct DB writes; decouples load spikes
3. **Auth** — JWT + per-user conversation isolation
4. **Real-time dashboard** — WebSocket push instead of polling
5. **Full PII redaction** — NLP-based entity recognition (spaCy/Presidio) instead of regex
6. **Distributed tracing** — OpenTelemetry integration for full request traces across services
7. **Multi-provider** — OpenAI, Gemini, DeepSeek adapters with unified interface
8. **Rate limiting** — per-user token budget enforcement
9. **Alerting** — webhook/email when error rate exceeds threshold
10. **Export** — CSV/JSON export of logs for offline analysis

---

## 📊 Logging Strategy

- **Near real-time**: logs are written within the same request lifecycle, immediately after the LLM response
- **Fail-safe**: `fail_silently=True` in the SDK — a logging failure never breaks the chat
- **PII-safe**: input/output previews are redacted before storage using regex patterns for email, phone, SSN, credit cards, IPs
- **Structured**: all logs are typed Pydantic models validated before storage

## 📈 Scaling Considerations

- Replace SQLite with **Postgres** and add indexes on `(timestamp, conversation_id)`
- Add a **write-ahead buffer** (Redis list) in front of the DB for burst ingestion
- **Horizontal scale** the FastAPI backend behind a load balancer (stateless by design)
- Move analytics aggregations to **materialized views** or a time-series DB (TimescaleDB / ClickHouse)
- Use **Kubernetes HPA** (provided manifests) to auto-scale pods on CPU/memory

## 🛡️ Failure Handling

- All LLM errors are caught, logged with `status=error`, and returned as HTTP 500 to the client
- Streaming errors mid-stream yield a final `{"error": ...}` SSE event
- Ingestion endpoint validates all fields via Pydantic; invalid payloads return 422
- DB writes are wrapped in try/catch; logging failures never surface to the user

---

## 🐳 Kubernetes Deployment

```bash
# Build images
docker build -t llm-logger-backend ./backend
docker build -t llm-logger-frontend ./frontend

# Apply manifests
kubectl apply -f k8s/manifests.yaml

# Check pods
kubectl get pods -n llm-logger
```

Set your API key in `k8s/manifests.yaml` under the Secret before applying.

---

## 🧩 SDK Usage (standalone)

```python
from sdk.llm_logger_sdk import LLMLoggerSDK

sdk = LLMLoggerSDK(
    api_key="sk-ant-...",
    ingestion_url="http://localhost:8000/api/logs/ingest",
)

result = await sdk.call_anthropic(
    messages=[{"role": "user", "content": "Hello!"}],
    conversation_id="my-conv-123",
)
print(result["text"])
```

---

## 📬 Submission

Submitted to: work@ollive.ai  
GitHub: https://github.com/YOUR_USERNAME/llm-inference-logger
