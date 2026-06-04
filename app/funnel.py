from datetime import datetime, timedelta
from fastapi import APIRouter, Response, status
from app.database import SessionLocal
from app.db_models import EventDB, POSTransactionDB
from app.metrics import parse_iso_timestamp

router = APIRouter()


@router.get("/stores/{store_id}/funnel")
def get_funnel(store_id: str, response: Response):
    """Computes session-based conversion funnel: Entry -> Zone Visit -> Billing Queue -> Purchase."""
    try:
        db = SessionLocal()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": "Database unavailable."}

    try:
        # 1. Total Entries
        # We query all unique visitor IDs to ensure visitors already inside the store at the start of the video are included
        entries = (
            db.query(EventDB.visitor_id)
            .filter(
                EventDB.store_id == store_id,
                EventDB.is_staff == False
            )
            .distinct()
            .all()
        )
        total_entered = len(entries)
        entered_ids = set(v[0] for v in entries)

        # 2. Zone Visits (any shelf/display zone excluding billing queue)
        zone_visits = (
            db.query(EventDB.visitor_id)
            .filter(
                EventDB.store_id == store_id,
                EventDB.is_staff == False,
                EventDB.event_type == "ZONE_ENTER",
                EventDB.zone_id.notin_(["BILLING", "PURPLLE_MUM_1076_Z_BILLING_01"])
            )
            .distinct()
            .all()
        )
        # Ensure they had entered (validate session integrity)
        visited_ids = set(v[0] for v in zone_visits).intersection(entered_ids)
        total_visited = len(visited_ids)

        # 3. Billing Queue Joins
        billing_joins = (
            db.query(EventDB.visitor_id, EventDB.timestamp)
            .filter(
                EventDB.store_id == store_id,
                EventDB.is_staff == False,
                EventDB.event_type == "BILLING_QUEUE_JOIN"
            )
            .all()
        )
        queued_ids = set(v[0] for v in billing_joins).intersection(entered_ids)
        total_queued = len(queued_ids)

        # 4. Purchases (correlating POS transaction in 5 minute window after queue join)
        purchase_ids = set()
        for v_id, join_ts_str in billing_joins:
            if v_id not in queued_ids:
                continue
                
            join_dt = parse_iso_timestamp(join_ts_str)
            five_mins_later = join_dt + timedelta(minutes=5)
            
            # Look for a POS transaction
            has_tx = (
                db.query(POSTransactionDB.order_id)
                .filter(
                    POSTransactionDB.store_id == store_id,
                    POSTransactionDB.timestamp >= join_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    POSTransactionDB.timestamp <= five_mins_later.strftime("%Y-%m-%dT%H:%M:%SZ")
                )
                .first()
            )
            if has_tx:
                purchase_ids.add(v_id)
        total_purchased = len(purchase_ids)

        # Calculate drop-off percentages
        drop_to_visit = round(((total_entered - total_visited) / total_entered * 100), 2) if total_entered > 0 else 0.0
        drop_to_queue = round(((total_visited - total_queued) / total_visited * 100), 2) if total_visited > 0 else 0.0
        drop_to_buy = round(((total_queued - total_purchased) / total_queued * 100), 2) if total_queued > 0 else 0.0

        db.close()
        return {
            "store_id": store_id,
            "stages": [
                {
                    "stage": "1. Entry",
                    "count": total_entered,
                    "conversion_from_previous": 100.0,
                    "dropoff_from_previous": 0.0
                },
                {
                    "stage": "2. Zone Visit",
                    "count": total_visited,
                    "conversion_from_previous": round((total_visited / total_entered * 100), 2) if total_entered > 0 else 0.0,
                    "dropoff_from_previous": drop_to_visit
                },
                {
                    "stage": "3. Billing Queue",
                    "count": total_queued,
                    "conversion_from_previous": round((total_queued / total_visited * 100), 2) if total_visited > 0 else 0.0,
                    "dropoff_from_previous": drop_to_queue
                },
                {
                    "stage": "4. Purchase",
                    "count": total_purchased,
                    "conversion_from_previous": round((total_purchased / total_queued * 100), 2) if total_queued > 0 else 0.0,
                    "dropoff_from_previous": drop_to_buy
                }
            ],
            "overall_conversion": round((total_purchased / total_entered * 100), 2) if total_entered > 0 else 0.0
        }
        
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error", "message": f"Funnel computation failed: {str(e)}"}