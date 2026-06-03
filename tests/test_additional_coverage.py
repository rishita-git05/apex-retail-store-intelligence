# PROMPT: Write additional pytest integration tests for Store Intelligence API to cover `/stores/{store_id}/funnel` endpoint, `/health` endpoint stale warnings, lifespan database populators, and request logging middleware, ensuring statement coverage >70%.
# CHANGES MADE: Implemented mocks and database population to hit all uncovered branch statements in app/funnel.py, app/health.py, and app/main.py.

import os
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app, populate_pos_data, populate_events_data
from app.database import Base
import app.funnel as funnel_module
import app.health as health_module
import app.main as main_module

TEST_DATABASE_URL = "sqlite:///./test_coverage.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Overrides app DB session creator to use the test database file."""
    Base.metadata.create_all(bind=test_engine)
    
    # Override SessionLocal across all modules
    monkeypatch.setattr(funnel_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(health_module, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(main_module, "SessionLocal", TestSessionLocal)
    
    yield
    
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    if os.path.exists("test_coverage.db"):
        try:
            os.remove("test_coverage.db")
        except Exception:
            pass


def test_funnel_endpoint_empty():
    client = TestClient(app)
    # Test for normal store
    res = client.get("/stores/TEST_STORE/funnel")
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "TEST_STORE"
    assert data["overall_conversion"] == 0.0
    for stage in data["stages"]:
        assert stage["count"] == 0


def test_funnel_endpoint_populated():
    client = TestClient(app)
    db = TestSessionLocal()
    from app.db_models import EventDB, POSTransactionDB
    
    # Visitor 1: Entry -> Zone Visit -> Queue -> Purchase
    db.add(EventDB(
        event_id="e1", store_id="TEST_STORE", camera_id="CAM_3",
        visitor_id="VIS_001", event_type="ENTRY", timestamp="2026-06-03T14:00:00Z",
        dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e2", store_id="TEST_STORE", camera_id="CAM_1",
        visitor_id="VIS_001", event_type="ZONE_ENTER", timestamp="2026-06-03T14:00:10Z",
        zone_id="MINIMALIST", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e3", store_id="TEST_STORE", camera_id="CAM_5",
        visitor_id="VIS_001", event_type="BILLING_QUEUE_JOIN", timestamp="2026-06-03T14:01:00Z",
        zone_id="BILLING", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(POSTransactionDB(
        order_id="tx_1", store_id="TEST_STORE", timestamp="2026-06-03T14:03:00Z", total_amount=200.0
    ))
    
    # Visitor 2: Entry -> Zone Visit -> Queue -> No Purchase (Transaction too late)
    db.add(EventDB(
        event_id="e4", store_id="TEST_STORE", camera_id="CAM_3",
        visitor_id="VIS_002", event_type="ENTRY", timestamp="2026-06-03T14:15:00Z",
        dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e5", store_id="TEST_STORE", camera_id="CAM_1",
        visitor_id="VIS_002", event_type="ZONE_ENTER", timestamp="2026-06-03T14:16:00Z",
        zone_id="MINIMALIST", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(EventDB(
        event_id="e6", store_id="TEST_STORE", camera_id="CAM_5",
        visitor_id="VIS_002", event_type="BILLING_QUEUE_JOIN", timestamp="2026-06-03T14:20:00Z",
        zone_id="BILLING", dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.add(POSTransactionDB(
        order_id="tx_2", store_id="TEST_STORE", timestamp="2026-06-03T14:10:00Z", total_amount=100.0  # Before queue join (not after)
    ))
    
    # Visitor 3: Staff member (should be ignored in funnel)
    db.add(EventDB(
        event_id="e7", store_id="TEST_STORE", camera_id="CAM_3",
        visitor_id="STAFF_01", event_type="ENTRY", timestamp="2026-06-03T14:00:00Z",
        dwell_ms=0, is_staff=True, confidence=1.0, metadata_json="{}"
    ))
    
    db.commit()
    db.close()
    
    res = client.get("/stores/TEST_STORE/funnel")
    assert res.status_code == 200
    data = res.json()
    assert data["store_id"] == "TEST_STORE"
    
    stages = {s["stage"]: s for s in data["stages"]}
    assert stages["1. Entry"]["count"] == 2      # VIS_001, VIS_002 (staff ignored)
    assert stages["2. Zone Visit"]["count"] == 2  # both visited MINIMALIST
    assert stages["3. Billing Queue"]["count"] == 2 # both joined queue
    assert stages["4. Purchase"]["count"] == 1    # only VIS_001 converted (tx within 5 mins)
    assert data["overall_conversion"] == 50.0     # 1 / 2 * 100


def test_funnel_database_unavailability(monkeypatch):
    client = TestClient(app)
    
    def mock_db_raise():
        raise Exception("Database Connection Failure")
        
    monkeypatch.setattr(funnel_module, "SessionLocal", mock_db_raise)
    
    res = client.get("/stores/STORE_BLR_002/funnel")
    assert res.status_code == 503
    assert res.json()["status"] == "error"
    assert "unavailable" in res.json()["message"]


def test_funnel_endpoint_internal_error(monkeypatch):
    client = TestClient(app)
    
    # Force a query exception
    def mock_session_query(*args, **kwargs):
        raise Exception("Query Execution Timeout")
        
    class MockSession:
        def query(self, *args, **kwargs):
            return mock_session_query()
        def close(self):
            pass
            
    monkeypatch.setattr(funnel_module, "SessionLocal", lambda: MockSession())
    
    res = client.get("/stores/STORE_BLR_002/funnel")
    assert res.status_code == 500
    assert "failed" in res.json()["message"]


def test_health_stale_feed_warning():
    client = TestClient(app)
    db = TestSessionLocal()
    from app.db_models import EventDB
    
    # Inject a stale event: timestamp is more than 10 minutes ago
    # We use UTC timestamp
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    stale_time_str = stale_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    db.add(EventDB(
        event_id="stale_evt", store_id="STORE_BLR_002", camera_id="CAM_3",
        visitor_id="VIS_999", event_type="ENTRY", timestamp=stale_time_str,
        dwell_ms=0, is_staff=False, confidence=1.0, metadata_json="{}"
    ))
    db.commit()
    db.close()
    
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "degraded"
    assert "warnings" in data
    assert any("STALE_FEED" in w for w in data["warnings"])
    assert data["feed_status"]["STORE_BLR_002"]["status"] == "stale"


def test_health_check_database_unavailability(monkeypatch):
    client = TestClient(app)
    
    def mock_db_raise():
        raise Exception("Database Connection Refused")
        
    monkeypatch.setattr(health_module, "SessionLocal", mock_db_raise)
    
    res = client.get("/health")
    assert res.status_code == 503
    assert res.json()["status"] == "unhealthy"
    assert res.json()["database"] == "disconnected"


def test_health_check_internal_error(monkeypatch):
    client = TestClient(app)
    
    class MockSession:
        def execute(self, *args, **kwargs):
            pass
        def query(self, *args, **kwargs):
            raise Exception("Mock query execution exception")
        def close(self):
            pass
            
    monkeypatch.setattr(health_module, "SessionLocal", lambda: MockSession())
    
    res = client.get("/health")
    assert res.status_code == 500
    assert "failed" in res.json()["message"]


def test_main_populate_pos_data_exception(monkeypatch):
    # Test error path in populate_pos_data
    # We force an error by making bulk_save_objects raise an exception
    class MockSession:
        def query(self, *args, **kwargs):
            class MockQuery:
                def count(self):
                    return 0
            return MockQuery()
        def bulk_save_objects(self, *args, **kwargs):
            raise Exception("SQL Execution Exception")
        def rollback(self):
            # Verify rollback is called
            self.rolled_back = True
        def close(self):
            pass
            
    mock_session = MockSession()
    monkeypatch.setattr(main_module, "SessionLocal", lambda: mock_session)
    
    # This should run without raising exception (handled internally)
    populate_pos_data()
    assert getattr(mock_session, "rolled_back", False) is True


def test_main_populate_events_data_exception(monkeypatch):
    # Test error path in populate_events_data
    class MockSession:
        def query(self, *args, **kwargs):
            class MockQuery:
                def count(self):
                    return 0
            return MockQuery()
        def bulk_save_objects(self, *args, **kwargs):
            raise Exception("SQL Execution Exception")
        def rollback(self):
            self.rolled_back = True
        def close(self):
            pass
            
    mock_session = MockSession()
    monkeypatch.setattr(main_module, "SessionLocal", lambda: mock_session)
    
    # This should run without raising exception (handled internally)
    populate_events_data()
    assert getattr(mock_session, "rolled_back", False) is True


def test_middleware_logging():
    client = TestClient(app)
    res = client.get("/stores/STORE_BLR_002/metrics")
    assert res.status_code == 200
    assert "X-Trace-ID" in res.headers
