import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from src.gtfs_bc.realtime.domain.entities import VehiclePosition, TripUpdate, StopTimeUpdate, Alert
from src.gtfs_bc.realtime.infrastructure.models import (
    VehiclePositionModel,
    TripUpdateModel,
    StopTimeUpdateModel,
    VehicleStatusEnum,
    AlertModel,
    AlertEntityModel,
    AlertCauseEnum,
    AlertEffectEnum,
    PlatformHistoryModel,
)
from src.gtfs_bc.trip.infrastructure.models import TripModel

logger = logging.getLogger(__name__)


class GTFSRealtimeFetcher:
    """Service to fetch and store GTFS-RT data from Renfe."""

    # Renfe GTFS-RT endpoints (JSON format)
    VEHICLE_POSITIONS_URL = "https://gtfsrt.renfe.com/vehicle_positions.json"
    TRIP_UPDATES_URL = "https://gtfsrt.renfe.com/trip_updates.json"
    ALERTS_URL = "https://gtfsrt.renfe.com/alerts.json"

    def __init__(self, db: Session):
        self.db = db

    async def fetch_and_store_vehicle_positions(self) -> int:
        """Fetch vehicle positions from Renfe API and store in database.

        Returns the number of vehicle positions updated.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.VEHICLE_POSITIONS_URL, timeout=30.0)
                response.raise_for_status()
                data = response.json()

            entities = data.get("entity", [])
            logger.info(f"Fetched {len(entities)} vehicle positions from Renfe")

            count = 0
            for entity in entities:
                try:
                    vp = VehiclePosition.from_gtfsrt_json(entity)
                    self._upsert_vehicle_position(vp)
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing vehicle position: {e}")

            self.db.commit()
            return count

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching vehicle positions: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching vehicle positions: {e}")
            raise

    def fetch_and_store_vehicle_positions_sync(self) -> int:
        """Synchronous version of fetch_and_store_vehicle_positions."""
        try:
            response = httpx.get(self.VEHICLE_POSITIONS_URL, timeout=30.0)
            response.raise_for_status()
            data = response.json()

            entities = data.get("entity", [])
            logger.info(f"Fetched {len(entities)} vehicle positions from Renfe")

            count = 0
            for entity in entities:
                try:
                    vp = VehiclePosition.from_gtfsrt_json(entity)
                    self._upsert_vehicle_position(vp)
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing vehicle position: {e}")

            self.db.commit()
            return count

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching vehicle positions: {e}")
            raise

    def _upsert_vehicle_position(self, vp: VehiclePosition) -> None:
        """Insert or update a vehicle position."""
        status_enum = VehicleStatusEnum(vp.current_status.value)

        stmt = insert(VehiclePositionModel).values(
            vehicle_id=vp.vehicle_id,
            trip_id=vp.trip_id,
            latitude=vp.latitude,
            longitude=vp.longitude,
            current_status=status_enum,
            stop_id=vp.stop_id,
            label=vp.label,
            platform=vp.platform,
            timestamp=vp.timestamp,
            updated_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["vehicle_id"],
            set_={
                "trip_id": stmt.excluded.trip_id,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "current_status": stmt.excluded.current_status,
                "stop_id": stmt.excluded.stop_id,
                "label": stmt.excluded.label,
                "platform": stmt.excluded.platform,
                "timestamp": stmt.excluded.timestamp,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        self.db.execute(stmt)

        # Record platform history when train is stopped at a station
        if vp.current_status.value == "STOPPED_AT" and vp.stop_id and vp.platform:
            self._record_platform_history(vp)

    def _record_platform_history(self, vp: VehiclePosition) -> None:
        """Record platform usage for learning predictions (daily data)."""
        try:
            # Extract route short name from label (e.g., "C7-21811-PLATF.(1)" -> "C7")
            route_short_name = None
            if vp.label:
                parts = vp.label.split("-")
                if parts:
                    route_short_name = parts[0]

            if not route_short_name:
                return

            # Get headsign from trip (ensure never None)
            trip = self.db.query(TripModel).filter(TripModel.id == vp.trip_id).first()
            headsign = (trip.headsign if trip and trip.headsign else None) or "Unknown"

            # Normalize stop_id
            stop_id = vp.stop_id
            today = date.today()

            # Check if this combination already exists FOR TODAY
            existing = self.db.query(PlatformHistoryModel).filter(
                PlatformHistoryModel.stop_id == stop_id,
                PlatformHistoryModel.route_short_name == route_short_name,
                PlatformHistoryModel.headsign == headsign,
                PlatformHistoryModel.platform == vp.platform,
                PlatformHistoryModel.observation_date == today,
            ).first()

            if existing:
                # Increment count for today
                existing.count += 1
                existing.last_seen = datetime.utcnow()
            else:
                # Create new record for today
                new_record = PlatformHistoryModel(
                    stop_id=stop_id,
                    route_short_name=route_short_name,
                    headsign=headsign,
                    platform=vp.platform,
                    count=1,
                    observation_date=today,
                    last_seen=datetime.utcnow(),
                )
                self.db.add(new_record)
        except Exception as e:
            logger.warning(f"Error recording platform history: {e}")

    async def fetch_and_store_trip_updates(self) -> int:
        """Fetch trip updates from Renfe API and store in database.

        Returns the number of trip updates processed.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.TRIP_UPDATES_URL, timeout=30.0)
                response.raise_for_status()
                data = response.json()

            entities = data.get("entity", [])
            logger.info(f"Fetched {len(entities)} trip updates from Renfe")

            count = 0
            for entity in entities:
                try:
                    tu = TripUpdate.from_gtfsrt_json(entity)
                    self._upsert_trip_update(tu)
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing trip update: {e}")

            self.db.commit()
            return count

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching trip updates: {e}")
            raise

    def fetch_and_store_trip_updates_sync(self) -> int:
        """Synchronous version of fetch_and_store_trip_updates."""
        try:
            response = httpx.get(self.TRIP_UPDATES_URL, timeout=30.0)
            response.raise_for_status()
            data = response.json()

            entities = data.get("entity", [])
            logger.info(f"Fetched {len(entities)} trip updates from Renfe")

            count = 0
            for entity in entities:
                try:
                    tu = TripUpdate.from_gtfsrt_json(entity)
                    self._upsert_trip_update(tu)
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing trip update: {e}")

            self.db.commit()
            return count

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching trip updates: {e}")
            raise

    def _upsert_trip_update(self, tu: TripUpdate) -> None:
        """Insert or update a trip update and its stop time updates."""
        # First, delete existing stop time updates for this trip
        self.db.query(StopTimeUpdateModel).filter(
            StopTimeUpdateModel.trip_id == tu.trip_id
        ).delete()

        # Upsert the trip update
        stmt = insert(TripUpdateModel).values(
            trip_id=tu.trip_id,
            delay=tu.delay,
            vehicle_id=tu.vehicle_id,
            wheelchair_accessible=tu.wheelchair_accessible,
            timestamp=tu.timestamp,
            updated_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["trip_id"],
            set_={
                "delay": stmt.excluded.delay,
                "vehicle_id": stmt.excluded.vehicle_id,
                "wheelchair_accessible": stmt.excluded.wheelchair_accessible,
                "timestamp": stmt.excluded.timestamp,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        self.db.execute(stmt)

        # Insert stop time updates
        for stu in tu.stop_time_updates:
            stop_time_model = StopTimeUpdateModel(
                trip_id=tu.trip_id,
                stop_id=stu.stop_id,
                arrival_delay=stu.arrival_delay,
                arrival_time=stu.arrival_time,
                departure_delay=stu.departure_delay,
                departure_time=stu.departure_time,
            )
            self.db.add(stop_time_model)

    def fetch_and_store_alerts_sync(self) -> int:
        """Fetch alerts from Renfe API and store in database.

        Returns the number of alerts updated.
        """
        try:
            response = httpx.get(self.ALERTS_URL, timeout=30.0)
            response.raise_for_status()
            data = response.json()

            entities = data.get("entity", [])
            logger.info(f"Fetched {len(entities)} alerts from Renfe")

            count = 0
            for entity in entities:
                try:
                    alert = Alert.from_gtfsrt_json(entity)
                    self._upsert_alert(alert)
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing alert: {e}")

            self.db.commit()
            return count

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching alerts: {e}")
            raise

    def _upsert_alert(self, alert: Alert) -> None:
        """Insert or update an alert."""
        # Delete existing alert entities for this alert
        self.db.query(AlertEntityModel).filter(
            AlertEntityModel.alert_id == alert.alert_id
        ).delete()

        # Map domain enums to DB enums
        cause_enum = AlertCauseEnum(alert.cause.value)
        effect_enum = AlertEffectEnum(alert.effect.value)

        # Upsert the alert
        stmt = insert(AlertModel).values(
            alert_id=alert.alert_id,
            cause=cause_enum,
            effect=effect_enum,
            header_text=alert.header_text,
            description_text=alert.description_text,
            url=alert.url,
            active_period_start=alert.active_period_start,
            active_period_end=alert.active_period_end,
            timestamp=alert.timestamp,
            updated_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["alert_id"],
            set_={
                "cause": stmt.excluded.cause,
                "effect": stmt.excluded.effect,
                "header_text": stmt.excluded.header_text,
                "description_text": stmt.excluded.description_text,
                "url": stmt.excluded.url,
                "active_period_start": stmt.excluded.active_period_start,
                "active_period_end": stmt.excluded.active_period_end,
                "timestamp": stmt.excluded.timestamp,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        self.db.execute(stmt)

        # Insert informed entities
        for ie in alert.informed_entities:
            entity_model = AlertEntityModel(
                alert_id=alert.alert_id,
                route_id=ie.route_id,
                stop_id=ie.stop_id,
                trip_id=ie.trip_id,
                agency_id=ie.agency_id,
                route_type=ie.route_type,
            )
            self.db.add(entity_model)

    def fetch_all_sync(self) -> Dict[str, int]:
        """Fetch vehicle positions, trip updates, and alerts synchronously.

        Returns a dict with counts of each type.
        """
        vehicle_count = self.fetch_and_store_vehicle_positions_sync()
        trip_count = self.fetch_and_store_trip_updates_sync()
        alerts_count = self.fetch_and_store_alerts_sync()
        return {
            "vehicle_positions": vehicle_count,
            "trip_updates": trip_count,
            "alerts": alerts_count,
        }

    def get_vehicle_positions(
        self,
        stop_id: Optional[str] = None,
        trip_id: Optional[str] = None,
    ) -> List[VehiclePositionModel]:
        """Get vehicle positions with optional filters."""
        query = self.db.query(VehiclePositionModel)
        if stop_id:
            query = query.filter(VehiclePositionModel.stop_id == stop_id)
        if trip_id:
            query = query.filter(VehiclePositionModel.trip_id == trip_id)
        return query.all()

    def get_trip_updates(
        self,
        min_delay: Optional[int] = None,
        trip_id: Optional[str] = None,
    ) -> List[TripUpdateModel]:
        """Get trip updates with optional filters."""
        query = self.db.query(TripUpdateModel)
        if min_delay is not None:
            query = query.filter(TripUpdateModel.delay >= min_delay)
        if trip_id:
            query = query.filter(TripUpdateModel.trip_id == trip_id)
        return query.order_by(TripUpdateModel.delay.desc()).all()

    def get_delays_for_stop(self, stop_id: str) -> List[Dict[str, Any]]:
        """Get all delays for a specific stop.

        Returns list of dicts with trip_id, delay, arrival_time.
        """
        stop_time_updates = (
            self.db.query(StopTimeUpdateModel)
            .filter(StopTimeUpdateModel.stop_id == stop_id)
            .all()
        )
        result = []
        for stu in stop_time_updates:
            result.append({
                "trip_id": stu.trip_id,
                "stop_id": stu.stop_id,
                "arrival_delay": stu.arrival_delay,
                "arrival_time": stu.arrival_time,
                "departure_delay": stu.departure_delay,
                "departure_time": stu.departure_time,
            })
        return result

    def get_alerts(
        self,
        route_id: Optional[str] = None,
        stop_id: Optional[str] = None,
        active_only: bool = True,
    ) -> List[AlertModel]:
        """Get alerts with optional filters.

        Args:
            route_id: Filter by affected route
            stop_id: Filter by affected stop
            active_only: Only return currently active alerts (default True)
        """
        query = self.db.query(AlertModel)

        if active_only:
            now = datetime.utcnow()
            query = query.filter(
                (AlertModel.active_period_start.is_(None)) | (AlertModel.active_period_start <= now),
                (AlertModel.active_period_end.is_(None)) | (AlertModel.active_period_end >= now),
            )

        if route_id or stop_id:
            # Join with entities if filtering
            query = query.join(AlertModel.informed_entities)
            if route_id:
                query = query.filter(AlertEntityModel.route_id == route_id)
            if stop_id:
                query = query.filter(AlertEntityModel.stop_id == stop_id)

        return query.distinct().all()

    def get_alerts_for_route(self, route_id: str) -> List[AlertModel]:
        """Get all active alerts for a specific route."""
        return self.get_alerts(route_id=route_id, active_only=True)

    def get_alerts_for_stop(self, stop_id: str) -> List[AlertModel]:
        """Get all active alerts for a specific stop."""
        return self.get_alerts(stop_id=stop_id, active_only=True)
