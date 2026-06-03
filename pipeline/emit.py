import uuid
from datetime import datetime, timedelta

# Constants for entry detection
ENTRY_LINE_Y = 350

class EventEmitter:
    """Generates structured retail behavior events from visitor tracking coordinates."""

    def __init__(self, store_id="STORE_BLR_002"):
        self.store_id = store_id
        
        # State tracking
        self.last_y_position = {}     # visitor_id -> y_center
        self.current_zones = {}       # visitor_id -> {zone_id, enter_time, last_dwell_time}
        self.session_sequences = {}   # visitor_id -> seq_num
        self.exited_visitors = set()   # set of visitor_ids that have exited the store
        self.active_billing_queue = [] # list of active visitor_ids in billing zone

    def get_session_seq(self, visitor_id):
        """Get the next ordinal position of an event in a visitor's session."""
        seq = self.session_sequences.get(visitor_id, 0) + 1
        self.session_sequences[visitor_id] = seq
        return seq

    def format_timestamp(self, timestamp_sec):
        """Format simulated seconds offset into a realistic ISO-8601 UTC string.
        
        Simulates events happening on June 3rd, 2026.
        """
        base_time = datetime(2026, 6, 3, 14, 0, 0)  # Starts at 2 PM
        event_time = base_time + timedelta(seconds=timestamp_sec)
        return event_time.strftime("%Y-%m-%dT%H:%M:%SZ")

    def create_event(self, visitor_id, camera_id, event_type, timestamp_sec, zone_id=None, dwell_ms=0, is_staff=False, confidence=1.0, metadata=None):
        """Factory method to construct a compliant event dictionary."""
        if metadata is None:
            metadata = {}
            
        metadata["session_seq"] = self.get_session_seq(visitor_id)
        
        return {
            "event_id": str(uuid.uuid4()),
            "store_id": self.store_id,
            "camera_id": camera_id,
            "visitor_id": visitor_id,
            "event_type": event_type,
            "timestamp": self.format_timestamp(timestamp_sec),
            "zone_id": zone_id,
            "dwell_ms": int(dwell_ms),
            "is_staff": is_staff,
            "confidence": round(float(confidence), 2),
            "metadata": metadata
        }

    def process_entry_exit(self, visitor_id, center_y, is_staff, confidence, timestamp_sec):
        """Process tracking in CAM 3 to detect ENTRY and EXIT events."""
        events = []
        
        # If this is the first time we see the visitor
        if visitor_id not in self.last_y_position:
            self.last_y_position[visitor_id] = center_y
            
            # If they start below the line, they entered
            if center_y > ENTRY_LINE_Y:
                event_type = "REENTRY" if visitor_id in self.exited_visitors else "ENTRY"
                events.append(self.create_event(
                    visitor_id=visitor_id,
                    camera_id="CAM_3",
                    event_type=event_type,
                    timestamp_sec=timestamp_sec,
                    is_staff=is_staff,
                    confidence=confidence
                ))
            return events

        prev_y = self.last_y_position[visitor_id]
        self.last_y_position[visitor_id] = center_y

        # Crossing line downwards: ENTRY
        if prev_y <= ENTRY_LINE_Y and center_y > ENTRY_LINE_Y:
            event_type = "REENTRY" if visitor_id in self.exited_visitors else "ENTRY"
            events.append(self.create_event(
                visitor_id=visitor_id,
                camera_id="CAM_3",
                event_type=event_type,
                timestamp_sec=timestamp_sec,
                is_staff=is_staff,
                confidence=confidence
            ))
            
            # Remove from exited if they re-entered
            self.exited_visitors.discard(visitor_id)

        # Crossing line upwards: EXIT
        elif prev_y > ENTRY_LINE_Y and center_y <= ENTRY_LINE_Y:
            events.append(self.create_event(
                visitor_id=visitor_id,
                camera_id="CAM_3",
                event_type="EXIT",
                timestamp_sec=timestamp_sec,
                is_staff=is_staff,
                confidence=confidence
            ))
            self.exited_visitors.add(visitor_id)
            
            # Trigger zone exit if they were in a zone
            if visitor_id in self.current_zones:
                exit_events = self.exit_zone(visitor_id, timestamp_sec, is_staff, confidence, "CAM_3")
                events.extend(exit_events)

        return events

    def is_billing_zone(self, zone_id):
        """Check if a zone is a billing queue zone."""
        return zone_id in ["BILLING", "PURPLLE_MUM_1076_Z_BILLING_01"]

    def map_coords_to_zone(self, camera_id, center_x):
        """Map bounding box horizontal center to store shelf brand zones."""
        if self.store_id == "ST1076":
            if camera_id == "CAM_1":
                # Mumbai Store: Sliced into 3 zones
                if center_x < 320:
                    return "PURPLLE_MUM_1076_Z01"  # Left Shelf
                elif center_x < 640:
                    return "PURPLLE_MUM_1076_Z02"  # Center Display
                else:
                    return "PURPLLE_MUM_1076_Z03"  # Lipstick Aisle
            elif camera_id == "CAM_5":
                if center_x < 1000:
                    return "PURPLLE_MUM_1076_Z_BILLING_01"
            return None

        if camera_id == "CAM_1":
            # Sliced into 8 zones (240px wide each)
            idx = int(center_x // 240)
            zones = [
                "EB_KOREAN", "THE_FACE_SHOP", "GOOD_VIBES", "DERMDOC",
                "MINIMALIST", "AQUALOGICA", "LAKME_SKIN", "ACCESSORIES"
            ]
            if 0 <= idx < len(zones):
                return zones[idx]
                
        elif camera_id == "CAM_2":
            # Sliced into 10 zones (192px wide each)
            idx = int(center_x // 192)
            zones = [
                "MAYBELLINE", "FACES_CANADA", "LAKME", "COLORBAR_SUGAR",
                "SWISS_BEAUTY", "RENEE", "NY_BAE", "ALPS_GOODNESS",
                "STREAX", "PMU"
            ]
            if 0 <= idx < len(zones):
                return zones[idx]
                
        elif camera_id == "CAM_5":
            # Billing zone on the left
            if center_x < 1000:
                return "BILLING"
                
        return None

    def process_zone_movement(self, visitor_id, camera_id, center_x, is_staff, confidence, timestamp_sec):
        """Process movement inside CAM 1, 2, and 5 to generate zone events."""
        events = []
        
        # Don't track zone events for staff (as per the metrics filtering requirement)
        if is_staff:
            return events

        zone_id = self.map_coords_to_zone(camera_id, center_x)
        
        # If the visitor is not currently recorded in any zone
        if visitor_id not in self.current_zones:
            if zone_id is not None:
                # Enter new zone
                self.current_zones[visitor_id] = {
                    "zone_id": zone_id,
                    "enter_time": timestamp_sec,
                    "last_dwell_time": timestamp_sec
                }
                events.append(self.create_event(
                    visitor_id=visitor_id,
                    camera_id=camera_id,
                    event_type="ZONE_ENTER",
                    timestamp_sec=timestamp_sec,
                    zone_id=zone_id,
                    confidence=confidence
                ))
                
                # If they entered billing zone
                if self.is_billing_zone(zone_id):
                    q_depth = len(self.active_billing_queue)
                    if visitor_id not in self.active_billing_queue:
                        self.active_billing_queue.append(visitor_id)
                    events.append(self.create_event(
                        visitor_id=visitor_id,
                        camera_id=camera_id,
                        event_type="BILLING_QUEUE_JOIN",
                        timestamp_sec=timestamp_sec,
                        zone_id=zone_id,
                        confidence=confidence,
                        metadata={"queue_depth": q_depth}
                    ))
            return events

        current = self.current_zones[visitor_id]
        
        # Visitor shifted to a different zone or walked out of zones
        if current["zone_id"] != zone_id:
            # First, exit the previous zone
            exit_events = self.exit_zone(visitor_id, timestamp_sec, is_staff, confidence, camera_id)
            events.extend(exit_events)
            
            # Enter new zone if applicable
            if zone_id is not None:
                self.current_zones[visitor_id] = {
                    "zone_id": zone_id,
                    "enter_time": timestamp_sec,
                    "last_dwell_time": timestamp_sec
                }
                events.append(self.create_event(
                    visitor_id=visitor_id,
                    camera_id=camera_id,
                    event_type="ZONE_ENTER",
                    timestamp_sec=timestamp_sec,
                    zone_id=zone_id,
                    confidence=confidence
                ))
                
                if self.is_billing_zone(zone_id):
                    q_depth = len(self.active_billing_queue)
                    if visitor_id not in self.active_billing_queue:
                        self.active_billing_queue.append(visitor_id)
                    events.append(self.create_event(
                        visitor_id=visitor_id,
                        camera_id=camera_id,
                        event_type="BILLING_QUEUE_JOIN",
                        timestamp_sec=timestamp_sec,
                        zone_id=zone_id,
                        confidence=confidence,
                        metadata={"queue_depth": q_depth}
                    ))
        else:
            # Continuous dwell tracking: check if 30s has passed since last DWELL event
            dwell_duration = timestamp_sec - current["last_dwell_time"]
            if dwell_duration >= 30.0:
                total_dwell_ms = (timestamp_sec - current["enter_time"]) * 1000
                events.append(self.create_event(
                    visitor_id=visitor_id,
                    camera_id=camera_id,
                    event_type="ZONE_DWELL",
                    timestamp_sec=timestamp_sec,
                    zone_id=current["zone_id"],
                    dwell_ms=total_dwell_ms,
                    confidence=confidence
                ))
                current["last_dwell_time"] = timestamp_sec

        return events

    def exit_zone(self, visitor_id, timestamp_sec, is_staff, confidence, camera_id):
        """Helper to process zone exiting and return exit events."""
        events = []
        if visitor_id in self.current_zones:
            current = self.current_zones.pop(visitor_id)
            dwell_ms = (timestamp_sec - current["enter_time"]) * 1000
            
            events.append(self.create_event(
                visitor_id=visitor_id,
                camera_id=camera_id,
                event_type="ZONE_EXIT",
                timestamp_sec=timestamp_sec,
                zone_id=current["zone_id"],
                dwell_ms=dwell_ms,
                confidence=confidence
            ))
            
            if self.is_billing_zone(current["zone_id"]):
                if visitor_id in self.active_billing_queue:
                    self.active_billing_queue.remove(visitor_id)
                    
        return events

    def purge_inactive_visitors(self, active_global_ids, timestamp_sec):
        """Clean up visitors that disappeared from camera feeds, triggering zone exits."""
        events = []
        for visitor_id in list(self.current_zones.keys()):
            if visitor_id not in active_global_ids:
                # Disappeared, trigger exit
                exit_events = self.exit_zone(visitor_id, timestamp_sec, False, 1.0, "CAM_UNKNOWN")
                events.extend(exit_events)
        return events