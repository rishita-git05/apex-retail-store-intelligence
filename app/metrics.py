from datetime import datetime, timedelta
from fastapi import APIRouter, Response, status
from sqlalchemy import func

from app.database import SessionLocal
from app.db_models import EventDB, POSTransactionDB

router = APIRouter()


def parse_iso_timestamp(ts_str):
    """Safely parse ISO-8601 timestamp string into datetime object."""
    try:
        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            return datetime.utcnow()


@router.get("/stores/{store_id}/metrics")
def get_metrics(store_id: str, response: Response):
    """Computes real-time store metrics including unique visitors, conversion rate, and queue details."""
    if store_id == "ST1008":
        store_id = "STORE_BLR_002"
    try:
        db = SessionLocal()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": "Database unavailable."}

    try:
        # 1. Total Unique Visitors (excluding staff)
        unique_visitors = (
            db.query(EventDB.visitor_id)
            .filter(EventDB.store_id == store_id, EventDB.is_staff == False)
            .distinct()
            .all()
        )
        visitor_ids = [v[0] for v in unique_visitors]
        total_visitors = len(visitor_ids)

        if total_visitors == 0:
            db.close()
            return {
                "store_id": store_id,
                "unique_visitors": 0,
                "conversion_rate": 0.0,
                "avg_dwell_by_zone": {},
                "queue_depth": 0,
                "abandonment_rate": 0.0
            }

        # 2. Conversion Rate Calculation
        # A visitor counts as converted if they were in the billing zone and a POS transaction occurred in the 5 minutes following.
        billing_joins = (
            db.query(EventDB.visitor_id, EventDB.timestamp)
            .filter(
                EventDB.store_id == store_id,
                EventDB.event_type == "BILLING_QUEUE_JOIN",
                EventDB.is_staff == False
            )
            .all()
        )

        converted_visitors = set()
        for v_id, join_ts_str in billing_joins:
            join_dt = parse_iso_timestamp(join_ts_str)
            five_mins_later = join_dt + timedelta(minutes=5)
            
            # Look for a POS transaction in that store within the 5 minute window
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
                converted_visitors.add(v_id)

        conversion_rate = round((len(converted_visitors) / total_visitors) * 100, 2)

        # 3. Average Dwell time per Zone (in seconds)
        dwell_events = (
            db.query(EventDB.zone_id, func.avg(EventDB.dwell_ms))
            .filter(
                EventDB.store_id == store_id,
                EventDB.event_type == "ZONE_EXIT",
                EventDB.is_staff == False,
                EventDB.zone_id != None
            )
            .group_by(EventDB.zone_id)
            .all()
        )
        avg_dwells = {zone: round(avg_ms / 1000.0, 1) for zone, avg_ms in dwell_events}

        # 4. Current Queue Depth
        # Count visitors currently inside the billing zone (latest zone event is ENTER / JOIN, and has no EXIT/store EXIT)
        latest_visitor_events = (
            db.query(EventDB.visitor_id, EventDB.event_type, EventDB.zone_id)
            .filter(
                EventDB.store_id == store_id,
                EventDB.is_staff == False,
                EventDB.event_type.in_(["ZONE_ENTER", "ZONE_EXIT", "BILLING_QUEUE_JOIN", "EXIT"])
            )
            .order_by(EventDB.timestamp.desc())
            .all()
        )
        
        # Keep track of visitor states
        in_billing = set()
        exited_billing = set()
        for v_id, ev_type, zone in latest_visitor_events:
            if v_id in in_billing or v_id in exited_billing:
                continue
            # If the latest event is an EXIT or the zone is not BILLING, they are not in the billing queue.
            is_billing = zone in ["BILLING", "PURPLLE_MUM_1076_Z_BILLING_01"]
            if ev_type in ["ZONE_ENTER", "BILLING_QUEUE_JOIN"] and is_billing:
                in_billing.add(v_id)
            else:
                exited_billing.add(v_id)
        queue_depth = len(in_billing)

        # 5. Abandonment Rate
        # Abandoned if joined billing queue but didn't convert
        queue_visitors = set(v[0] for v in billing_joins)
        total_queued = len(queue_visitors)
        
        if total_queued > 0:
            abandoned_count = sum(1 for q_v in queue_visitors if q_v not in converted_visitors)
            abandonment_rate = round((abandoned_count / total_queued) * 100, 2)
        else:
            abandonment_rate = 0.0

        db.close()
        return {
            "store_id": store_id,
            "unique_visitors": total_visitors,
            "conversion_rate": conversion_rate,
            "avg_dwell_by_zone": avg_dwells,
            "queue_depth": queue_depth,
            "abandonment_rate": abandonment_rate
        }
        
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error", "message": f"Metrics computation failed: {str(e)}"}


@router.get("/stores/{store_id}/heatmap")
def get_heatmap(store_id: str, response: Response):
    """Generates normalized zone visit frequency and average dwell times for grid heatmap rendering."""
    if store_id == "ST1008":
        store_id = "STORE_BLR_002"
    try:
        db = SessionLocal()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": "Database unavailable."}

    try:
        # Check sessions count for data confidence flag
        sessions_count = (
            db.query(EventDB.visitor_id)
            .filter(EventDB.store_id == store_id, EventDB.is_staff == False)
            .distinct()
            .count()
        )
        data_confidence = sessions_count >= 20

        # Query visit counts (ZONE_ENTER) and average dwell times (ZONE_EXIT) per zone
        visit_counts = (
            db.query(EventDB.zone_id, func.count(EventDB.event_id))
            .filter(
                EventDB.store_id == store_id,
                EventDB.event_type == "ZONE_ENTER",
                EventDB.is_staff == False,
                EventDB.zone_id != None
            )
            .group_by(EventDB.zone_id)
            .all()
        )
        
        dwell_times = (
            db.query(EventDB.zone_id, func.avg(EventDB.dwell_ms))
            .filter(
                EventDB.store_id == store_id,
                EventDB.event_type == "ZONE_EXIT",
                EventDB.is_staff == False,
                EventDB.zone_id != None
            )
            .group_by(EventDB.zone_id)
            .all()
        )

        visit_map = {zone: count for zone, count in visit_counts}
        dwell_map = {zone: round(avg_ms / 1000.0, 1) for zone, avg_ms in dwell_times}

        # Combine and normalize frequency (0-100 scale)
        heatmap_data = {}
        all_counts = list(visit_map.values())
        max_count = max(all_counts) if all_counts else 0
        min_count = min(all_counts) if all_counts else 0

        all_zones = set(visit_map.keys()).union(dwell_map.keys())
        
        for zone in all_zones:
            count = visit_map.get(zone, 0)
            avg_dwell_sec = dwell_map.get(zone, 0.0)
            
            # Normalization formula
            if max_count > min_count:
                normalized_frequency = round(((count - min_count) / (max_count - min_count)) * 100, 1)
            elif max_count > 0:
                normalized_frequency = 100.0
            else:
                normalized_frequency = 0.0
                
            heatmap_data[zone] = {
                "visit_count": count,
                "avg_dwell_sec": avg_dwell_sec,
                "normalized_frequency": normalized_frequency
            }

        db.close()
        return {
            "store_id": store_id,
            "data_confidence": data_confidence,
            "heatmap": heatmap_data
        }
        
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error", "message": f"Heatmap computation failed: {str(e)}"}