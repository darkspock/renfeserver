from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, Index, Enum as SQLEnum
from core.base import Base
import enum


class VehicleStatusEnum(enum.Enum):
    """GTFS-RT vehicle status."""
    INCOMING_AT = "INCOMING_AT"
    STOPPED_AT = "STOPPED_AT"
    IN_TRANSIT_TO = "IN_TRANSIT_TO"


class VehiclePositionModel(Base):
    """SQLAlchemy model for GTFS-RT vehicle positions.

    Stores the latest position of each vehicle. Updated in real-time.
    """
    __tablename__ = "gtfs_rt_vehicle_positions"

    vehicle_id = Column(String(50), primary_key=True)
    trip_id = Column(String(50), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    current_status = Column(SQLEnum(VehicleStatusEnum), nullable=False)
    stop_id = Column(String(50), nullable=True, index=True)
    label = Column(String(100), nullable=True)
    platform = Column(String(20), nullable=True)  # Platform/track number from GTFS-RT
    timestamp = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_vehicle_positions_trip_stop", "trip_id", "stop_id"),
    )

    def __repr__(self):
        return f"<VehiclePosition {self.vehicle_id} @ {self.latitude},{self.longitude}>"
