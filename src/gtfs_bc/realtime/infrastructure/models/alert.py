from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, Index, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from core.base import Base
import enum


class AlertCauseEnum(enum.Enum):
    """GTFS-RT alert cause."""
    UNKNOWN_CAUSE = "UNKNOWN_CAUSE"
    OTHER_CAUSE = "OTHER_CAUSE"
    TECHNICAL_PROBLEM = "TECHNICAL_PROBLEM"
    STRIKE = "STRIKE"
    DEMONSTRATION = "DEMONSTRATION"
    ACCIDENT = "ACCIDENT"
    HOLIDAY = "HOLIDAY"
    WEATHER = "WEATHER"
    MAINTENANCE = "MAINTENANCE"
    CONSTRUCTION = "CONSTRUCTION"
    POLICE_ACTIVITY = "POLICE_ACTIVITY"
    MEDICAL_EMERGENCY = "MEDICAL_EMERGENCY"


class AlertEffectEnum(enum.Enum):
    """GTFS-RT alert effect."""
    NO_SERVICE = "NO_SERVICE"
    REDUCED_SERVICE = "REDUCED_SERVICE"
    SIGNIFICANT_DELAYS = "SIGNIFICANT_DELAYS"
    DETOUR = "DETOUR"
    ADDITIONAL_SERVICE = "ADDITIONAL_SERVICE"
    MODIFIED_SERVICE = "MODIFIED_SERVICE"
    OTHER_EFFECT = "OTHER_EFFECT"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"
    STOP_MOVED = "STOP_MOVED"


class AlertModel(Base):
    """SQLAlchemy model for GTFS-RT service alerts.

    Stores service alerts that affect routes, stops, or trips.
    """
    __tablename__ = "gtfs_rt_alerts"

    alert_id = Column(String(100), primary_key=True)
    cause = Column(SQLEnum(AlertCauseEnum), nullable=False, default=AlertCauseEnum.UNKNOWN_CAUSE)
    effect = Column(SQLEnum(AlertEffectEnum), nullable=False, default=AlertEffectEnum.UNKNOWN_EFFECT)
    header_text = Column(Text, nullable=False)
    description_text = Column(Text, nullable=True)
    url = Column(String(500), nullable=True)
    active_period_start = Column(DateTime, nullable=True)
    active_period_end = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Source: 'gtfsrt' for automatic GTFS-RT alerts, 'manual' for user-created alerts
    source = Column(String(20), nullable=True, default='gtfsrt')

    # Relationship to informed entities
    informed_entities = relationship(
        "AlertEntityModel",
        back_populates="alert",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_alerts_active_period", "active_period_start", "active_period_end"),
    )

    def __repr__(self):
        return f"<Alert {self.alert_id}: {self.header_text[:50]}>"

    @property
    def is_active(self) -> bool:
        """Check if alert is currently active."""
        now = datetime.utcnow()
        if self.active_period_start and now < self.active_period_start:
            return False
        if self.active_period_end and now > self.active_period_end:
            return False
        return True


class AlertEntityModel(Base):
    """SQLAlchemy model for GTFS-RT alert informed entities.

    Links alerts to the routes, stops, trips, or agencies they affect.
    """
    __tablename__ = "gtfs_rt_alert_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(
        String(100),
        ForeignKey("gtfs_rt_alerts.alert_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    route_id = Column(String(100), nullable=True, index=True)
    stop_id = Column(String(100), nullable=True, index=True)
    trip_id = Column(String(100), nullable=True, index=True)
    agency_id = Column(String(50), nullable=True)
    route_type = Column(Integer, nullable=True)

    # Relationship to parent alert
    alert = relationship("AlertModel", back_populates="informed_entities")

    __table_args__ = (
        Index("ix_alert_entities_route", "route_id"),
        Index("ix_alert_entities_stop", "stop_id"),
    )

    def __repr__(self):
        return f"<AlertEntity alert={self.alert_id} route={self.route_id} stop={self.stop_id}>"
