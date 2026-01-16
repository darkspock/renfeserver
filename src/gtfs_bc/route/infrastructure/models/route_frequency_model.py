from sqlalchemy import Column, String, Integer, Time, Index, ForeignKey
from sqlalchemy.orm import relationship
from core.base import Base


class RouteFrequencyModel(Base):
    """SQLAlchemy model for route frequencies.

    Stores frequency data (headway) for routes by time period.
    Based on GTFS frequencies.txt format.
    """
    __tablename__ = "gtfs_route_frequencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(String(100), ForeignKey("gtfs_routes.id"), nullable=False, index=True)

    # Time period
    start_time = Column(Time, nullable=False)  # Start of frequency period (e.g., 07:00)
    end_time = Column(Time, nullable=False)    # End of frequency period (e.g., 10:00)

    # Frequency
    headway_secs = Column(Integer, nullable=False)  # Seconds between departures

    # Day type (to distinguish weekday/weekend frequencies)
    day_type = Column(String(20), nullable=False, default="weekday")  # weekday, saturday, sunday

    # Relationship
    route = relationship("RouteModel", backref="frequencies")

    __table_args__ = (
        Index("ix_route_freq_lookup", "route_id", "day_type", "start_time"),
    )

    def __repr__(self):
        mins = self.headway_secs // 60
        return f"<RouteFrequency {self.route_id} {self.start_time}-{self.end_time}: every {mins}m ({self.day_type})>"

    @property
    def headway_minutes(self) -> int:
        """Return headway in minutes."""
        return self.headway_secs // 60
