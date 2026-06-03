from ultralytics import YOLO
import cv2


class PersonDetector:

    def __init__(self):
        self.model = YOLO("yolov8n.pt")

    def detect(self, frame):

        results = self.model(frame, verbose=False)

        detections = []

        for result in results:

            for box in result.boxes:

                cls = int(box.cls[0])
                conf = float(box.conf[0])

                if cls != 0 or conf < 0.3:
                    continue

                x1, y1, x2, y2 = map(
                    int,
                    box.xyxy[0]
                )

                detections.append({
                    "bbox": [x1, y1, x2, y2],
                    "confidence": conf
                })

        return detections