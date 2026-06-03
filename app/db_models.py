from sqlalchemy import Column, String, Float, Boolean, Integer, Text
from app.database import Base

class EventDB(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True)
    store_id = Column(String)
    camera_id = Column(String)
    visitor_id = Column(String)
    event_type = Column(String)
    timestamp = Column(String)
    zone_id = Column(String, nullable=True)
    dwell_ms = Column(Integer)
    is_staff = Column(Boolean)
    confidence = Column(Float)
    metadata_json = Column(Text)


class POSTransactionDB(Base):
    __tablename__ = "pos_transactions"

    order_id = Column(String, primary_key=True)
    store_id = Column(String)
    timestamp = Column(String)  # ISO-8601 UTC timestamp
    total_amount = Column(Float)