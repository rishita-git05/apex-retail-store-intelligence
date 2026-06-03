# PROMPT: Write pytest unit tests for the FastAPI /events/ingest and /health endpoints, testing normal ingestion, partial success for malformed batches, database failure 503 responses, and feed status lag warnings in health checks.
# CHANGES MADE: Implemented database SessionLocal mocking to simulate database disconnects and test 503 graceful degradation.

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base
import app.ingestion as ingestion_module
import app.health as health_module

TEST_DATABASE_URL = "sqlite:///./test_ingest_health.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr(ingestion_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(health_module, "SessionLocal", TestSessionLocal)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.exists("test_ingest_health.db"):
        try:
            os.remove("test_ingest_health.db")
        except Exception:
            pass


def test_health_check_healthy():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_events_ingest_success():
    client = TestClient(app)
    payload = [
        {
            "event_id": "evt_success_1",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_3",
            "visitor_id": "VIS_001",
            "event_type": "ENTRY",
            "timestamp": "2026-06-03T14:00:00Z",
            "confidence": 0.95
        }
    ]
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["ingested"] == 1
    assert data["failed"] == 0


def test_events_ingest_partial_success():
    client = TestClient(app)
    # Include 1 valid event and 1 malformed event (missing required store_id & confidence)
    payload = [
        {
            "event_id": "evt_valid_1",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_3",
            "visitor_id": "VIS_001",
            "event_type": "ENTRY",
            "timestamp": "2026-06-03T14:00:00Z",
            "confidence": 0.95
        },
        {
            "event_id": "evt_malformed_2",
            "camera_id": "CAM_3",
            "visitor_id": "VIS_002",
            "event_type": "ENTRY",
            "timestamp": "2026-06-03T14:00:00Z"
        }
    ]
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 207  # Multi-Status
    data = res.json()
    assert data["status"] == "partial_success"
    assert data["ingested"] == 1
    assert data["failed"] == 1
    assert len(data["errors"]) == 1
    assert data["errors"][0]["event_id"] == "evt_malformed_2"


def test_events_ingest_database_unavailable(monkeypatch):
    client = TestClient(app)
    
    # Simulate database unavailability by making SessionLocal raise an error
    def mock_session_raise():
        raise Exception("Connection Refused")
        
    monkeypatch.setattr(ingestion_module, "SessionLocal", mock_session_raise)
    
    payload = [
        {
            "event_id": "evt_db_fail",
            "store_id": "STORE_BLR_002",
            "camera_id": "CAM_3",
            "visitor_id": "VIS_001",
            "event_type": "ENTRY",
            "timestamp": "2026-06-03T14:00:00Z",
            "confidence": 0.95
        }
    ]
    res = client.post("/events/ingest", json=payload)
    assert res.status_code == 503
    data = res.json()
    assert data["status"] == "error"
    assert "unavailable" in data["message"]
