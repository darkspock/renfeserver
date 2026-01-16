"""Service to calculate estimated vehicle positions from schedule data.

When GTFS-RT data is not available, this service estimates where trains
should be based on their scheduled stop times.
"""

from datetime import datetime, date, time, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

# Madrid timezone for all time calculations
MADRID_TZ = ZoneInfo("Europe/Madrid")


class EstimatedStatus(str, Enum):
    """Status of an estimated vehicle."""
    IN_TRANSIT_TO = "IN_TRANSIT_TO"
    INCOMING_AT = "INCOMING_AT"
    STOPPED_AT = "STOPPED_AT"
    WAITING_AT_ORIGIN = "WAITING_AT_ORIGIN"  # Train hasn't started yet


@dataclass
class EstimatedPosition:
    """Estimated position of a train based on schedule."""
    trip_id: str
    route_id: str
    route_short_name: str
    route_color: str
    headsign: Optional[str]
    latitude: float
    longitude: float
    current_status: EstimatedStatus
    current_stop_id: str
    current_stop_name: str
    next_stop_id: Optional[str]
    next_stop_name: Optional[str]
    progress_percent: float  # 0-100, how far between stops
    estimated: bool = True  # Always True for this service


class EstimatedPositionsService:
    """Calculates estimated train positions from schedule data."""

    def __init__(self, db: Session):
        self.db = db

    def get_active_service_ids(self, target_date: date) -> List[str]:
        """Get service_ids active on the given date."""
        weekday = target_date.weekday()
        day_columns = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        day_column = day_columns[weekday]

        # Get regular calendar services
        query = text(f"""
            SELECT service_id FROM gtfs_calendar
            WHERE {day_column} = true
            AND start_date <= :target_date
            AND end_date >= :target_date
        """)
        regular_services = [row[0] for row in self.db.execute(query, {"target_date": target_date}).fetchall()]

        # Check for calendar_dates exceptions
        # exception_type = 1 means service added, 2 means service removed
        added_query = text("""
            SELECT service_id FROM gtfs_calendar_dates
            WHERE date = :target_date AND exception_type = 1
        """)
        added_services = [row[0] for row in self.db.execute(added_query, {"target_date": target_date}).fetchall()]

        removed_query = text("""
            SELECT service_id FROM gtfs_calendar_dates
            WHERE date = :target_date AND exception_type = 2
        """)
        removed_services = set(row[0] for row in self.db.execute(removed_query, {"target_date": target_date}).fetchall())

        # Combine: regular + added - removed
        all_services = set(regular_services) | set(added_services)
        active_services = [s for s in all_services if s not in removed_services]

        return active_services

    def get_estimated_positions(
        self,
        nucleo_id: Optional[int] = None,
        route_id: Optional[str] = None,
        trip_ids: Optional[List[str]] = None,
        limit: int = 100
    ) -> List[EstimatedPosition]:
        """Get estimated positions of trains currently in service.

        Args:
            nucleo_id: Filter by nucleo (network area)
            route_id: Filter by specific route
            trip_ids: Filter by specific trip IDs
            limit: Maximum number of results

        Returns:
            List of estimated vehicle positions
        """
        now = datetime.now(MADRID_TZ)
        current_date = now.date()
        current_seconds = now.hour * 3600 + now.minute * 60 + now.second

        # Get active service IDs for today
        active_services = self.get_active_service_ids(current_date)
        if not active_services:
            return []

        # Query to find trips currently in service with their position
        # A trip is "in service" if current time is between first and last stop time
        query = text("""
            WITH active_trips AS (
                SELECT
                    t.id as trip_id,
                    t.route_id,
                    t.headsign,
                    r.short_name as route_short_name,
                    r.color as route_color,
                    MIN(st.departure_seconds) as first_departure,
                    MAX(st.arrival_seconds) as last_arrival
                FROM gtfs_trips t
                JOIN gtfs_routes r ON t.route_id = r.id
                JOIN gtfs_stop_times st ON t.id = st.trip_id
                WHERE t.service_id = ANY(:service_ids)
                    AND (:route_id IS NULL OR t.route_id = :route_id)
                    AND (:trip_ids IS NULL OR t.id = ANY(:trip_ids))
                GROUP BY t.id, t.route_id, t.headsign, r.short_name, r.color
                HAVING MIN(st.departure_seconds) <= :current_seconds
                    AND MAX(st.arrival_seconds) >= :current_seconds
                LIMIT :limit
            ),
            trip_positions AS (
                SELECT DISTINCT ON (at.trip_id)
                    at.trip_id,
                    at.route_id,
                    at.route_short_name,
                    at.route_color,
                    at.headsign,
                    st_prev.stop_id as prev_stop_id,
                    s_prev.name as prev_stop_name,
                    s_prev.lat as prev_lat,
                    s_prev.lon as prev_lon,
                    st_prev.departure_seconds as prev_departure,
                    st_next.stop_id as next_stop_id,
                    s_next.name as next_stop_name,
                    s_next.lat as next_lat,
                    s_next.lon as next_lon,
                    st_next.arrival_seconds as next_arrival,
                    st_next.stop_sequence as next_sequence
                FROM active_trips at
                JOIN gtfs_stop_times st_prev ON at.trip_id = st_prev.trip_id
                JOIN gtfs_stops s_prev ON st_prev.stop_id = s_prev.id
                JOIN gtfs_stop_times st_next ON at.trip_id = st_next.trip_id
                    AND st_next.stop_sequence = st_prev.stop_sequence + 1
                JOIN gtfs_stops s_next ON st_next.stop_id = s_next.id
                WHERE st_prev.departure_seconds <= :current_seconds
                    AND st_next.arrival_seconds >= :current_seconds
                    AND (:nucleo_id IS NULL OR s_prev.nucleo_id = :nucleo_id OR s_next.nucleo_id = :nucleo_id)
                ORDER BY at.trip_id, st_prev.stop_sequence DESC
            )
            SELECT * FROM trip_positions
        """)

        results = self.db.execute(query, {
            "service_ids": active_services,
            "current_seconds": current_seconds,
            "nucleo_id": nucleo_id,
            "route_id": route_id,
            "trip_ids": list(trip_ids) if trip_ids else None,
            "limit": limit
        }).fetchall()

        positions = []
        for row in results:
            # Calculate progress between stops
            time_range = row.next_arrival - row.prev_departure
            if time_range > 0:
                elapsed = current_seconds - row.prev_departure
                progress = min(100, max(0, (elapsed / time_range) * 100))
            else:
                progress = 50

            # Interpolate position
            lat = row.prev_lat + (row.next_lat - row.prev_lat) * (progress / 100)
            lon = row.prev_lon + (row.next_lon - row.prev_lon) * (progress / 100)

            # Determine status based on progress
            if progress < 10:
                status = EstimatedStatus.STOPPED_AT
                current_stop_id = row.prev_stop_id
                current_stop_name = row.prev_stop_name
            elif progress > 90:
                status = EstimatedStatus.INCOMING_AT
                current_stop_id = row.next_stop_id
                current_stop_name = row.next_stop_name
            else:
                status = EstimatedStatus.IN_TRANSIT_TO
                current_stop_id = row.next_stop_id
                current_stop_name = row.next_stop_name

            positions.append(EstimatedPosition(
                trip_id=row.trip_id,
                route_id=row.route_id,
                route_short_name=row.route_short_name,
                route_color=row.route_color or "#000000",
                headsign=row.headsign,
                latitude=lat,
                longitude=lon,
                current_status=status,
                current_stop_id=current_stop_id,
                current_stop_name=current_stop_name,
                next_stop_id=row.next_stop_id if status != EstimatedStatus.INCOMING_AT else None,
                next_stop_name=row.next_stop_name if status != EstimatedStatus.INCOMING_AT else None,
                progress_percent=progress,
                estimated=True
            ))

        # Get trips that are waiting at origin (haven't started yet but will start within 30 min)
        found_trip_ids = {p.trip_id for p in positions}
        remaining_trip_ids = [tid for tid in (trip_ids or []) if tid not in found_trip_ids]

        if remaining_trip_ids:
            waiting_query = text("""
                SELECT
                    t.id as trip_id,
                    t.route_id,
                    t.headsign,
                    r.short_name as route_short_name,
                    r.color as route_color,
                    first_stop.stop_id as origin_stop_id,
                    s.name as origin_stop_name,
                    s.lat as origin_lat,
                    s.lon as origin_lon,
                    first_stop.departure_seconds as first_departure
                FROM gtfs_trips t
                JOIN gtfs_routes r ON t.route_id = r.id
                JOIN (
                    SELECT trip_id, stop_id, departure_seconds
                    FROM gtfs_stop_times
                    WHERE stop_sequence = 1
                ) first_stop ON t.id = first_stop.trip_id
                JOIN gtfs_stops s ON first_stop.stop_id = s.id
                WHERE t.service_id = ANY(:service_ids)
                    AND t.id = ANY(:remaining_trip_ids)
                    AND first_stop.departure_seconds > :current_seconds
                    AND first_stop.departure_seconds <= :current_seconds + 1800
            """)

            waiting_results = self.db.execute(waiting_query, {
                "service_ids": active_services,
                "remaining_trip_ids": remaining_trip_ids,
                "current_seconds": current_seconds,
            }).fetchall()

            for row in waiting_results:
                positions.append(EstimatedPosition(
                    trip_id=row.trip_id,
                    route_id=row.route_id,
                    route_short_name=row.route_short_name,
                    route_color=row.route_color or "#000000",
                    headsign=row.headsign,
                    latitude=row.origin_lat,
                    longitude=row.origin_lon,
                    current_status=EstimatedStatus.WAITING_AT_ORIGIN,
                    current_stop_id=row.origin_stop_id,
                    current_stop_name=row.origin_stop_name,
                    next_stop_id=None,
                    next_stop_name=None,
                    progress_percent=0.0,
                    estimated=True
                ))

        return positions

    def get_estimated_positions_for_route(
        self,
        route_id: str,
        limit: int = 50
    ) -> List[EstimatedPosition]:
        """Get estimated positions for a specific route."""
        return self.get_estimated_positions(route_id=route_id, limit=limit)

    def get_estimated_positions_for_nucleo(
        self,
        nucleo_id: int,
        limit: int = 100
    ) -> List[EstimatedPosition]:
        """Get estimated positions for a specific nucleo (network area)."""
        return self.get_estimated_positions(nucleo_id=nucleo_id, limit=limit)
