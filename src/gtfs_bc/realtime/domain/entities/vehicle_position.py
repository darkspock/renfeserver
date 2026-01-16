import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class VehicleStatus(Enum):
    """GTFS-RT vehicle status."""
    INCOMING_AT = "INCOMING_AT"  # Vehicle is about to arrive at the stop
    STOPPED_AT = "STOPPED_AT"    # Vehicle is standing at the stop
    IN_TRANSIT_TO = "IN_TRANSIT_TO"  # Vehicle is in transit to the stop


@dataclass
class VehiclePosition:
    """GTFS-RT Vehicle Position entity.

    Represents the real-time position of a vehicle (train).
    """
    vehicle_id: str
    trip_id: str
    latitude: float
    longitude: float
    current_status: VehicleStatus
    stop_id: str
    timestamp: datetime
    label: Optional[str] = None
    platform: Optional[str] = None  # Platform/track number extracted from label

    @staticmethod
    def _extract_platform(label: Optional[str]) -> Optional[str]:
        """Extract platform number from label like 'C4-23603-PLATF.(8)'."""
        if not label:
            return None
        # Match patterns like "PLATF.(8)" or "PLATF.(12)"
        match = re.search(r'PLATF\.\((\d+)\)', label)
        if match:
            return match.group(1)
        return None

    @classmethod
    def from_gtfsrt_json(cls, entity: dict) -> "VehiclePosition":
        """Create VehiclePosition from GTFS-RT JSON entity."""
        vehicle = entity.get("vehicle", {})
        trip = vehicle.get("trip", {})
        position = vehicle.get("position", {})
        vehicle_info = vehicle.get("vehicle", {})

        status_str = vehicle.get("currentStatus", "IN_TRANSIT_TO")
        try:
            status = VehicleStatus(status_str)
        except ValueError:
            status = VehicleStatus.IN_TRANSIT_TO

        label = vehicle_info.get("label")
        platform = cls._extract_platform(label)

        return cls(
            vehicle_id=vehicle_info.get("id", ""),
            trip_id=trip.get("tripId", ""),
            latitude=position.get("latitude", 0.0),
            longitude=position.get("longitude", 0.0),
            current_status=status,
            stop_id=vehicle.get("stopId", ""),
            timestamp=datetime.fromtimestamp(int(vehicle.get("timestamp", 0))),
            label=label,
            platform=platform,
        )
