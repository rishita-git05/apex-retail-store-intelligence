import math
import cv2
import numpy as np


class ColorSignature:
    """Helper class to extract and compare color features of people."""

    @staticmethod
    def extract_histogram(image):
        """Extract a normalized Hue-Saturation histogram from an image crop."""
        if image is None or image.size == 0:
            return None
        
        # Convert to HSV color space
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        
        # Compute histogram on H and S channels
        # Hue has range [0, 180], Saturation has range [0, 255]
        hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
        
        # Normalize the histogram
        cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        return hist.flatten()

    @staticmethod
    def compare_histograms(hist1, hist2):
        """Compare two color histograms using correlation distance."""
        if hist1 is None or hist2 is None:
            return 0.0
        # Correlation method returns 1.0 for perfect match, -1.0 for worst
        sim = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        return max(0.0, sim)

    @staticmethod
    def is_wearing_staff_uniform(image):
        """Detect if the person is wearing the store's black uniform.
        
        Analyzes the torso region (middle part of the bounding box).
        """
        if image is None or image.size == 0:
            return False
        
        h, w, _ = image.shape
        # Torso region: middle-upper section of the crop
        y1, y2 = int(h * 0.2), int(h * 0.6)
        x1, x2 = int(w * 0.2), int(w * 0.8)
        
        torso = image[y1:y2, x1:x2]
        if torso.size == 0:
            return False
            
        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        # Black is characterized by very low brightness (Value channel)
        # Define mask for black: Value < 55
        lower_black = np.array([0, 0, 0])
        upper_black = np.array([180, 255, 55])
        
        mask = cv2.inRange(hsv, lower_black, upper_black)
        black_pixels = np.sum(mask > 0)
        total_pixels = mask.size
        
        black_ratio = black_pixels / total_pixels
        # If more than 60% of torso is black, flag as staff
        return bool(black_ratio > 0.60)


class SingleCameraTracker:
    """Tracks people within a single camera using location, sizing, and lost states."""

    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.next_track_id = 1
        self.active_tracks = {}  # local_id -> {center, bbox, hist, is_staff, last_seen_frame, age_frames}
        self.lost_tracks = {}    # local_id -> {center, bbox, hist, is_staff, last_seen_frame}
        self.frame_count = 0

    def get_center(self, bbox):
        x1, y1, x2, y2 = bbox
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def update(self, detections, frame):
        """Update tracker with new detections in the current frame."""
        self.frame_count += 1
        
        # Bounding box width/height constraints to ensure valid crop
        fh, fw, _ = frame.shape
        
        updated_tracks = {}
        matched_detection_indices = set()
        
        # 1. Match new detections with active tracks using distance and size
        for local_id, track in list(self.active_tracks.items()):
            best_det_idx = None
            min_dist = 120.0  # Max pixel distance to associate
            
            for idx, det in enumerate(detections):
                if idx in matched_detection_indices:
                    continue
                
                det_center = self.get_center(det["bbox"])
                dist = math.dist(track["center"], det_center)
                
                if dist < min_dist:
                    min_dist = dist
                    best_det_idx = idx
            
            if best_det_idx is not None:
                # Track matched
                det = detections[best_det_idx]
                center = self.get_center(det["bbox"])
                matched_detection_indices.add(best_det_idx)
                
                # Extract crop
                x1, y1, x2, y2 = det["bbox"]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(fw, x2), min(fh, y2)
                crop = frame[y1:y2, x1:x2]
                
                hist = ColorSignature.extract_histogram(crop)
                is_staff = ColorSignature.is_wearing_staff_uniform(crop)
                
                updated_tracks[local_id] = {
                    "center": center,
                    "bbox": det["bbox"],
                    "hist": hist if hist is not None else track["hist"],
                    "is_staff": is_staff or track["is_staff"],
                    "last_seen_frame": self.frame_count,
                    "age_frames": track["age_frames"] + 1,
                    "confidence": det["confidence"]
                }
            else:
                # Track not matched, move to lost
                self.lost_tracks[local_id] = track
                
        # 2. Match remaining detections with lost tracks
        for local_id, track in list(self.lost_tracks.items()):
            # If lost for too long, purge
            if self.frame_count - track["last_seen_frame"] > 45:  # 1.5 seconds at 30 fps
                self.lost_tracks.pop(local_id, None)
                continue
                
            best_det_idx = None
            min_dist = 150.0  # Slightly larger search radius for lost tracks
            
            for idx, det in enumerate(detections):
                if idx in matched_detection_indices:
                    continue
                
                det_center = self.get_center(det["bbox"])
                dist = math.dist(track["center"], det_center)
                
                if dist < min_dist:
                    min_dist = dist
                    best_det_idx = idx
                    
            if best_det_idx is not None:
                # Recover track from lost
                det = detections[best_det_idx]
                center = self.get_center(det["bbox"])
                matched_detection_indices.add(best_det_idx)
                
                x1, y1, x2, y2 = det["bbox"]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(fw, x2), min(fh, y2)
                crop = frame[y1:y2, x1:x2]
                
                hist = ColorSignature.extract_histogram(crop)
                is_staff = ColorSignature.is_wearing_staff_uniform(crop)
                
                # Move back to active
                updated_tracks[local_id] = {
                    "center": center,
                    "bbox": det["bbox"],
                    "hist": hist if hist is not None else track["hist"],
                    "is_staff": is_staff or track["is_staff"],
                    "last_seen_frame": self.frame_count,
                    "age_frames": track["age_frames"] + 1,
                    "confidence": det["confidence"]
                }
                self.lost_tracks.pop(local_id, None)

        # 3. Create new tracks for unmatched detections
        for idx, det in enumerate(detections):
            if idx in matched_detection_indices:
                continue
                
            center = self.get_center(det["bbox"])
            
            x1, y1, x2, y2 = det["bbox"]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(fw, x2), min(fh, y2)
            crop = frame[y1:y2, x1:x2]
            
            hist = ColorSignature.extract_histogram(crop)
            is_staff = ColorSignature.is_wearing_staff_uniform(crop)
            
            local_id = f"{self.camera_id}_{self.next_track_id:03d}"
            self.next_track_id += 1
            
            updated_tracks[local_id] = {
                "center": center,
                "bbox": det["bbox"],
                "hist": hist,
                "is_staff": is_staff,
                "last_seen_frame": self.frame_count,
                "age_frames": 1,
                "confidence": det["confidence"]
            }
            
        self.active_tracks = updated_tracks
        return self.active_tracks


class CrossCameraReIDManager:
    """Manages global visitor identities across multiple camera trackers using space-time & color Re-ID."""

    def __init__(self):
        self.global_next_id = 1
        self.local_to_global_map = {}  # local_track_id -> global_visitor_id
        
        # Archive of completed visitor sessions
        # global_id -> {hist, is_staff, last_seen_time, camera_history}
        self.global_registry = {}

    def get_global_id(self, local_track_id, track_data, timestamp_sec):
        """Map a local camera track ID to a global visitor ID."""
        if local_track_id in self.local_to_global_map:
            return self.local_to_global_map[local_track_id]
            
        local_hist = track_data["hist"]
        is_staff = track_data["is_staff"]
        
        # Scan registry to find matching color signature within a 2-minute time window
        best_global_id = None
        best_sim = 0.65  # Minimum correlation threshold for match
        
        for g_id, g_data in self.global_registry.items():
            # Skip if staff flag mismatch (optional, but uniform is highly distinct)
            if g_data["is_staff"] != is_staff:
                continue
                
            # Check time gap (max 90 seconds gap between cameras)
            time_gap = abs(timestamp_sec - g_data["last_seen_time"])
            if time_gap > 90.0:
                continue
                
            sim = ColorSignature.compare_histograms(local_hist, g_data["hist"])
            if sim > best_sim:
                best_sim = sim
                best_global_id = g_id
                
        if best_global_id is not None:
            # Match found
            g_id = best_global_id
            self.local_to_global_map[local_track_id] = g_id
            
            # Update signature (average the histogram to adapt to lighting changes)
            if local_hist is not None and self.global_registry[g_id]["hist"] is not None:
                self.global_registry[g_id]["hist"] = (self.global_registry[g_id]["hist"] + local_hist) / 2.0
            self.global_registry[g_id]["last_seen_time"] = timestamp_sec
            self.global_registry[g_id]["is_staff"] = self.global_registry[g_id]["is_staff"] or is_staff
        else:
            # Create a new global ID
            g_id = f"VIS_{self.global_next_id:03d}"
            self.global_next_id += 1
            
            self.local_to_global_map[local_track_id] = g_id
            self.global_registry[g_id] = {
                "hist": local_hist,
                "is_staff": is_staff,
                "last_seen_time": timestamp_sec
            }
            
        return g_id