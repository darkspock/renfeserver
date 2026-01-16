from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from core.base import Base


class TripUpdateModel(Base):
    """SQLAlchemy model for GTFS-RT trip updates.

    Stores the latest delay information for each trip.
    """
    __tablename__ = "gtfs_rt_trip_updates"

    trip_id = Column(String(50), primary_key=True)
    delay = Column(Integer, nullable=False, default=0)  # Delay in seconds
    vehicle_id = Column(String(50), nullable=True)
    wheelchair_accessible = Column(Boolean, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to stop time updates
    stop_time_updates = relationship(
        "StopTimeUpdateModel",
        back_populates="trip_update",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_trip_updates_delay", "delay"),
    )

    def __repr__(self):
        return f"<TripUpdate {self.trip_id} delay={self.delay}s>"

    @property
    def delay_minutes(self) -> int:
        return self.delay // 60

    @property
    def is_delayed(self) -> bool:
        return self.delay > 60


class StopTimeUpdateModel(Base):
    """SQLAlchemy model for GTFS-RT stop time updates.

    Stores delay information for specific stops in a trip.
    """
    __tablename__ = "gtfs_rt_stop_time_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_id = Column(
        String(50),
        ForeignKey("gtfs_rt_trip_updates.trip_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stop_id = Column(String(50), nullable=False, index=True)
    arrival_delay = Column(Integer, nullable=True)  # Delay in seconds
    arrival_time = Column(DateTime, nullable=True)  # Predicted arrival
    departure_delay = Column(Integer, nullable=True)  # Delay in seconds
    departure_time = Column(DateTime, nullable=True)  # Predicted departure
    platform = Column(String(20), nullable=True)  # Platform/track number from GTFS-RT

    # Relationship to parent trip update
    trip_update = relationship("TripUpdateModel", back_populates="stop_time_updates")

    __table_args__ = (
        Index("ix_stop_time_updates_trip_stop", "trip_id", "stop_id"),
    )

    def __repr__(self):
        return f"<StopTimeUpdate {self.trip_id}:{self.stop_id} delay={self.arrival_delay}s>"
