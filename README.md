# Store Intelligence System (Apex Retail Edge)

An end-to-end computer vision and data engineering intelligence system designed to process physical store CCTV footage, track shoppers across multiple camera zones, detect checkout queues, and expose real-time queryable API analytics.

---

## System Overview

Apex Retail operates 40 physical stores across 8 cities. This system eliminates data blind spots by translating raw CCTV video streams into actionable, real-time store analytics:

📹 **Raw CCTV Clips** $\rightarrow$ 🔍 **Detection & Tracking Layer** $\rightarrow$ ⚡ **Event Stream** $\rightarrow$ 🧠 **FastAPI REST API** $\rightarrow$ 📊 **Live Glassmorphism Dashboard**

---

## Quick Setup (5 Commands)

To run the entire system on a clean host machine:

```bash
# 1. Clone the repository and enter the directory
git clone https://github.com/your-username/store-intelligence.git && cd store-intelligence

# 2. Start the API & database server container in background
docker compose up --build -d

# 3. Initialize Python virtual environment
# For Windows (PowerShell):
python -m venv .venv && .venv\Scripts\Activate.ps1
# For macOS/Linux (Bash/Zsh):
# python -m venv .venv && source .venv/bin/activate

# 4. Install pipeline dependencies
pip install -r requirements.txt

# 5. Execute computer vision pipeline for default store (STORE_BLR_002)
python pipeline/run.py --store STORE_BLR_002
```

---

## Video Dataset Setup

Place raw `.mp4` video files under `data/videos/{store_id}/` named after their camera channels:
- **STORE_BLR_002 (Bangalore)**:
  - `data/videos/STORE_BLR_002/CAM 1.mp4` (Floor Shelf Interactions - Top Wall)
  - `data/videos/STORE_BLR_002/CAM 2.mp4` (Floor Shelf Interactions - Bottom Wall)
  - `data/videos/STORE_BLR_002/CAM 3.mp4` (Store Entrance/Exit)
  - `data/videos/STORE_BLR_002/CAM 5.mp4` (Billing Checkout Counter)
- **ST1076 (Mumbai)**:
  - `data/videos/ST1076/CAM 1.mp4` (Floor Zone Coverage)
  - `data/videos/ST1076/CAM 3.mp4` (Entrance 1)
  - `data/videos/ST1076/CAM 4.mp4` (Entrance 2)
  - `data/videos/ST1076/CAM 5.mp4` (Billing Counter)

*(Note: Videos are locally ignored by `.gitignore` to prevent committing heavy binaries).*

---

## Component Guide

### 1. Computer Vision Pipeline (`pipeline/`)
Decoupled frame processing pipeline running locally on the host CPU or GPU:
- [detect.py]: Bounding-box human detection using YOLOv8n.
- [tracker.py]: Single-camera tracking + Space-Time HSV color histogram cross-camera Re-ID (runs at $30+\text{FPS}$ on CPU).
- [emit.py]: Resolves layout coordinate boundaries, filters store staff (via HSV torso uniform color checks), tracks queue dwells, and generates behavioral events (`ENTRY`, `EXIT`, `ZONE_ENTER`, `ZONE_EXIT`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `BILLING_QUEUE_ABANDON`, `REENTRY`).
- [run.py]: Lockstep multi-video stream runner. Emits to `data/events.jsonl` and auto-posts to the API server.

Run manually for a specific store:
```bash
python pipeline/run.py --store STORE_BLR_002
# or
python pipeline/run.py --store ST1076
```

### 2. REST API (`app/`)
High-performance FastAPI containerized application that ingests events, handles transactions, and calculates live analytics:
- `POST /events/ingest`: Idempotent batch event ingestion (up to 500 events, supports partial success).
- `GET /stores/{id}/metrics`: Live store metrics (unique visitors, conversion rate, checkout queue depth/abandonment).
- `GET /stores/{id}/funnel`: Conversion funnel analysis and drop-offs (`Entry -> Zone Visit -> Queue -> Purchase`).
- `GET /stores/{id}/heatmap`: Brand shelves visits and dwell metrics.
- `GET /stores/{id}/anomalies`: Active store alarms (e.g. `BILLING_QUEUE_SPIKE`, `CONVERSION_DROP`).
- `GET /health`: Core service status and stale feed lag metrics.

Run manually outside Docker:
```bash
PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Glassmorphic Live Dashboard (`dashboard/`)
To visualize real-time store metrics, shelf heatmaps, anomalies, and live event logs:
1. Open [dashboard/index.html] in any modern web browser.
2. Select the store ID from the dropdown list.
3. The dashboard connects to the API at `http://localhost:8000` and refreshes metrics and alerts dynamically.

---

## Testing & Coverage

Run the pytest suite to assert correctness and verify $>70\%$ statement coverage:
```bash
PYTHONPATH=. pytest tests -v --cov=app
```
*(All 24 test assertions covering database operations, CV trackers, and edge conditions must pass successfully).*
