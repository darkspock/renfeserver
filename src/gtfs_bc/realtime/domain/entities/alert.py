from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class AlertCause(Enum):
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


class AlertEffect(Enum):
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


@dataclass
class AlertEntity:
    """Entity selector for an alert - identifies what the alert applies to."""
    route_id: Optional[str] = None
    stop_id: Optional[str] = None
    trip_id: Optional[str] = None
    agency_id: Optional[str] = None
    route_type: Optional[int] = None


@dataclass
class Alert:
    """GTFS-RT Alert entity.

    Represents a service alert that affects routes, stops, or trips.
    """
    alert_id: str
    cause: AlertCause
    effect: AlertEffect
    header_text: str
    description_text: Optional[str]
    url: Optional[str]
    active_period_start: Optional[datetime]
    active_period_end: Optional[datetime]
    informed_entities: List[AlertEntity] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_gtfsrt_json(cls, entity: dict) -> "Alert":
        """Create Alert from GTFS-RT JSON entity."""
        alert = entity.get("alert", {})

        # Parse cause
        cause_str = alert.get("cause", "UNKNOWN_CAUSE")
        try:
            cause = AlertCause(cause_str)
        except ValueError:
            cause = AlertCause.UNKNOWN_CAUSE

        # Parse effect
        effect_str = alert.get("effect", "UNKNOWN_EFFECT")
        try:
            effect = AlertEffect(effect_str)
        except ValueError:
            effect = AlertEffect.UNKNOWN_EFFECT

        # Parse header text
        header_text_obj = alert.get("headerText", {})
        header_text = ""
        translations = header_text_obj.get("translation", [])
        if translations:
            # Prefer Spanish, fall back to first available
            for t in translations:
                if t.get("language") == "es":
                    header_text = t.get("text", "")
                    break
            if not header_text:
                header_text = translations[0].get("text", "")

        # Parse description text
        description_text_obj = alert.get("descriptionText", {})
        description_text = None
        desc_translations = description_text_obj.get("translation", [])
        if desc_translations:
            for t in desc_translations:
                if t.get("language") == "es":
                    description_text = t.get("text", "")
                    break
            if not description_text:
                description_text = desc_translations[0].get("text", "")

        # Parse URL
        url_obj = alert.get("url", {})
        url = None
        url_translations = url_obj.get("translation", [])
        if url_translations:
            url = url_translations[0].get("text", "")

        # Parse active periods
        active_period_start = None
        active_period_end = None
        active_periods = alert.get("activePeriod", [])
        if active_periods:
            period = active_periods[0]
            if period.get("start"):
                active_period_start = datetime.fromtimestamp(int(period["start"]))
            if period.get("end"):
                active_period_end = datetime.fromtimestamp(int(period["end"]))

        # Parse informed entities
        informed_entities = []
        for ie in alert.get("informedEntity", []):
            informed_entities.append(AlertEntity(
                route_id=ie.get("routeId"),
                stop_id=ie.get("stopId"),
                trip_id=ie.get("trip", {}).get("tripId") if ie.get("trip") else None,
                agency_id=ie.get("agencyId"),
                route_type=ie.get("routeType"),
            ))

        return cls(
            alert_id=entity.get("id", ""),
            cause=cause,
            effect=effect,
            header_text=header_text,
            description_text=description_text,
            url=url,
            active_period_start=active_period_start,
            active_period_end=active_period_end,
            informed_entities=informed_entities,
        )
