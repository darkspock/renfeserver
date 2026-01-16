from datetime import datetime, date
from sqlalchemy import Column, String, Integer, DateTime, Date, Index
from core.base import Base


class PlatformHistoryModel(Base):
    """Tracks daily platform usage to enable predictions.

    Records which platforms are used by each route/direction at each station.
    Data is kept per day - at the start of each new day, the most common
    platform from yesterday becomes the initial estimate for today.
    """
    __tablename__ = "gtfs_rt_platform_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stop_id = Column(String(50), nullable=False)
    route_short_name = Column(String(20), nullable=False)  # C1, C2, C3, etc.
    headsign = Column(String(200), nullable=False)  # Direction indicator
    platform = Column(String(20), nullable=False)
    count = Column(Integer, default=1)  # How many times this combo was seen today
    observation_date = Column(Date, default=date.today)  # Which day this was observed
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_platform_history_lookup", "stop_id", "route_short_name", "headsign", "observation_date"),
        Index("ix_platform_history_stop_date", "stop_id", "observation_date"),
    )

    def __repr__(self):
        return f"<PlatformHistory {self.stop_id} {self.route_short_name} → {self.headsign}: Vía {self.platform} ({self.count}x) [{self.observation_date}]>"
