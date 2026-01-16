from typing import List, Optional
from datetime import datetime, time
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import get_db
from src.gtfs_bc.realtime.infrastructure.services.gtfs_rt_fetcher import GTFSRealtimeFetcher
from src.gtfs_bc.realtime.infrastructure.services.estimated_positions import (
    EstimatedPositionsService,
    EstimatedPosition,
)
from src.gtfs_bc.realtime.infrastructure.services.gtfs_rt_scheduler import gtfs_rt_scheduler
from src.gtfs_bc.route.infrastructure.models import RouteModel, RouteFrequencyModel
from src.gtfs_bc.realtime.infrastructure.models import AlertModel, AlertEntityModel, AlertCauseEnum, AlertEffectEnum


router = APIRouter(prefix="/gtfs/realtime", tags=["GTFS Realtime"])


# Response schemas
class PositionSchema(BaseModel):
    latitude: float
    longitude: float


class VehiclePositionResponse(BaseModel):
    vehicle_id: str
    trip_id: str
    position: PositionSchema
    current_status: str
    stop_id: Optional[str]
    label: Optional[str]
    timestamp: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TripUpdateResponse(BaseModel):
    trip_id: str
    delay: int
    delay_minutes: int
    is_delayed: bool
    vehicle_id: Optional[str]
    wheelchair_accessible: Optional[bool]
    timestamp: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class StopDelayResponse(BaseModel):
    trip_id: str
    stop_id: str
    arrival_delay: Optional[int]
    arrival_time: Optional[datetime]
    departure_delay: Optional[int]
    departure_time: Optional[datetime]


class AlertEntityResponse(BaseModel):
    route_id: Optional[str]
    stop_id: Optional[str]
    trip_id: Optional[str]
    agency_id: Optional[str]
    route_type: Optional[int]


class AlertResponse(BaseModel):
    alert_id: str
    cause: str
    effect: str
    header_text: str
    description_text: Optional[str]
    url: Optional[str]
    active_period_start: Optional[datetime]
    active_period_end: Optional[datetime]
    is_active: bool
    informed_entities: List[AlertEntityResponse]
    timestamp: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class FetchResponse(BaseModel):
    vehicle_positions: int
    trip_updates: int
    alerts: int
    message: str


class EstimatedPositionResponse(BaseModel):
    """Estimated vehicle position based on schedule."""
    trip_id: str
    route_id: str
    route_short_name: str
    route_color: str
    headsign: Optional[str]
    position: PositionSchema
    current_status: str
    current_stop_id: str
    current_stop_name: str
    next_stop_id: Optional[str]
    next_stop_name: Optional[str]
    progress_percent: float
    estimated: bool = True


@router.post("/fetch", response_model=FetchResponse)
def fetch_realtime_data(db: Session = Depends(get_db)):
    """Fetch latest GTFS-RT data from Renfe API.

    This endpoint triggers a fetch of vehicle positions, trip updates, and alerts
    from Renfe's GTFS-RT API and stores them in the database.
    """
    fetcher = GTFSRealtimeFetcher(db)
    try:
        result = fetcher.fetch_all_sync()
        return FetchResponse(
            vehicle_positions=result["vehicle_positions"],
            trip_updates=result["trip_updates"],
            alerts=result["alerts"],
            message="GTFS-RT data fetched and stored successfully",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching GTFS-RT data: {str(e)}")


@router.get("/vehicles", response_model=List[VehiclePositionResponse])
def get_vehicle_positions(
    stop_id: Optional[str] = Query(None, description="Filter by stop ID"),
    trip_id: Optional[str] = Query(None, description="Filter by trip ID"),
    db: Session = Depends(get_db),
):
    """Get current vehicle positions.

    Optionally filter by stop_id or trip_id.
    """
    fetcher = GTFSRealtimeFetcher(db)
    vehicles = fetcher.get_vehicle_positions(stop_id=stop_id, trip_id=trip_id)

    return [
        VehiclePositionResponse(
            vehicle_id=v.vehicle_id,
            trip_id=v.trip_id,
            position=PositionSchema(latitude=v.latitude, longitude=v.longitude),
            current_status=v.current_status.value,
            stop_id=v.stop_id,
            label=v.label,
            timestamp=v.timestamp,
            updated_at=v.updated_at,
        )
        for v in vehicles
    ]


@router.get("/delays", response_model=List[TripUpdateResponse])
def get_trip_delays(
    min_delay: Optional[int] = Query(None, description="Minimum delay in seconds"),
    trip_id: Optional[str] = Query(None, description="Filter by trip ID"),
    db: Session = Depends(get_db),
):
    """Get trip delays.

    Optionally filter by minimum delay or trip_id.
    Results are sorted by delay descending.
    """
    fetcher = GTFSRealtimeFetcher(db)
    updates = fetcher.get_trip_updates(min_delay=min_delay, trip_id=trip_id)

    return [
        TripUpdateResponse(
            trip_id=u.trip_id,
            delay=u.delay,
            delay_minutes=u.delay_minutes,
            is_delayed=u.is_delayed,
            vehicle_id=u.vehicle_id,
            wheelchair_accessible=u.wheelchair_accessible,
            timestamp=u.timestamp,
            updated_at=u.updated_at,
        )
        for u in updates
    ]


@router.get("/stops/{stop_id}/delays", response_model=List[StopDelayResponse])
def get_delays_for_stop(
    stop_id: str,
    db: Session = Depends(get_db),
):
    """Get all delays for a specific stop.

    Returns all trips that have delay information for this stop.
    """
    fetcher = GTFSRealtimeFetcher(db)
    delays = fetcher.get_delays_for_stop(stop_id)

    return [
        StopDelayResponse(
            trip_id=d["trip_id"],
            stop_id=d["stop_id"],
            arrival_delay=d["arrival_delay"],
            arrival_time=d["arrival_time"],
            departure_delay=d["departure_delay"],
            departure_time=d["departure_time"],
        )
        for d in delays
    ]


@router.get("/vehicles/{vehicle_id}", response_model=VehiclePositionResponse)
def get_vehicle_position(
    vehicle_id: str,
    db: Session = Depends(get_db),
):
    """Get position for a specific vehicle."""
    fetcher = GTFSRealtimeFetcher(db)
    vehicles = fetcher.get_vehicle_positions()
    vehicle = next((v for v in vehicles if v.vehicle_id == vehicle_id), None)

    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle {vehicle_id} not found")

    return VehiclePositionResponse(
        vehicle_id=vehicle.vehicle_id,
        trip_id=vehicle.trip_id,
        position=PositionSchema(latitude=vehicle.latitude, longitude=vehicle.longitude),
        current_status=vehicle.current_status.value,
        stop_id=vehicle.stop_id,
        label=vehicle.label,
        timestamp=vehicle.timestamp,
        updated_at=vehicle.updated_at,
    )


@router.get("/alerts", response_model=List[AlertResponse])
def get_alerts(
    route_id: Optional[str] = Query(None, description="Filter by affected route ID"),
    stop_id: Optional[str] = Query(None, description="Filter by affected stop ID"),
    active_only: bool = Query(True, description="Only return currently active alerts"),
    db: Session = Depends(get_db),
):
    """Get service alerts.

    Optionally filter by affected route_id, stop_id, or active status.
    """
    fetcher = GTFSRealtimeFetcher(db)
    alerts = fetcher.get_alerts(route_id=route_id, stop_id=stop_id, active_only=active_only)

    return [
        AlertResponse(
            alert_id=a.alert_id,
            cause=a.cause.value,
            effect=a.effect.value,
            header_text=a.header_text,
            description_text=a.description_text,
            url=a.url,
            active_period_start=a.active_period_start,
            active_period_end=a.active_period_end,
            is_active=a.is_active,
            informed_entities=[
                AlertEntityResponse(
                    route_id=e.route_id,
                    stop_id=e.stop_id,
                    trip_id=e.trip_id,
                    agency_id=e.agency_id,
                    route_type=e.route_type,
                )
                for e in a.informed_entities
            ],
            timestamp=a.timestamp,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]


@router.get("/routes/{route_id}/alerts", response_model=List[AlertResponse])
def get_alerts_for_route(
    route_id: str,
    db: Session = Depends(get_db),
):
    """Get all active alerts for a specific route."""
    fetcher = GTFSRealtimeFetcher(db)
    alerts = fetcher.get_alerts_for_route(route_id)

    return [
        AlertResponse(
            alert_id=a.alert_id,
            cause=a.cause.value,
            effect=a.effect.value,
            header_text=a.header_text,
            description_text=a.description_text,
            url=a.url,
            active_period_start=a.active_period_start,
            active_period_end=a.active_period_end,
            is_active=a.is_active,
            informed_entities=[
                AlertEntityResponse(
                    route_id=e.route_id,
                    stop_id=e.stop_id,
                    trip_id=e.trip_id,
                    agency_id=e.agency_id,
                    route_type=e.route_type,
                )
                for e in a.informed_entities
            ],
            timestamp=a.timestamp,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]


@router.get("/stops/{stop_id}/alerts", response_model=List[AlertResponse])
def get_alerts_for_stop(
    stop_id: str,
    db: Session = Depends(get_db),
):
    """Get all active alerts for a specific stop."""
    fetcher = GTFSRealtimeFetcher(db)
    alerts = fetcher.get_alerts_for_stop(stop_id)

    return [
        AlertResponse(
            alert_id=a.alert_id,
            cause=a.cause.value,
            effect=a.effect.value,
            header_text=a.header_text,
            description_text=a.description_text,
            url=a.url,
            active_period_start=a.active_period_start,
            active_period_end=a.active_period_end,
            is_active=a.is_active,
            informed_entities=[
                AlertEntityResponse(
                    route_id=e.route_id,
                    stop_id=e.stop_id,
                    trip_id=e.trip_id,
                    agency_id=e.agency_id,
                    route_type=e.route_type,
                )
                for e in a.informed_entities
            ],
            timestamp=a.timestamp,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]


# Estimated positions endpoints (fallback when GTFS-RT is not available)

@router.get("/estimated", response_model=List[EstimatedPositionResponse])
def get_estimated_positions(
    nucleo_id: Optional[int] = Query(None, description="Filter by nucleo ID (network area)"),
    route_id: Optional[str] = Query(None, description="Filter by route ID"),
    limit: int = Query(100, description="Maximum number of results"),
    db: Session = Depends(get_db),
):
    """Get estimated train positions based on scheduled times.

    This endpoint calculates where trains should be based on their scheduled
    stop times. Use this when GTFS-RT vehicle positions are not available.

    The positions are interpolated between stops based on the current time
    and the scheduled departure/arrival times.
    """
    service = EstimatedPositionsService(db)
    positions = service.get_estimated_positions(
        nucleo_id=nucleo_id,
        route_id=route_id,
        limit=limit
    )

    return [
        EstimatedPositionResponse(
            trip_id=p.trip_id,
            route_id=p.route_id,
            route_short_name=p.route_short_name,
            route_color=p.route_color,
            headsign=p.headsign,
            position=PositionSchema(latitude=p.latitude, longitude=p.longitude),
            current_status=p.current_status.value,
            current_stop_id=p.current_stop_id,
            current_stop_name=p.current_stop_name,
            next_stop_id=p.next_stop_id,
            next_stop_name=p.next_stop_name,
            progress_percent=p.progress_percent,
            estimated=True
        )
        for p in positions
    ]


@router.get("/nucleos/{nucleo_id}/estimated", response_model=List[EstimatedPositionResponse])
def get_estimated_positions_for_nucleo(
    nucleo_id: int,
    limit: int = Query(100, description="Maximum number of results"),
    db: Session = Depends(get_db),
):
    """Get estimated train positions for a specific nucleo (network area)."""
    service = EstimatedPositionsService(db)
    positions = service.get_estimated_positions_for_nucleo(nucleo_id, limit=limit)

    return [
        EstimatedPositionResponse(
            trip_id=p.trip_id,
            route_id=p.route_id,
            route_short_name=p.route_short_name,
            route_color=p.route_color,
            headsign=p.headsign,
            position=PositionSchema(latitude=p.latitude, longitude=p.longitude),
            current_status=p.current_status.value,
            current_stop_id=p.current_stop_id,
            current_stop_name=p.current_stop_name,
            next_stop_id=p.next_stop_id,
            next_stop_name=p.next_stop_name,
            progress_percent=p.progress_percent,
            estimated=True
        )
        for p in positions
    ]


@router.get("/routes/{route_id}/estimated", response_model=List[EstimatedPositionResponse])
def get_estimated_positions_for_route(
    route_id: str,
    limit: int = Query(50, description="Maximum number of results"),
    db: Session = Depends(get_db),
):
    """Get estimated train positions for a specific route."""
    service = EstimatedPositionsService(db)
    positions = service.get_estimated_positions_for_route(route_id, limit=limit)

    return [
        EstimatedPositionResponse(
            trip_id=p.trip_id,
            route_id=p.route_id,
            route_short_name=p.route_short_name,
            route_color=p.route_color,
            headsign=p.headsign,
            position=PositionSchema(latitude=p.latitude, longitude=p.longitude),
            current_status=p.current_status.value,
            current_stop_id=p.current_stop_id,
            current_stop_name=p.current_stop_name,
            next_stop_id=p.next_stop_id,
            next_stop_name=p.next_stop_name,
            progress_percent=p.progress_percent,
            estimated=True
        )
        for p in positions
    ]


# Scheduler status endpoint

class SchedulerStatusResponse(BaseModel):
    running: bool
    last_fetch: Optional[str]
    fetch_count: int
    error_count: int
    interval_seconds: int


@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
def get_scheduler_status():
    """Get the status of the automatic GTFS-RT fetcher.

    The scheduler automatically fetches GTFS-RT data every 30 seconds.
    This endpoint shows the current status and statistics.
    """
    return SchedulerStatusResponse(**gtfs_rt_scheduler.status)


# ============================================================================
# Route Frequencies endpoints
# ============================================================================

class FrequencyPeriodResponse(BaseModel):
    start_time: str  # HH:MM format
    end_time: str    # HH:MM format
    headway_minutes: int
    headway_secs: int


class RouteFrequencyResponse(BaseModel):
    route_id: str
    route_short_name: str
    route_long_name: str
    route_color: Optional[str]
    day_type: str
    periods: List[FrequencyPeriodResponse]


class CurrentFrequencyResponse(BaseModel):
    route_id: str
    route_short_name: str
    route_color: Optional[str]
    day_type: str
    current_headway_minutes: int
    current_period: str  # e.g., "07:00-10:00"
    message: str  # e.g., "Un tren cada 5 minutos"


@router.get("/routes/{route_id}/frequencies", response_model=RouteFrequencyResponse)
def get_route_frequencies(
    route_id: str,
    day_type: str = Query("weekday", description="Day type: weekday, saturday, sunday"),
    db: Session = Depends(get_db),
):
    """Get frequency schedule for a route.

    Returns the headway (time between trains) for different periods of the day.
    """
    # Get route info
    route = db.query(RouteModel).filter(RouteModel.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route {route_id} not found")

    # Get frequencies
    frequencies = db.query(RouteFrequencyModel).filter(
        RouteFrequencyModel.route_id == route_id,
        RouteFrequencyModel.day_type == day_type,
    ).order_by(RouteFrequencyModel.start_time).all()

    if not frequencies:
        raise HTTPException(
            status_code=404,
            detail=f"No frequencies found for route {route_id} on {day_type}"
        )

    periods = [
        FrequencyPeriodResponse(
            start_time=f.start_time.strftime("%H:%M"),
            end_time=f.end_time.strftime("%H:%M"),
            headway_minutes=f.headway_minutes,
            headway_secs=f.headway_secs,
        )
        for f in frequencies
    ]

    return RouteFrequencyResponse(
        route_id=route.id,
        route_short_name=route.short_name,
        route_long_name=route.long_name,
        route_color=route.color,
        day_type=day_type,
        periods=periods,
    )


@router.get("/routes/{route_id}/frequency/current", response_model=CurrentFrequencyResponse)
def get_current_frequency(
    route_id: str,
    db: Session = Depends(get_db),
):
    """Get the current frequency for a route based on current time.

    Returns the headway (time between trains) for the current time period.
    """
    # Get route info
    route = db.query(RouteModel).filter(RouteModel.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route {route_id} not found")

    # Determine day type from current day
    now = datetime.now()
    weekday = now.weekday()
    if weekday == 5:
        day_type = "saturday"
    elif weekday == 6:
        day_type = "sunday"
    else:
        day_type = "weekday"

    current_time = now.time()

    # Find the frequency period for the current time
    frequency = db.query(RouteFrequencyModel).filter(
        RouteFrequencyModel.route_id == route_id,
        RouteFrequencyModel.day_type == day_type,
        RouteFrequencyModel.start_time <= current_time,
        RouteFrequencyModel.end_time > current_time,
    ).first()

    if not frequency:
        # Try to find any frequency for this route
        any_freq = db.query(RouteFrequencyModel).filter(
            RouteFrequencyModel.route_id == route_id
        ).first()

        if not any_freq:
            raise HTTPException(
                status_code=404,
                detail=f"No frequencies found for route {route_id}"
            )

        # Service might be closed
        return CurrentFrequencyResponse(
            route_id=route.id,
            route_short_name=route.short_name,
            route_color=route.color,
            day_type=day_type,
            current_headway_minutes=0,
            current_period="Cerrado",
            message="Servicio cerrado en este horario",
        )

    headway = frequency.headway_minutes
    period = f"{frequency.start_time.strftime('%H:%M')}-{frequency.end_time.strftime('%H:%M')}"

    return CurrentFrequencyResponse(
        route_id=route.id,
        route_short_name=route.short_name,
        route_color=route.color,
        day_type=day_type,
        current_headway_minutes=headway,
        current_period=period,
        message=f"Un tren cada {headway} minutos",
    )


# ============================================================================
# Manual Alerts endpoints
# ============================================================================

class CreateAlertRequest(BaseModel):
    header_text: str
    description_text: Optional[str] = None
    cause: str = "OTHER_CAUSE"
    effect: str = "OTHER_EFFECT"
    route_ids: Optional[List[str]] = None
    stop_ids: Optional[List[str]] = None
    active_period_start: Optional[datetime] = None
    active_period_end: Optional[datetime] = None
    url: Optional[str] = None


class CreateAlertResponse(BaseModel):
    alert_id: str
    message: str


@router.post("/alerts/manual", response_model=CreateAlertResponse)
def create_manual_alert(
    alert: CreateAlertRequest,
    db: Session = Depends(get_db),
):
    """Create a manual service alert.

    Use this to add alerts for Metro or other services that don't have automatic GTFS-RT feeds.
    """
    # Generate unique alert ID
    alert_id = f"MANUAL_{uuid.uuid4().hex[:12].upper()}"

    # Validate cause and effect
    try:
        cause_enum = AlertCauseEnum(alert.cause)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cause. Valid values: {[e.value for e in AlertCauseEnum]}"
        )

    try:
        effect_enum = AlertEffectEnum(alert.effect)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid effect. Valid values: {[e.value for e in AlertEffectEnum]}"
        )

    # Create alert
    alert_model = AlertModel(
        alert_id=alert_id,
        cause=cause_enum,
        effect=effect_enum,
        header_text=alert.header_text,
        description_text=alert.description_text,
        url=alert.url,
        active_period_start=alert.active_period_start,
        active_period_end=alert.active_period_end,
        source='manual',
    )
    db.add(alert_model)

    # Add informed entities
    if alert.route_ids:
        for route_id in alert.route_ids:
            entity = AlertEntityModel(
                alert_id=alert_id,
                route_id=route_id,
            )
            db.add(entity)

    if alert.stop_ids:
        for stop_id in alert.stop_ids:
            entity = AlertEntityModel(
                alert_id=alert_id,
                stop_id=stop_id,
            )
            db.add(entity)

    db.commit()

    return CreateAlertResponse(
        alert_id=alert_id,
        message="Alert created successfully",
    )


@router.delete("/alerts/{alert_id}")
def delete_alert(
    alert_id: str,
    db: Session = Depends(get_db),
):
    """Delete an alert by ID.

    Only manual alerts can be deleted. GTFS-RT alerts are managed automatically.
    """
    alert = db.query(AlertModel).filter(AlertModel.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")

    if alert.source != 'manual':
        raise HTTPException(
            status_code=400,
            detail="Only manual alerts can be deleted. GTFS-RT alerts are managed automatically."
        )

    # Delete entities first
    db.query(AlertEntityModel).filter(AlertEntityModel.alert_id == alert_id).delete()
    db.query(AlertModel).filter(AlertModel.alert_id == alert_id).delete()
    db.commit()

    return {"message": f"Alert {alert_id} deleted successfully"}


@router.get("/alerts/manual", response_model=List[AlertResponse])
def get_manual_alerts(
    active_only: bool = Query(True, description="Only return currently active alerts"),
    db: Session = Depends(get_db),
):
    """Get all manual alerts.

    Returns alerts that were created manually (not from GTFS-RT feeds).
    """
    query = db.query(AlertModel).filter(AlertModel.source == 'manual')

    if active_only:
        now = datetime.utcnow()
        query = query.filter(
            (AlertModel.active_period_start.is_(None)) | (AlertModel.active_period_start <= now),
            (AlertModel.active_period_end.is_(None)) | (AlertModel.active_period_end >= now),
        )

    alerts = query.all()

    return [
        AlertResponse(
            alert_id=a.alert_id,
            cause=a.cause.value,
            effect=a.effect.value,
            header_text=a.header_text,
            description_text=a.description_text,
            url=a.url,
            active_period_start=a.active_period_start,
            active_period_end=a.active_period_end,
            is_active=a.is_active,
            informed_entities=[
                AlertEntityResponse(
                    route_id=e.route_id,
                    stop_id=e.stop_id,
                    trip_id=e.trip_id,
                    agency_id=e.agency_id,
                    route_type=e.route_type,
                )
                for e in a.informed_entities
            ],
            timestamp=a.timestamp,
            updated_at=a.updated_at,
        )
        for a in alerts
    ]
