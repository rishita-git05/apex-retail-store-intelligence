# PROMPT: Write pytest unit tests for the SingleCameraTracker and ColorSignature classes, including test cases for Euclidean distance tracking, lost-and-recovered track state management, and HSV staff uniform detection.
# CHANGES MADE: Added mocked cv2 frame inputs to test detector-tracker loop without loading video files.

import pytest
import numpy as np
from pipeline.tracker import ColorSignature, SingleCameraTracker

def test_color_signature_is_wearing_staff_uniform():
    # Create a mock torso image with black pixels (staff uniform)
    black_crop = np.zeros((100, 100, 3), dtype=np.uint8)
    assert ColorSignature.is_wearing_staff_uniform(black_crop) is True

    # Create a mock torso image with bright white pixels (not staff uniform)
    white_crop = np.ones((100, 100, 3), dtype=np.uint8) * 255
    assert ColorSignature.is_wearing_staff_uniform(white_crop) is False

def test_single_camera_tracker_initialization():
    tracker = SingleCameraTracker("CAM_1")
    assert tracker.camera_id == "CAM_1"
    assert tracker.next_track_id == 1
    assert len(tracker.active_tracks) == 0

def test_single_camera_tracker_update():
    tracker = SingleCameraTracker("CAM_1")
    frame = np.ones((1080, 1920, 3), dtype=np.uint8) * 128
    
    # First detection
    detections = [{"bbox": [100, 100, 200, 200], "confidence": 0.9}]
    tracks = tracker.update(detections, frame)
    
    assert len(tracks) == 1
    local_id = list(tracks.keys())[0]
    assert local_id == "CAM_1_001"
    assert tracks[local_id]["center"] == (150, 150)
    assert tracks[local_id]["confidence"] == 0.9

    # Second detection: moved slightly (distance < 120)
    detections_moved = [{"bbox": [110, 110, 210, 210], "confidence": 0.95}]
    tracks_moved = tracker.update(detections_moved, frame)
    assert len(tracks_moved) == 1
    assert "CAM_1_001" in tracks_moved
    assert tracks_moved["CAM_1_001"]["center"] == (160, 160)
    assert tracks_moved["CAM_1_001"]["confidence"] == 0.95

def test_single_camera_tracker_lost_state():
    tracker = SingleCameraTracker("CAM_1")
    frame = np.ones((1080, 1920, 3), dtype=np.uint8) * 128
    
    # 1. Add track
    detections = [{"bbox": [100, 100, 200, 200], "confidence": 0.85}]
    tracker.update(detections, frame)
    assert "CAM_1_001" in tracker.active_tracks
    
    # 2. Update with empty detections (moves track to lost)
    tracker.update([], frame)
    assert "CAM_1_001" not in tracker.active_tracks
    assert "CAM_1_001" in tracker.lost_tracks
    
    # 3. Update with matching detection (recovers from lost)
    detections_recover = [{"bbox": [102, 102, 202, 202], "confidence": 0.88}]
    tracks_recovered = tracker.update(detections_recover, frame)
    assert "CAM_1_001" in tracks_recovered
    assert "CAM_1_001" not in tracker.lost_tracks
