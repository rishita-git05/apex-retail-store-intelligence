# PROMPT: Write pytest integration tests for the /stores/{store_id}/metrics and /stores/{store_id}/heatmap endpoints in FastAPI, asserting database session integration and transaction correlation.
# CHANGES MADE: Overrode database engine with temporary SQLite file instance to avoid connection isolation issues of in-memory sqlite.

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base
import app.metrics as metrics_module
import app.ingestion as ingestion_module
import app.funnel as funnel_module
import app.anomalies as anomalies_module

# Setup a file-based SQLite database for testing to avoid memory connection isolation
TEST_DATABASE_URL = "sqlite:///./test_metrics.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Overrides app DB session creator to use the test database file."""
    # Ensure tables are created
    Base.metadata.create_all(bind=test_engine)
    
    # Override SessionLocal across all modules
    monkeypatch.setattr(metrics_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(ingestion_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(funnel_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(anomalies_module, "SessionLocal", TestSessionLocal)
    
    yield
    
    # Teardown: drop tables and delete file
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.exists("test_metrics.db"):
        try:
            os.remove("test_metrics.db")
        except Exception:
            pass


def test_metrics_endpoint():
    client = TestClient(app)
    
    # 1. Test empty store metrics
    res_empty = client.get("/stores/TEST_STORE/metrics")
    assert res_empty.status_code == 200
    data_empty = res_empty.json()
    assert data_empty["unique_visitors"] == 0
    assert data_empty["conversion_rate"] == 0.0

    # 2. Ingest some events to test metrics calculation
    db = TestSessionLocal()
    from app.db_models import EventDB, POSTransactionDB
    
    # Insert entry events
    db.add(EventDB(
        event_id="e1", store_id="TEST_STORE", camera_id="CAM_3",
        visitor_id="VIS_001", event_type="ENTRY", timestamp="2026-06-03T14:00:00Z",
        dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    # Insert zone events
    db.add(EventDB(
        event_id="e2", store_id="TEST_STORE", camera_id="CAM_1",
        visitor_id="VIS_001", event_type="ZONE_ENTER", timestamp="2026-06-03T14:00:10Z",
        zone_id="MINIMALIST", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e3", store_id="TEST_STORE", camera_id="CAM_1",
        visitor_id="VIS_001", event_type="ZONE_EXIT", timestamp="2026-06-03T14:00:40Z",
        zone_id="MINIMALIST", dwell_ms=30000, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    # Insert billing queue join event
    db.add(EventDB(
        event_id="e4", store_id="TEST_STORE", camera_id="CAM_5",
        visitor_id="VIS_001", event_type="BILLING_QUEUE_JOIN", timestamp="2026-06-03T14:01:00Z",
        zone_id="BILLING", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    
    # Insert POS transaction (occurs 2 minutes after queue join, inside the 5-min window)
    db.add(POSTransactionDB(
        order_id="tx_1", store_id="TEST_STORE", timestamp="2026-06-03T14:03:00Z", total_amount=120.0
    ))
    db.commit()
    db.close()

    # Call metrics endpoint
    res = client.get("/stores/TEST_STORE/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 1
    assert data["conversion_rate"] == 100.0
    assert data["avg_dwell_by_zone"]["MINIMALIST"] == 30.0
    assert data["abandonment_rate"] == 0.0


def test_heatmap_endpoint():
    client = TestClient(app)
    db = TestSessionLocal()
    from app.db_models import EventDB
    
    # Populate events in the test database
    db.add(EventDB(
        event_id="e5", store_id="TEST_STORE", camera_id="CAM_1",
        visitor_id="VIS_001", event_type="ZONE_ENTER", timestamp="2026-06-03T14:00:00Z",
        zone_id="MINIMALIST", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e6", store_id="TEST_STORE", camera_id="CAM_1",
        visitor_id="VIS_001", event_type="ZONE_EXIT", timestamp="2026-06-03T14:00:30Z",
        zone_id="MINIMALIST", dwell_ms=30000, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.commit()
    db.close()

    res = client.get("/stores/TEST_STORE/heatmap")
    assert res.status_code == 200
    data = res.json()
    assert data["data_confidence"] is False  # visitor sessions count is 1 (<20)
    assert "MINIMALIST" in data["heatmap"]
    assert data["heatmap"]["MINIMALIST"]["visit_count"] == 1
    assert data["heatmap"]["MINIMALIST"]["avg_dwell_sec"] == 30.0
    assert data["heatmap"]["MINIMALIST"]["normalized_frequency"] == 100.0


def test_store2_metrics():
    client = TestClient(app)
    db = TestSessionLocal()
    from app.db_models import EventDB, POSTransactionDB
    
    # Ingest Store 2 events
    db.add(EventDB(
        event_id="s2_e1", store_id="ST1076", camera_id="CAM_3",
        visitor_id="VIS_S2_001", event_type="ENTRY", timestamp="2026-06-03T14:00:00Z",
        dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="s2_e2", store_id="ST1076", camera_id="CAM_1",
        visitor_id="VIS_S2_001", event_type="ZONE_ENTER", timestamp="2026-06-03T14:00:10Z",
        zone_id="PURPLLE_MUM_1076_Z01", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="s2_e3", store_id="ST1076", camera_id="CAM_1",
        visitor_id="VIS_S2_001", event_type="ZONE_EXIT", timestamp="2026-06-03T14:00:40Z",
        zone_id="PURPLLE_MUM_1076_Z01", dwell_ms=30000, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="s2_e4", store_id="ST1076", camera_id="CAM_5",
        visitor_id="VIS_S2_001", event_type="BILLING_QUEUE_JOIN", timestamp="2026-06-03T14:01:00Z",
        zone_id="PURPLLE_MUM_1076_Z_BILLING_01", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    
    # Store 2 transaction
    db.add(POSTransactionDB(
        order_id="tx_s2_1", store_id="ST1076", timestamp="2026-06-03T14:03:00Z", total_amount=150.0
    ))
    db.commit()
    db.close()
    
    res = client.get("/stores/ST1076/metrics")
    assert res.status_code == 200
    data = res.json()
    assert data["unique_visitors"] == 1
    assert data["conversion_rate"] == 100.0
    assert data["avg_dwell_by_zone"]["PURPLLE_MUM_1076_Z01"] == 30.0

