import os
import json
import cv2
import argparse
from detect import PersonDetector
from tracker import SingleCameraTracker, CrossCameraReIDManager
from emit import EventEmitter

def main():
    parser = argparse.ArgumentParser(description="Run Store Intelligence CV pipeline.")
    parser.add_argument("--store", type=str, default="STORE_BLR_002", help="Store ID to run pipeline for.")
    args = parser.parse_args()
    
    store_id = args.store
    print(f"Initializing Store Intelligence Pipeline for store {store_id}...")
    
    # 1. Initialize detector, trackers, ReID manager, and event emitter
    detector = PersonDetector()
    
    if store_id == "ST1076":
        camera_ids = ["CAM_1", "CAM_3", "CAM_4", "CAM_5"]
    else:
        camera_ids = ["CAM_1", "CAM_2", "CAM_3", "CAM_4", "CAM_5"]
        
    trackers = {cam_id: SingleCameraTracker(cam_id) for cam_id in camera_ids}
    
    reid_manager = CrossCameraReIDManager()
    emitter = EventEmitter(store_id=store_id)
    
    # 2. Open all video files
    video_caps = {}
    fps_rates = {}
    max_frames = {}
    
    for cam_id in camera_ids:
        num = cam_id.split("_")[1]
        video_path = f"data/videos/{store_id}/CAM {num}.mp4"
        
        if not os.path.exists(video_path):
            print(f"Warning: Video file {video_path} not found. Skipping.")
            continue
            
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Warning: Could not open {video_path}. Skipping.")
            continue
            
        video_caps[cam_id] = cap
        fps_rates[cam_id] = cap.get(cv2.CAP_PROP_FPS)
        max_frames[cam_id] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        print(f"Loaded {cam_id} video: {max_frames[cam_id]} frames @ {fps_rates[cam_id]:.2f} FPS")

    if not video_caps:
        print("Error: No video files could be loaded. Exiting.")
        return

    # Determine max simulation duration in seconds (based on longest video)
    durations = [max_frames[cam_id] / fps_rates[cam_id] for cam_id in video_caps]
    max_duration_sec = int(max(durations))
    print(f"Simulating store timeline for {max_duration_sec} seconds...")

    all_events = []

    # 3. Loop over timeline in 1-second steps
    for t_sec in range(max_duration_sec):
        if t_sec % 10 == 0:
            print(f"Processing second {t_sec}/{max_duration_sec}...")
            
        active_global_ids = set()
        
        for cam_id, cap in video_caps.items():
            fps = fps_rates[cam_id]
            frame_idx = int(t_sec * fps)
            
            # Bound check
            if frame_idx >= max_frames[cam_id]:
                continue
                
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue
                
            # Detect people
            detections = detector.detect(frame)
            
            # Update single-camera tracker
            tracked_people = trackers[cam_id].update(detections, frame)
            
            # Map local tracks to global visitor IDs
            for local_id, track in tracked_people.items():
                g_id = reid_manager.get_global_id(local_id, track, t_sec)
                active_global_ids.add(g_id)
                
                # Check for behavior events
                is_staff = track["is_staff"]
                confidence = track["confidence"]
                
                if cam_id == "CAM_3":
                    # Entry/Exit Camera
                    cx, cy = track["center"]
                    entry_events = emitter.process_entry_exit(
                        visitor_id=g_id,
                        center_y=cy,
                        is_staff=is_staff,
                        confidence=confidence,
                        timestamp_sec=t_sec
                    )
                    all_events.extend(entry_events)
                else:
                    # Zone cameras (CAM 1, CAM 2, CAM 5)
                    # Note: CAM 4 is backroom/storage and does not map to brand zones.
                    if cam_id != "CAM_4":
                        cx, cy = track["center"]
                        zone_events = emitter.process_zone_movement(
                            visitor_id=g_id,
                            camera_id=cam_id,
                            center_x=cx,
                            is_staff=is_staff,
                            confidence=confidence,
                            timestamp_sec=t_sec
                        )
                        all_events.extend(zone_events)
                        
        # Purge visitors who left all cameras to emit final ZONE_EXITS
        purge_events = emitter.purge_inactive_visitors(active_global_ids, t_sec)
        all_events.extend(purge_events)

    # 4. Clean up video captures
    for cap in video_caps.values():
        cap.release()

    # 5. Sort all events chronologically by timestamp
    all_events.sort(key=lambda x: x["timestamp"])

    # 6. Write events to data/events.jsonl
    output_path = "data/events.jsonl"
    with open(output_path, "w") as f:
        for ev in all_events:
            f.write(json.dumps(ev) + "\n")

    print(f"Pipeline execution complete. Generated {len(all_events)} events inside {output_path}.")
    
    # 7. Auto-post events to the local FastAPI app
    try:
        import requests
        print("Auto-posting events to API...")
        # Post in batches of 500
        for i in range(0, len(all_events), 500):
            batch = all_events[i:i+500]
            resp = requests.post("http://localhost:8000/events/ingest", json=batch)
            print(f"Posted batch {i//500 + 1}: status code {resp.status_code}")
    except Exception as e:
        print(f"Skipping auto-post: API not running or requests not installed. Detail: {e}")
    
    # Print some statistics
    entries = sum(1 for e in all_events if e["event_type"] == "ENTRY")
    exits = sum(1 for e in all_events if e["event_type"] == "EXIT")
    reentries = sum(1 for e in all_events if e["event_type"] == "REENTRY")
    staff = len(set(e["visitor_id"] for e in all_events if e["is_staff"]))
    unique_visitors = len(set(e["visitor_id"] for e in all_events if not e["is_staff"]))
    
    print(f"Stats:")
    print(f"  - Unique Customers: {unique_visitors}")
    print(f"  - Unique Staff: {staff}")
    print(f"  - Total Entry Events: {entries}")
    print(f"  - Total Re-entry Events: {reentries}")
    print(f"  - Total Exit Events: {exits}")

if __name__ == "__main__":
    main()