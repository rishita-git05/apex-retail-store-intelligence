# PROMPT: Write pytest unit tests for the /stores/{store_id}/anomalies endpoint in FastAPI, verifying detection of queue spikes, conversion rate drop anomalies, and inactive dead zones.
# CHANGES MADE: Overrode the database session engine to support file-based SQLite database.

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base
import app.anomalies as anomalies_module

# Test SQLite file database setup
TEST_DATABASE_URL = "sqlite:///./test_anomalies.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr(anomalies_module, "SessionLocal", TestSessionLocal)
    yield
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.exists("test_anomalies.db"):
        try:
            os.remove("test_anomalies.db")
        except Exception:
            pass


def test_anomalies_no_data():
    client = TestClient(app)
    res = client.get("/stores/TEST_STORE/anomalies")
    assert res.status_code == 200
    data = res.json()
    assert len(data["anomalies"]) == 0


def test_anomalies_queue_spike():
    client = TestClient(app)
    db = TestSessionLocal()
    from app.db_models import EventDB
    
    # Add 6 people currently in the queue zone (entered but not exited)
    for i in range(6):
        db.add(EventDB(
            event_id=f"evt_{i}", store_id="TEST_STORE", camera_id="CAM_5",
            visitor_id=f"VIS_{i:03d}", event_type="BILLING_QUEUE_JOIN", timestamp="2026-06-03T14:00:00Z",
            zone_id="BILLING", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
        ))
    db.commit()
    db.close()

    res = client.get("/stores/TEST_STORE/anomalies")
    assert res.status_code == 200
    data = res.json()
    
    # Assert queue spike anomaly exists and has correct severity
    q_spikes = [a for a in data["anomalies"] if a["anomaly_id"] == "BILLING_QUEUE_SPIKE"]
    assert len(q_spikes) == 1
    assert q_spikes[0]["severity"] == "CRITICAL"
    assert "Open another cash counter" in q_spikes[0]["suggested_action"]


def test_anomalies_conversion_drop():
    client = TestClient(app)
    db = TestSessionLocal()
    from app.db_models import EventDB
    
    # If we have visitors but 0 conversions, it should trigger CONVERSION_DROP
    db.add(EventDB(
        event_id="e1", store_id="TEST_STORE", camera_id="CAM_3",
        visitor_id="VIS_001", event_type="ENTRY", timestamp="2026-06-03T14:00:00Z",
        dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e2", store_id="TEST_STORE", camera_id="CAM_5",
        visitor_id="VIS_001", event_type="BILLING_QUEUE_JOIN", timestamp="2026-06-03T14:01:00Z",
        zone_id="BILLING", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    # No POS transaction is inserted, meaning conversion rate = 0%
    db.commit()
    db.close()

    res = client.get("/stores/TEST_STORE/anomalies")
    assert res.status_code == 200
    data = res.json()
    
    # Assert conversion drop anomaly is reported as critical
    conv_drops = [a for a in data["anomalies"] if a["anomaly_id"] == "CONVERSION_DROP"]
    assert len(conv_drops) == 1
    assert conv_drops[0]["severity"] == "CRITICAL"
    assert "Review price tags" in conv_drops[0]["suggested_action"]
