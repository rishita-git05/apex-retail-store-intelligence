import json
from typing import List
from fastapi import APIRouter, Response, status
from pydantic import ValidationError

from app.models import Event
from app.database import SessionLocal
from app.db_models import EventDB

router = APIRouter()


@router.post("/events/ingest", status_code=status.HTTP_207_MULTI_STATUS)
def ingest_events(raw_events: List[dict], response: Response):
    """Ingests a batch of up to 500 events.
    
    Supports partial success for malformed events and handles database failures gracefully.
    """
    if len(raw_events) > 500:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return {
            "status": "error",
            "message": "Batch size exceeds maximum limit of 500 events."
        }

    # Open DB Session and handle Database unavailable -> HTTP 503
    try:
        db = SessionLocal()
        # Verify db is reachable by executing a simple check
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
    except Exception as db_err:
        print(f"Database connection error: {db_err}")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "error",
            "message": "Database service is temporarily unavailable. Please try again later."
        }

    ingested = 0
    errors = []

    try:
        for idx, raw_event in enumerate(raw_events):
            # 1. Validation
            try:
                # Parse and validate with Pydantic model
                event_obj = Event(**raw_event)
            except ValidationError as val_err:
                errors.append({
                    "index": idx,
                    "event_id": raw_event.get("event_id", "unknown"),
                    "reason": val_err.errors()
                })
                continue
            except Exception as e:
                errors.append({
                    "index": idx,
                    "event_id": raw_event.get("event_id", "unknown"),
                    "reason": f"Parsing error: {str(e)}"
                })
                continue

            # 2. Idempotency check (Deduplication)
            try:
                existing = db.query(EventDB).filter(EventDB.event_id == event_obj.event_id).first()
                if existing:
                    # Treat as successfully processed to ensure idempotency
                    ingested += 1
                    continue
                
                # 3. Store in database
                metadata_str = json.dumps(event_obj.metadata)
                
                db_event = EventDB(
                    event_id=event_obj.event_id,
                    store_id=event_obj.store_id,
                    camera_id=event_obj.camera_id,
                    visitor_id=event_obj.visitor_id,
                    event_type=event_obj.event_type,
                    timestamp=event_obj.timestamp,
                    zone_id=event_obj.zone_id,
                    dwell_ms=event_obj.dwell_ms,
                    is_staff=event_obj.is_staff,
                    confidence=event_obj.confidence,
                    metadata_json=metadata_str
                )
                db.add(db_event)
                ingested += 1
            except Exception as insert_err:
                errors.append({
                    "index": idx,
                    "event_id": event_obj.event_id,
                    "reason": f"Database insert failure: {str(insert_err)}"
                })

        db.commit()
    except Exception as commit_err:
        db.rollback()
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "status": "error",
            "message": f"Transaction commit failed: {str(commit_err)}"
        }
    finally:
        db.close()

    # Determine status and response code
    if len(errors) == len(raw_events) and len(raw_events) > 0:
        response.status_code = status.HTTP_400_BAD_REQUEST
        status_text = "failed"
    elif len(errors) > 0:
        response.status_code = status.HTTP_207_MULTI_STATUS
        status_text = "partial_success"
    else:
        response.status_code = status.HTTP_200_OK
        status_text = "success"

    return {
        "status": status_text,
        "ingested": ingested,
        "failed": len(errors),
        "errors": errors
    }