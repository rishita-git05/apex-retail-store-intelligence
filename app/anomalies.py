from datetime import datetime, timedelta
from fastapi import APIRouter, Response, status
from sqlalchemy import func

from app.database import SessionLocal
from app.db_models import EventDB, POSTransactionDB
from app.metrics import parse_iso_timestamp

router = APIRouter()


@router.get("/stores/{store_id}/anomalies")
def get_anomalies(store_id: str, response: Response):
    """Detects active operational anomalies: queue spikes, conversion drops, and dead zones."""
    if store_id == "ST1008":
        store_id = "STORE_BLR_002"
    try:
        db = SessionLocal()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "message": "Database unavailable."}

    try:
        anomalies = []
        
        # --- 1. Queue Spike Detection ---
        # Get active people in billing zone (including EXIT event to accurately detect leaves)
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
        
        in_billing = set()
        exited_billing = set()
        for v_id, ev_type, zone in latest_visitor_events:
            if v_id in in_billing or v_id in exited_billing:
                continue
            is_billing = zone in ["BILLING", "PURPLLE_MUM_1076_Z_BILLING_01"]
            if ev_type in ["ZONE_ENTER", "BILLING_QUEUE_JOIN"] and is_billing:
                in_billing.add(v_id)
            else:
                exited_billing.add(v_id)
        queue_depth = len(in_billing)
        
        if queue_depth > 5:
            anomalies.append({
                "anomaly_id": "BILLING_QUEUE_SPIKE",
                "severity": "CRITICAL",
                "message": f"Critical queue build-up: {queue_depth} customers waiting at the cashier counter.",
                "suggested_action": "Open another cash counter immediately to reduce customer wait time."
            })
        elif queue_depth >= 3:
            anomalies.append({
                "anomaly_id": "BILLING_QUEUE_SPIKE",
                "severity": "WARN",
                "message": f"Queue buildup: {queue_depth} customers waiting.",
                "suggested_action": "Monitor the queue; prepare to deploy a backup cashier if queue depth reaches 6."
            })

        # --- 2. Conversion Drop Detection ---
        # Get conversion rate
        unique_visitors = (
            db.query(EventDB.visitor_id)
            .filter(EventDB.store_id == store_id, EventDB.is_staff == False)
            .distinct()
            .all()
        )
        total_visitors = len(unique_visitors)
        
        if total_visitors > 0:
            billing_joins = (
                db.query(EventDB.visitor_id, EventDB.timestamp)
                .filter(
                    EventDB.store_id == store_id,
                    EventDB.event_type == "BILLING_QUEUE_JOIN",
                    EventDB.is_staff == False
                )
                .all()
            )
            
            converted_count = 0
            for v_id, join_ts_str in billing_joins:
                join_dt = parse_iso_timestamp(join_ts_str)
                five_mins_later = join_dt + timedelta(minutes=5)
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
                    converted_count += 1
                    
            conversion_rate = (converted_count / total_visitors) * 100
            
            # Assume 7-day average baseline is 55.0%
            baseline_conversion = 55.0
            
            if conversion_rate < baseline_conversion * 0.6:
                anomalies.append({
                    "anomaly_id": "CONVERSION_DROP",
                    "severity": "CRITICAL",
                    "message": f"Critical drop in conversion rate: {conversion_rate:.1f}% (Normal baseline: {baseline_conversion}%).",
                    "suggested_action": "Review price tags, promotional displays, or cashier service speed. Heavy cart abandonment detected."
                })
            elif conversion_rate < baseline_conversion * 0.8:
                anomalies.append({
                    "anomaly_id": "CONVERSION_DROP",
                    "severity": "WARN",
                    "message": f"Minor drop in conversion rate: {conversion_rate:.1f}%.",
                    "suggested_action": "Check if floor staff are actively assisting customers or if billing lines are moving slowly."
                })

        # --- 3. Dead Zone Detection ---
        # Defined brand zones in layout dynamically per store
        if store_id == "ST1076":
            defined_zones = ["PURPLLE_MUM_1076_Z01", "PURPLLE_MUM_1076_Z02", "PURPLLE_MUM_1076_Z03"]
        else:
            defined_zones = [
                "EB_KOREAN", "THE_FACE_SHOP", "GOOD_VIBES", "DERMDOC",
                "MINIMALIST", "AQUALOGICA", "LAKME_SKIN", "ACCESSORIES",
                "MAYBELLINE", "FACES_CANADA", "LAKME", "COLORBAR_SUGAR",
                "SWISS_BEAUTY", "RENEE", "NY_BAE", "ALPS_GOODNESS", "STREAX", "PMU"
            ]
        
        # Get latest event in DB to anchor current simulation time
        latest_event = db.query(EventDB.timestamp).order_by(EventDB.timestamp.desc()).first()
        if latest_event:
            latest_time_str = latest_event[0]
            latest_dt = parse_iso_timestamp(latest_time_str)
            
            for zone in defined_zones:
                # Find latest visit to this zone
                last_visit = (
                    db.query(EventDB.timestamp)
                    .filter(
                        EventDB.store_id == store_id,
                        EventDB.zone_id == zone,
                        EventDB.event_type == "ZONE_ENTER",
                        EventDB.is_staff == False
                    )
                    .order_by(EventDB.timestamp.desc())
                    .first()
                )
                
                is_dead = False
                time_diff_sec = 0
                if last_visit:
                    last_visit_dt = parse_iso_timestamp(last_visit[0])
                    time_diff_sec = (latest_dt - last_visit_dt).total_seconds()
                    # Strictly check for 30 minutes of inactivity as required by the problem statement (1800 seconds)
                    if time_diff_sec > 1800.0:
                        is_dead = True
                else:
                    is_dead = True
                    
                if is_dead:
                    anomalies.append({
                        "anomaly_id": "DEAD_ZONE",
                        "severity": "INFO",
                        "message": f"Zone '{zone}' is inactive. Last customer visit was {int(time_diff_sec)} seconds ago (or never visited).",
                        "suggested_action": f"Check product stocking, visual merchandising, and tester quality at the '{zone}' counter."
                    })

        db.close()
        return {
            "store_id": store_id,
            "anomalies": anomalies
        }
        
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error", "message": f"Anomalies computation failed: {str(e)}"}