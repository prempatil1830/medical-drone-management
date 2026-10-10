# Medical Drone Delivery Management Platform

AI-powered medical drone delivery management and simulation platform.

> **Phase 1** — Backend bootstrap only. Auth, drone, and agent logic are future phases.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite |
| Backend | Python 3.12+ · FastAPI |
| Database | MongoDB 7 (async via Motor) |
| Config | Pydantic-Settings |
| Logging | structlog |
| Containerisation | Docker Compose (Mongo only) |

---

## Repository Layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── core/
│   │   │   ├── config.py        # Pydantic settings
│   │   │   └── logging.py       # structlog setup
│   │   ├── db/
│   │   │   └── database.py      # Motor connection helpers
│   │   ├── api/
│   │   │   ├── router.py        # Root API router
│   │   │   └── health.py        # GET /api/health
│   │   ├── schemas/             # Pydantic request/response models (future)
│   │   ├── repositories/        # DB query layer (future)
│   │   ├── services/            # Business logic (future)
│   │   ├── agents/              # AI agent orchestration (future)
│   │   ├── ml/                  # ML inference (future)
│   │   ├── routing/             # Route planning (future)
│   │   ├── simulation/          # Drone simulation (future)
│   │   └── websocket/           # Real-time updates (future)
│   ├── tests/
│   ├── scripts/
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── services/
│       ├── hooks/
│       ├── store/
│       └── maps/
├── data/
├── models/
├── docker-compose.yml
├── .env.example
└── menv/                        # Python virtual environment (git-ignored)
```

---

## Running the Backend Locally

### 1 — Prerequisites

- Python 3.12 or higher
- Docker (for the MongoDB container) **or** a locally running MongoDB instance

### 2 — Clone & enter the project

```bash
git clone <repo-url>
cd "medical drone management"
```

### 3 — Create and activate the virtual environment

```bash
python3 -m venv menv
source menv/bin/activate      # Windows: menv\Scripts\activate
```

> The `menv/` directory is already created at the project root and is git-ignored.

### 4 — Install Python dependencies

```bash
pip install -r backend/requirements.txt
```

### 5 — Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in real values if needed
```

Minimum required for Phase 1 (defaults work for local Docker Mongo):

```
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=medical_drone_db
```

### 6 — Start MongoDB via Docker Compose

```bash
docker compose up -d mongo
```

### 7 — Start the FastAPI backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 8 — Verify the health endpoint

```bash
curl http://localhost:8000/api/health
```

Expected response when Mongo is reachable:

```json
{"status": "ok", "mongo": "connected"}
```

If Mongo is unreachable you will still get HTTP 200 with:

```json
{"status": "degraded", "mongo": "error: ..."}
```

### 9 — Explore the auto-generated API docs

- **Swagger UI** → http://localhost:8000/docs
- **ReDoc**      → http://localhost:8000/redoc

---

## Environment Variables Reference

| Variable | Description |
|---|---|
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DATABASE` | Database name |
| `JWT_SECRET` | Secret for signing JWTs (future phase) |
| `WEATHER_API_KEY` | Key for weather API |
| `WEATHER_API_BASE_URL` | Base URL for weather API |
| `MAP_PROVIDER_KEY` | Key for map tile provider |
| `MODEL_PATH` | Path to ML model files |
| `CORS_ORIGINS` | Comma-separated allowed origins |

See `.env.example` for a full template.

---

## Running Tests

```bash
cd backend
pytest tests/
```

---

## Phase Roadmap

| Phase | Scope |
|---|---|
| **1 (current)** | Repo scaffold · FastAPI bootstrap · MongoDB connection · /api/health |
| 2 | Drone CRUD API · Pydantic schemas · Repository pattern |
| 3 | Route optimisation service · Simulation engine |
| 4 | AI agents · ML inference |
| 5 | WebSocket real-time updates · React frontend |
| 6 | Auth (JWT) · Role-based access control |
