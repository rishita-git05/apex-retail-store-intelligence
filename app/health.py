from datetime import datetime, timezone
from fastapi import APIRouter, Response, status
from sqlalchemy import func

from app.database import SessionLocal
from app.db_models import EventDB
from app.metrics import parse_iso_timestamp

router = APIRouter()


@router.get("/health")
def health_check(response: Response):
    """Exposes API status and monitors lag between system clock and latest ingested feed event."""
    try:
        db = SessionLocal()
        # Verify db connection
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": str(e)
        }

    try:
        # Get latest event per store
        stores_feed = (
            db.query(EventDB.store_id, func.max(EventDB.timestamp))
            .group_by(EventDB.store_id)
            .all()
        )
        
        feed_status = {}
        warnings = []
        
        current_utc = datetime.now(timezone.utc)
        
        for store_id, max_ts_str in stores_feed:
            if not max_ts_str:
                feed_status[store_id] = {"last_event": None, "lag_seconds": None, "status": "no_data"}
                continue
                
            last_dt = parse_iso_timestamp(max_ts_str)
            # Ensure timezone info is set (assume UTC from 'Z' suffix)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
                
            lag = (current_utc - last_dt).total_seconds()
            
            # If lag is negative (due to simulated future events), cap at 0
            lag_sec = max(0.0, lag)
            
            status_text = "active"
            # 10 minutes stale feed limit (600 seconds)
            if lag_sec > 600.0:
                status_text = "stale"
                warnings.append(f"STALE_FEED warning for store {store_id}: last event ingested was {int(lag_sec // 60)} minutes ago.")
                
            feed_status[store_id] = {
                "last_event_timestamp": max_ts_str,
                "lag_seconds": int(lag_sec),
                "status": status_text
            }

        db.close()
        
        result = {
            "status": "healthy" if not warnings else "degraded",
            "database": "connected",
            "feed_status": feed_status
        }
        if warnings:
            result["warnings"] = warnings
            
        return result
        
    except Exception as e:
        db.close()
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "status": "error",
            "message": f"Health check failed: {str(e)}"
        }