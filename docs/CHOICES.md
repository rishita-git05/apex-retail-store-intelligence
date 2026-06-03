# Architectural Choices Log - Store Intelligence System

Detailed log of the three major architectural decisions made during the design and implementation of the Store Intelligence System for Apex Retail.

---

## 1. Object Detection Model: YOLOv8n (Nano)

### Options Considered:
- **YOLOv8n (Nano)**: $3.2\text{M}$ parameters, CPU inference latency of $\sim30\text{ms}$ per frame.
- **YOLOv8x (X-Large)**: $68.2\text{M}$ parameters, high bounding box accuracy but slow CPU inference ($\sim400\text{ms}$ per frame).
- **RT-DETR (DEtection TRansformer)**: Modern transformer-based detector, high accuracy, but very heavy GPU dependency.

### What AI Suggested:
The AI assistant initially suggested using `YOLOv8m` or `YOLOv9-c` to ensure high bounding box accuracy and reduce false negatives in crowded frames or under mixed lighting.

### What We Chose and Why:
We chose **YOLOv8n (Nano)**. The primary design constraint of this edge system is that it must execute inside a container via `docker compose up` on arbitrary host hardware (which may not have access to an NVIDIA GPU). Running any model larger than YOLOv8n on CPU degrades frame rates to single digits, causing massive frame dropping in live streams. YOLOv8n provides the optimal balance of $30+\text{FPS}$ processing on normal CPU threads while maintaining high-confidence person detections (minimum confidence threshold of $0.30$). Minor false negatives from occlusion are handled downstream by the tracker's lost-recovery frame buffer (45 frames grace period).

---

## 2. Event Schema: Flat Schema with Metadata Block

### Options Considered:
- **Nested Schema**: Grouping timestamps, zones, and session counts into hierarchical sub-objects (e.g. `{"session": {"seq": 5}, "location": {"zone": "SKINCARE"}}`).
- **Flat Schema**: Explicit root-level attributes with a dynamic metadata block for contextual parameters (e.g., `queue_depth`, `sku_zone`).

### What AI Suggested:
The AI suggested using a fully nested JSON schema to maintain visual nesting structure and ease serialization in Python classes.

### What We Chose and Why:
We chose the **Flat Schema with Metadata block**, as specified in the problem statement. The flat structure simplifies downstream relational SQL mapping and minimizes processing overhead. Flat attributes (like `event_id`, `store_id`, `visitor_id`, `event_type`, `timestamp`, `zone_id`, `dwell_ms`, and `is_staff`) are mapped directly to database columns. This enables fast indexing, simple queries, and lightweight aggregation. The `metadata_json` text column handles custom metadata (like `queue_depth` for queue joins) without cluttering the database schema or requiring migrations.

---

## 3. Database Engine: SQLite

### Options Considered:
- **PostgreSQL**: Highly scalable, supports concurrent writes, rich JSON queries.
- **SQLite**: Local file-based, zero configuration, embedded, extremely fast reads.
- **Redis**: In-memory store for high-frequency metrics caching.

### What AI Suggested:
The AI suggested setting up a multi-container Docker Compose file containing a **PostgreSQL** instance and a **Redis** cache to handle live ingestion scales of up to 500 events per batch.

### What We Chose and Why:
We chose **SQLite** (stored in [store.db]).
For a store-level edge intelligence system, running a full PostgreSQL database is unnecessary overhead. SQLite runs within the FastAPI process space, requiring no port binding, credentials management, or separate container services. Because the Vision Pipeline writes events in batch and the API computes metrics on the fly using SQLite indexes, the latency is extremely low (typically $<15\text{ms}$ per query). This satisfies the "Acceptance Gate" requirement: the system runs seamlessly with `docker compose up` without requiring complex database setup, making the application portable and robust.
