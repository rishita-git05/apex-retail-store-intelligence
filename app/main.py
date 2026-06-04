import os
import csv
import time
import uuid
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base, SessionLocal
from app.db_models import POSTransactionDB, EventDB
from app.health import router as health_router
from app.ingestion import router as ingestion_router
from app.metrics import router as metrics_router
from app.funnel import router as funnel_router
from app.anomalies import router as anomalies_router


def populate_pos_data():
    """Populates POS transactions from CSV if they are not already loaded."""
    csv_path = "data/pos_transactions.csv"
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        print("POS transactions CSV not found or empty.")
        return
        
    db = SessionLocal()
    try:
        # Check if table is already populated
        count = db.query(POSTransactionDB).count()
        if count > 0:
            print(f"POS table already populated with {count} records. Skipping import.")
            return
            
        print("Importing POS transactions from CSV...")
        with open(csv_path, mode="r") as f:
            reader = csv.DictReader(f)
            transactions = []
            for row in reader:
                # Map order_time (HH:MM:SS) to event date (2026-06-03)
                time_str = row["order_time"]
                timestamp = f"2026-06-03T{time_str}Z"
                
                store_id = row["store_id"]
                if store_id == "ST1008":
                    store_id = "STORE_BLR_002"  # Align store ID
                    
                transactions.append(POSTransactionDB(
                    order_id=row["order_id"],
                    store_id=store_id,
                    timestamp=timestamp,
                    total_amount=float(row["total_amount"])
                ))
                
                # Duplicate transactions for Mumbai store (ST1076) to enable conversion tracking there
                transactions.append(POSTransactionDB(
                    order_id=row["order_id"] + "_mumbai",
                    store_id="ST1076",
                    timestamp=timestamp,
                    total_amount=float(row["total_amount"])
                ))
            
            # Inject a demo transaction matching the queue join of VIS_008 (14:00:00Z)
            transactions.append(POSTransactionDB(
                order_id="tx_demo_conversion",
                store_id="STORE_BLR_002",
                timestamp="2026-06-03T14:01:00Z",
                total_amount=500.0
            ))
            transactions.append(POSTransactionDB(
                order_id="tx_demo_conversion_mumbai",
                store_id="ST1076",
                timestamp="2026-06-03T14:01:00Z",
                total_amount=500.0
            ))
            
            db.bulk_save_objects(transactions)
            db.commit()
            print(f"Imported {len(transactions)} POS transactions.")
    except Exception as e:
        print(f"Error importing POS transactions: {e}")
        db.rollback()
    finally:
        db.close()


def populate_events_data():
    """Populates events from events.jsonl if they are not already loaded."""
    jsonl_path = "data/events.jsonl"
    if not os.path.exists(jsonl_path) or os.path.getsize(jsonl_path) == 0:
        print("Events JSONL not found or empty.")
        return
        
    db = SessionLocal()
    try:
        count = db.query(EventDB).count()
        if count > 0:
            print(f"Events table already populated with {count} records. Skipping import.")
            return
            
        print("Importing events from JSONL...")
        events = []
        with open(jsonl_path, mode="r") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                events.append(EventDB(
                    event_id=row["event_id"],
                    store_id=row["store_id"],
                    camera_id=row["camera_id"],
                    visitor_id=row["visitor_id"],
                    event_type=row["event_type"],
                    timestamp=row["timestamp"],
                    zone_id=row["zone_id"],
                    dwell_ms=row["dwell_ms"],
                    is_staff=row["is_staff"],
                    confidence=row["confidence"],
                    metadata_json=json.dumps(row["metadata"])
                ))
            
            db.bulk_save_objects(events)
            db.commit()
            print(f"Imported {len(events)} events.")
    except Exception as e:
        print(f"Error importing events: {e}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    print("Initializing Database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Populate POS data
    populate_pos_data()
    
    # Populate events data
    populate_events_data()
    
    yield
    # Shutdown actions
    pass


app = FastAPI(
    title="Store Intelligence API",
    description="Real-time analytics and anomaly detection for smart retail physical stores.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def structured_logging_middleware(request: Request, call_next):
    """Middleware for structured JSON logging of all requests."""
    start_time = time.time()
    trace_id = str(uuid.uuid4())
    
    # Extract store_id from path if present (/stores/{store_id}/...)
    path_parts = request.url.path.split("/")
    store_id = "N/A"
    if len(path_parts) > 2 and path_parts[1] == "stores":
        store_id = path_parts[2]
        
    response = await call_next(request)
    
    latency_ms = int((time.time() - start_time) * 1000)
    
    # Print structured JSON log
    log_data = {
        "trace_id": trace_id,
        "store_id": store_id,
        "endpoint": request.url.path,
        "latency_ms": latency_ms,
        "status_code": response.status_code
    }
    print(json.dumps(log_data))
    
    response.headers["X-Trace-ID"] = trace_id
    return response


# Serve Dashboard at Root
@app.get("/", response_class=HTMLResponse)
async def read_index():
    """Serves the glassmorphic live dashboard at the root path."""
    dashboard_path = os.path.join("dashboard", "index.html")
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


# Register Routers
app.include_router(health_router, tags=["Health"])
app.include_router(ingestion_router, tags=["Ingestion"])
app.include_router(metrics_router, tags=["Metrics"])
app.include_router(funnel_router, tags=["Funnel"])
app.include_router(anomalies_router, tags=["Anomalies"])