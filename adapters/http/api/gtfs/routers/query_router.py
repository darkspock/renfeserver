from typing import List, Optional
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

MADRID_TZ = ZoneInfo("Europe/Madrid")

from core.database import get_db
from src.gtfs_bc.route.infrastructure.models import RouteModel
from src.gtfs_bc.stop.infrastructure.models import StopModel
from src.gtfs_bc.trip.infrastructure.models import TripModel
from src.gtfs_bc.stop_time.infrastructure.models import StopTimeModel
from src.gtfs_bc.calendar.infrastructure.models import CalendarModel, CalendarDateModel
from src.gtfs_bc.agency.infrastructure.models import AgencyModel
from src.gtfs_bc.nucleo.infrastructure.models import NucleoModel
from src.gtfs_bc.realtime.infrastructure.models import TripUpdateModel, StopTimeUpdateModel, VehiclePositionModel, PlatformHistoryModel
from src.gtfs_bc.province.province_lookup import (
    get_province_by_coordinates,
    get_province_and_nucleo_by_coordinates,
)
from src.gtfs_bc.realtime.infrastructure.services.estimated_positions import EstimatedPositionsService


router = APIRouter(prefix="/gtfs", tags=["GTFS Query"])


# Response schemas
class RouteResponse(BaseModel):
    id: str
    short_name: str
    long_name: str
    route_type: int
    color: Optional[str]
    text_color: Optional[str]
    agency_id: str
    nucleo_id: Optional[int]
    nucleo_name: Optional[str]

    class Config:
        from_attributes = True


class StopResponse(BaseModel):
    id: str
    name: str
    lat: float
    lon: float
    code: Optional[str]
    location_type: int
    parent_station_id: Optional[str]
    zone_id: Optional[str]
    province: Optional[str]
    nucleo_id: Optional[int]
    nucleo_name: Optional[str]
    lineas: Optional[str]
    parking_bicis: Optional[str]
    accesibilidad: Optional[str]
    cor_bus: Optional[str]
    cor_metro: Optional[str]

    class Config:
        from_attributes = True


class TrainPositionSchema(BaseModel):
    """Current position of the train."""
    latitude: float
    longitude: float
    current_stop_name: str
    status: str  # STOPPED_AT, IN_TRANSIT_TO, INCOMING_AT
    progress_percent: float
    estimated: bool = True  # True if calculated from schedule, False if from GTFS-RT


class DepartureResponse(BaseModel):
    trip_id: str
    route_id: str
    route_short_name: str
    route_color: Optional[str]
    headsign: Optional[str]
    departure_time: str
    departure_seconds: int
    minutes_until: int
    stop_sequence: int
    # Platform/track info (from GTFS-RT when available, or estimated from history)
    platform: Optional[str] = None
    platform_estimated: bool = False  # True if platform is estimated from history
    # Realtime delay fields
    delay_seconds: Optional[int] = None
    realtime_departure_time: Optional[str] = None
    realtime_minutes_until: Optional[int] = None
    is_delayed: bool = False
    # Train position (from GTFS-RT or estimated)
    train_position: Optional[TrainPositionSchema] = None


class TripStopResponse(BaseModel):
    stop_id: str
    stop_name: str
    arrival_time: str
    departure_time: str
    stop_sequence: int
    stop_lat: float
    stop_lon: float


class TripDetailResponse(BaseModel):
    id: str
    route_id: str
    route_short_name: str
    route_long_name: str
    route_color: Optional[str]
    headsign: Optional[str]
    direction_id: Optional[int]
    stops: List[TripStopResponse]


class AgencyResponse(BaseModel):
    id: str
    name: str
    url: Optional[str]
    timezone: str
    lang: Optional[str]
    phone: Optional[str]

    class Config:
        from_attributes = True


class NucleoResponse(BaseModel):
    id: int
    name: str
    color: Optional[str]
    bounding_box_min_lat: Optional[float]
    bounding_box_max_lat: Optional[float]
    bounding_box_min_lon: Optional[float]
    bounding_box_max_lon: Optional[float]
    center_lat: Optional[float]
    center_lon: Optional[float]
    stations_count: Optional[int]
    lines_count: Optional[int]

    class Config:
        from_attributes = True


@router.get("/agencies", response_model=List[AgencyResponse])
def get_agencies(db: Session = Depends(get_db)):
    """Get all agencies."""
    agencies = db.query(AgencyModel).all()
    return agencies


@router.get("/nucleos", response_model=List[NucleoResponse])
def get_nucleos(db: Session = Depends(get_db)):
    """Get all Renfe regional networks (núcleos)."""
    nucleos = db.query(NucleoModel).order_by(NucleoModel.id).all()

    # Add stations and lines counts
    result = []
    for nucleo in nucleos:
        stations_count = db.query(func.count(StopModel.id)).filter(
            StopModel.nucleo_id == nucleo.id
        ).scalar()
        lines_count = db.query(func.count(RouteModel.id)).filter(
            RouteModel.nucleo_id == nucleo.id
        ).scalar()

        result.append(
            NucleoResponse(
                id=nucleo.id,
                name=nucleo.name,
                color=nucleo.color,
                bounding_box_min_lat=nucleo.bounding_box_min_lat,
                bounding_box_max_lat=nucleo.bounding_box_max_lat,
                bounding_box_min_lon=nucleo.bounding_box_min_lon,
                bounding_box_max_lon=nucleo.bounding_box_max_lon,
                center_lat=nucleo.center_lat,
                center_lon=nucleo.center_lon,
                stations_count=stations_count,
                lines_count=lines_count,
            )
        )

    return result


@router.get("/nucleos/{nucleo_id}", response_model=NucleoResponse)
def get_nucleo(nucleo_id: int, db: Session = Depends(get_db)):
    """Get a specific núcleo by ID."""
    nucleo = db.query(NucleoModel).filter(NucleoModel.id == nucleo_id).first()
    if not nucleo:
        raise HTTPException(status_code=404, detail=f"Nucleo {nucleo_id} not found")

    # Count associated stops and routes
    stations_count = db.query(func.count(StopModel.id)).filter(
        StopModel.nucleo_id == nucleo_id
    ).scalar()
    lines_count = db.query(func.count(RouteModel.id)).filter(
        RouteModel.nucleo_id == nucleo_id
    ).scalar()

    return NucleoResponse(
        id=nucleo.id,
        name=nucleo.name,
        color=nucleo.color,
        bounding_box_min_lat=nucleo.bounding_box_min_lat,
        bounding_box_max_lat=nucleo.bounding_box_max_lat,
        bounding_box_min_lon=nucleo.bounding_box_min_lon,
        bounding_box_max_lon=nucleo.bounding_box_max_lon,
        center_lat=nucleo.center_lat,
        center_lon=nucleo.center_lon,
        stations_count=stations_count,
        lines_count=lines_count,
    )


@router.get("/routes", response_model=List[RouteResponse])
def get_routes(
    agency_id: Optional[str] = Query(None, description="Filter by agency ID"),
    nucleo_id: Optional[int] = Query(None, description="Filter by núcleo ID"),
    nucleo_name: Optional[str] = Query(None, description="Filter by núcleo name"),
    search: Optional[str] = Query(None, description="Search by name"),
    db: Session = Depends(get_db),
):
    """Get all routes/lines.

    Optionally filter by agency, núcleo, or search by name.

    Note: When a base route (e.g., C4) has variants (C4A, C4B), only the variants
    are returned. Base routes without variants are also returned.
    """
    query = db.query(RouteModel)

    if agency_id:
        query = query.filter(RouteModel.agency_id == agency_id)

    if nucleo_id:
        query = query.filter(RouteModel.nucleo_id == nucleo_id)

    if nucleo_name:
        query = query.filter(RouteModel.nucleo_name.ilike(f"%{nucleo_name}%"))

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                RouteModel.short_name.ilike(search_term),
                RouteModel.long_name.ilike(search_term),
            )
        )

    routes = query.order_by(RouteModel.short_name).all()

    # Filter out base routes that have variants
    # e.g., if C4A and C4B exist, exclude C4
    filtered_routes = []
    base_routes_with_variants = set()

    # Normalize route names for comparison (strip whitespace)
    routes_by_name = {}
    for route in routes:
        short_name = route.short_name.strip() if route.short_name else ""
        if short_name:
            routes_by_name[short_name] = route

    # First pass: identify base routes that have variants
    for short_name in routes_by_name.keys():
        # Check if this is a variant (ends with a single letter A-Z)
        if short_name and short_name[-1].isalpha() and len(short_name) > 1:
            # Extract base name (e.g., "C4" from "C4A")
            base_name = short_name[:-1]
            # Check if base route exists (case-insensitive)
            if any(name.lower() == base_name.lower() for name in routes_by_name.keys()):
                base_routes_with_variants.add(base_name.lower())

    # Second pass: include routes, excluding base routes with variants
    for route in routes:
        short_name = route.short_name.strip() if route.short_name else ""
        if short_name.lower() not in base_routes_with_variants:
            filtered_routes.append(route)

    return filtered_routes


@router.get("/coordinates/routes", response_model=List[RouteResponse])
def get_routes_by_coordinates(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (e.g., 40.42 for Madrid)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (e.g., -3.72 for Madrid)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get all routes/lines from the núcleo determined by the given coordinates.

    The endpoint automatically calculates which province the coordinates belong to,
    then maps it to the corresponding Renfe regional network (núcleo),
    and returns all routes in that núcleo.

    Flow:
    1. Coordinates → Find Province (PostGIS)
    2. Province → Find Nucleo (province mapping)
    3. Nucleo → Return Routes

    If coordinates are outside Spain or in a province without Renfe service,
    returns empty list (no error).

    For Madrid example: lat=40.42&lon=-3.72
    """
    # Step 1: Determine province and nucleo from coordinates
    result = get_province_and_nucleo_by_coordinates(db, lat, lon)

    if not result:
        # Coordinates are outside Spain - return empty list
        return []

    province_name, nucleo_name = result

    # Step 2: If nucleo_name is None, province has no Renfe service - return empty list
    if not nucleo_name:
        return []

    # Step 3: Get all routes in the determined nucleo
    routes = (
        db.query(RouteModel)
        .filter(RouteModel.nucleo_name == nucleo_name)
        .order_by(RouteModel.short_name)
        .limit(limit)
        .all()
    )

    return routes


@router.get("/routes/{route_id}", response_model=RouteResponse)
def get_route(route_id: str, db: Session = Depends(get_db)):
    """Get a specific route by ID.

    Note: This endpoint requires a specific route_id and won't match /routes/by-coordinates
    """
    if route_id == "by-coordinates":
        raise HTTPException(status_code=400, detail="Use /routes/by-coordinates endpoint with lat/lon parameters")

    route = db.query(RouteModel).filter(RouteModel.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route {route_id} not found")
    return route


@router.get("/stops", response_model=List[StopResponse])
def get_stops(
    search: Optional[str] = Query(None, description="Search by name"),
    nucleo_id: Optional[int] = Query(None, description="Filter by núcleo ID"),
    nucleo_name: Optional[str] = Query(None, description="Filter by núcleo name"),
    location_type: Optional[int] = Query(None, description="Filter by location type (0=stop, 1=station)"),
    parent_station: Optional[str] = Query(None, description="Filter by parent station ID"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get all stops/stations.

    Optionally filter by name search, núcleo, location type, or parent station.
    """
    query = db.query(StopModel)

    if search:
        search_term = f"%{search}%"
        query = query.filter(StopModel.name.ilike(search_term))

    if nucleo_id:
        query = query.filter(StopModel.nucleo_id == nucleo_id)

    if nucleo_name:
        query = query.filter(StopModel.nucleo_name.ilike(f"%{nucleo_name}%"))

    if location_type is not None:
        query = query.filter(StopModel.location_type == location_type)

    if parent_station:
        query = query.filter(StopModel.parent_station_id == parent_station)

    stops = query.order_by(StopModel.name).limit(limit).all()
    return stops


@router.get("/stops/by-nucleo", response_model=List[StopResponse])
def get_stops_by_nucleo(
    nucleo_id: Optional[int] = Query(None, description="Núcleo ID"),
    nucleo_name: Optional[str] = Query(None, description="Núcleo name"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get all stops in a specific núcleo.

    Filter by either nucleo_id or nucleo_name.
    """
    if not nucleo_id and not nucleo_name:
        raise HTTPException(
            status_code=400,
            detail="Must provide either nucleo_id or nucleo_name parameter"
        )

    query = db.query(StopModel)

    if nucleo_id:
        query = query.filter(StopModel.nucleo_id == nucleo_id)
    else:
        query = query.filter(StopModel.nucleo_name.ilike(f"%{nucleo_name}%"))

    stops = query.order_by(StopModel.name).limit(limit).all()

    if not stops and nucleo_id:
        raise HTTPException(
            status_code=404,
            detail=f"No stops found for nucleoId {nucleo_id}"
        )

    return stops


@router.get("/stops/by-coordinates", response_model=List[StopResponse])
def get_stops_by_coordinates(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (e.g., 40.42 for Madrid)"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude (e.g., -3.72 for Madrid)"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get all stops from the núcleo determined by the given coordinates.

    The endpoint automatically calculates which province the coordinates belong to,
    then maps it to the corresponding Renfe regional network (núcleo),
    and returns all stops in that núcleo.

    Flow:
    1. Coordinates → Find Province (PostGIS)
    2. Province → Find Nucleo (province mapping)
    3. Nucleo → Return Stops

    If coordinates are outside Spain or in a province without Renfe service,
    returns empty list (no error).

    For Madrid example: lat=40.42&lon=-3.72
    """
    # Step 1: Determine province and nucleo from coordinates
    result = get_province_and_nucleo_by_coordinates(db, lat, lon)

    if not result:
        # Coordinates are outside Spain - return empty list
        return []

    province_name, nucleo_name = result

    # Step 2: If nucleo_name is None, province has no Renfe service - return empty list
    if not nucleo_name:
        return []

    # Step 3: Get all stops in the determined nucleo
    stops = (
        db.query(StopModel)
        .filter(StopModel.nucleo_name == nucleo_name)
        .order_by(StopModel.name)
        .limit(limit)
        .all()
    )

    return stops


@router.get("/stops/{stop_id}", response_model=StopResponse)
def get_stop(stop_id: str, db: Session = Depends(get_db)):
    """Get a specific stop by ID."""
    stop = db.query(StopModel).filter(StopModel.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail=f"Stop {stop_id} not found")
    return stop


@router.get("/stops/{stop_id}/departures", response_model=List[DepartureResponse])
def get_stop_departures(
    stop_id: str,
    route_id: Optional[str] = Query(None, description="Filter by route ID"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
    db: Session = Depends(get_db),
):
    """Get upcoming departures from a stop.

    Returns the next departures from this stop, filtered by current time and active services.
    """
    # Verify stop exists
    stop = db.query(StopModel).filter(StopModel.id == stop_id).first()
    if not stop:
        raise HTTPException(status_code=404, detail=f"Stop {stop_id} not found")

    # Get current time in seconds since midnight (Madrid timezone)
    now = datetime.now(MADRID_TZ)
    current_seconds = now.hour * 3600 + now.minute * 60 + now.second
    today = now.date()
    weekday = today.weekday()  # 0=Monday, 6=Sunday

    # Map weekday to calendar column
    weekday_columns = {
        0: CalendarModel.monday,
        1: CalendarModel.tuesday,
        2: CalendarModel.wednesday,
        3: CalendarModel.thursday,
        4: CalendarModel.friday,
        5: CalendarModel.saturday,
        6: CalendarModel.sunday,
    }

    # Get active service IDs for today
    # 1. Services from calendar that are active today
    active_services_query = db.query(CalendarModel.service_id).filter(
        CalendarModel.start_date <= today,
        CalendarModel.end_date >= today,
        weekday_columns[weekday] == True,
    )

    # 2. Add exceptions (type 1 = added)
    added_services = db.query(CalendarDateModel.service_id).filter(
        CalendarDateModel.date == today,
        CalendarDateModel.exception_type == 1,
    )

    # 3. Remove exceptions (type 2 = removed)
    removed_services = db.query(CalendarDateModel.service_id).filter(
        CalendarDateModel.date == today,
        CalendarDateModel.exception_type == 2,
    )

    active_service_ids = set(
        [s.service_id for s in active_services_query.all()] +
        [s.service_id for s in added_services.all()]
    ) - set([s.service_id for s in removed_services.all()])

    if not active_service_ids:
        return []

    # Query stop times with upcoming departures
    # Subquery to get the max stop_sequence for each trip (to filter out last stops)
    max_sequence_subquery = (
        db.query(
            StopTimeModel.trip_id,
            func.max(StopTimeModel.stop_sequence).label("max_seq")
        )
        .group_by(StopTimeModel.trip_id)
        .subquery()
    )

    query = (
        db.query(StopTimeModel, TripModel, RouteModel)
        .join(TripModel, StopTimeModel.trip_id == TripModel.id)
        .join(RouteModel, TripModel.route_id == RouteModel.id)
        .join(
            max_sequence_subquery,
            StopTimeModel.trip_id == max_sequence_subquery.c.trip_id
        )
        .filter(
            StopTimeModel.stop_id == stop_id,
            StopTimeModel.departure_seconds >= current_seconds,
            TripModel.service_id.in_(active_service_ids),
            # Exclude trips where this stop is the last stop (train arrives, doesn't depart)
            StopTimeModel.stop_sequence < max_sequence_subquery.c.max_seq,
        )
    )

    if route_id:
        query = query.filter(TripModel.route_id == route_id)

    results = (
        query
        .order_by(StopTimeModel.departure_seconds)
        .limit(limit)
        .all()
    )

    # Get trip IDs for realtime delay lookup
    trip_ids = [trip.id for _, trip, _ in results]

    # Get trip-level delays
    trip_delays = {}
    if trip_ids:
        trip_updates = db.query(TripUpdateModel).filter(
            TripUpdateModel.trip_id.in_(trip_ids)
        ).all()
        trip_delays = {tu.trip_id: tu.delay for tu in trip_updates}

    # Get stop-specific delays and platform info
    stop_delays = {}
    stop_platforms = {}
    if trip_ids:
        stop_time_updates = db.query(StopTimeUpdateModel).filter(
            StopTimeUpdateModel.trip_id.in_(trip_ids),
            StopTimeUpdateModel.stop_id == stop_id,
        ).all()
        for stu in stop_time_updates:
            stop_delays[stu.trip_id] = stu.departure_delay
            if stu.platform:
                stop_platforms[stu.trip_id] = stu.platform

    # Get train positions: first try GTFS-RT, then fall back to estimated
    train_positions = {}

    # 1. Try GTFS-RT vehicle positions
    vehicle_platforms = {}
    # Extract numeric stop_id for comparison (e.g., "17000" from "RENFE_17000")
    queried_stop_numeric = stop_id.replace("RENFE_", "") if stop_id.startswith("RENFE_") else stop_id

    if trip_ids:
        vehicle_positions = db.query(VehiclePositionModel).filter(
            VehiclePositionModel.trip_id.in_(trip_ids)
        ).all()
        for vp in vehicle_positions:
            # Get current stop name from stop_id (try with RENFE_ prefix)
            current_stop = None
            if vp.stop_id:
                current_stop = db.query(StopModel).filter(StopModel.id == f"RENFE_{vp.stop_id}").first()
                if not current_stop:
                    current_stop = db.query(StopModel).filter(StopModel.id == vp.stop_id).first()

            status = vp.current_status.value if vp.current_status else "IN_TRANSIT_TO"
            train_positions[vp.trip_id] = TrainPositionSchema(
                latitude=vp.latitude,
                longitude=vp.longitude,
                current_stop_name=current_stop.name if current_stop else "En tránsito",
                status=status,
                progress_percent=50.0,  # GTFS-RT doesn't provide progress
                estimated=False  # This is real GTFS-RT data
            )

            # Only store platform if train is AT or INCOMING to the queried stop
            # Compare stop_ids (handle both "17000" and "RENFE_17000" formats)
            vp_stop_numeric = vp.stop_id.replace("RENFE_", "") if vp.stop_id and vp.stop_id.startswith("RENFE_") else vp.stop_id
            train_at_queried_stop = vp_stop_numeric == queried_stop_numeric

            if vp.platform and train_at_queried_stop and status in ("STOPPED_AT", "INCOMING_AT"):
                vehicle_platforms[vp.trip_id] = vp.platform

    # 2. For trips without GTFS-RT, get estimated positions
    trips_without_position = [tid for tid in trip_ids if tid not in train_positions]
    if trips_without_position:
        estimated_service = EstimatedPositionsService(db)
        # Get estimated positions for the specific trips we need
        estimated_positions = estimated_service.get_estimated_positions(
            trip_ids=trips_without_position,
            limit=len(trips_without_position)
        )
        for ep in estimated_positions:
            train_positions[ep.trip_id] = TrainPositionSchema(
                latitude=ep.latitude,
                longitude=ep.longitude,
                current_stop_name=ep.current_stop_name,
                status=ep.current_status.value,
                progress_percent=ep.progress_percent,
                estimated=True
            )

    # Helper function to get estimated platform from history
    def get_estimated_platform(route_short: str, headsign: str) -> Optional[str]:
        """Get most likely platform from historical data.

        Looks at today's data first, then yesterday's if no data for today.
        Uses the platform with highest count (most commonly used).
        """
        from datetime import date, timedelta
        today_date = date.today()
        yesterday = today_date - timedelta(days=1)

        # Try today first
        history = db.query(PlatformHistoryModel).filter(
            PlatformHistoryModel.stop_id == queried_stop_numeric,
            PlatformHistoryModel.route_short_name == route_short,
            PlatformHistoryModel.headsign == headsign,
            PlatformHistoryModel.observation_date == today_date,
        ).order_by(PlatformHistoryModel.count.desc()).first()

        if history:
            return history.platform

        # Fall back to yesterday
        history = db.query(PlatformHistoryModel).filter(
            PlatformHistoryModel.stop_id == queried_stop_numeric,
            PlatformHistoryModel.route_short_name == route_short,
            PlatformHistoryModel.headsign == headsign,
            PlatformHistoryModel.observation_date == yesterday,
        ).order_by(PlatformHistoryModel.count.desc()).first()

        return history.platform if history else None

    departures = []
    for stop_time, trip, route in results:
        minutes_until = (stop_time.departure_seconds - current_seconds) // 60

        # Get delay: prefer stop-specific delay, fall back to trip delay
        delay_seconds = stop_delays.get(trip.id) or trip_delays.get(trip.id)
        realtime_departure_time = None
        realtime_minutes_until = None
        is_delayed = False

        if delay_seconds is not None and delay_seconds != 0:
            is_delayed = delay_seconds > 60  # More than 1 minute delay
            realtime_departure_seconds = stop_time.departure_seconds + delay_seconds
            # Convert to HH:MM:SS format
            rt_hours = realtime_departure_seconds // 3600
            rt_minutes = (realtime_departure_seconds % 3600) // 60
            rt_seconds = realtime_departure_seconds % 60
            realtime_departure_time = f"{rt_hours:02d}:{rt_minutes:02d}:{rt_seconds:02d}"
            realtime_minutes_until = max(0, (realtime_departure_seconds - current_seconds) // 60)

        # Get train position (from GTFS-RT or estimated)
        train_position = train_positions.get(trip.id)

        # Get platform from GTFS-RT (prefer stop_time_update, then vehicle_position)
        platform = stop_platforms.get(trip.id) or vehicle_platforms.get(trip.id)
        platform_estimated = False

        # If no real platform, try to get estimated from history
        if not platform:
            route_short = route.short_name.strip() if route.short_name else ""
            estimated = get_estimated_platform(route_short, trip.headsign or "")
            if estimated:
                platform = estimated
                platform_estimated = True

        departures.append(
            DepartureResponse(
                trip_id=trip.id,
                route_id=route.id,
                route_short_name=route.short_name.strip() if route.short_name else "",
                route_color=route.color,
                headsign=trip.headsign,
                departure_time=stop_time.departure_time,
                departure_seconds=stop_time.departure_seconds,
                minutes_until=minutes_until,
                stop_sequence=stop_time.stop_sequence,
                platform=platform,
                platform_estimated=platform_estimated,
                delay_seconds=delay_seconds,
                realtime_departure_time=realtime_departure_time,
                realtime_minutes_until=realtime_minutes_until,
                is_delayed=is_delayed,
                train_position=train_position,
            )
        )

    # Sort by realtime departure (use realtime_minutes_until if available, else minutes_until)
    departures.sort(key=lambda d: d.realtime_minutes_until if d.realtime_minutes_until is not None else d.minutes_until)

    return departures


@router.get("/trips/{trip_id}", response_model=TripDetailResponse)
def get_trip(trip_id: str, db: Session = Depends(get_db)):
    """Get details for a specific trip including all stops."""
    trip = db.query(TripModel).filter(TripModel.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail=f"Trip {trip_id} not found")

    route = db.query(RouteModel).filter(RouteModel.id == trip.route_id).first()

    # Get all stop times for this trip with stop info
    stop_times = (
        db.query(StopTimeModel, StopModel)
        .join(StopModel, StopTimeModel.stop_id == StopModel.id)
        .filter(StopTimeModel.trip_id == trip_id)
        .order_by(StopTimeModel.stop_sequence)
        .all()
    )

    stops = [
        TripStopResponse(
            stop_id=stop.id,
            stop_name=stop.name,
            arrival_time=stop_time.arrival_time,
            departure_time=stop_time.departure_time,
            stop_sequence=stop_time.stop_sequence,
            stop_lat=stop.lat,
            stop_lon=stop.lon,
        )
        for stop_time, stop in stop_times
    ]

    return TripDetailResponse(
        id=trip.id,
        route_id=trip.route_id,
        route_short_name=route.short_name.strip() if route and route.short_name else "",
        route_long_name=route.long_name.strip() if route and route.long_name else "",
        route_color=route.color if route else None,
        headsign=trip.headsign,
        direction_id=trip.direction_id,
        stops=stops,
    )


@router.get("/routes/{route_id}/stops", response_model=List[StopResponse])
def get_route_stops(route_id: str, db: Session = Depends(get_db)):
    """Get all stops served by a route, ordered by their position along the route.

    Stops are ordered by their sequence position based on the closest point on the
    route's LineString geometry from the Renfe GeoJSON data.
    """
    from src.gtfs_bc.stop_route_sequence.infrastructure.models import StopRouteSequenceModel

    # Verify route exists
    route = db.query(RouteModel).filter(RouteModel.id == route_id).first()
    if not route:
        raise HTTPException(status_code=404, detail=f"Route {route_id} not found")

    # Query stops using the stop_route_sequence table to get proper ordering
    stops = (
        db.query(StopModel)
        .join(
            StopRouteSequenceModel,
            StopModel.id == StopRouteSequenceModel.stop_id
        )
        .filter(StopRouteSequenceModel.route_id == route_id)
        .order_by(StopRouteSequenceModel.sequence)
        .all()
    )

    # If no sequences found, fallback to lineas-based search with alphabetical order
    if not stops:
        short_name = route.short_name
        stops = (
            db.query(StopModel)
            .filter(
                and_(
                    StopModel.nucleo_id == route.nucleo_id,
                    StopModel.lineas.isnot(None),
                    or_(
                        StopModel.lineas == short_name,
                        StopModel.lineas.startswith(f"{short_name},"),
                        StopModel.lineas.endswith(f",{short_name}"),
                        StopModel.lineas.contains(f",{short_name},"),
                    )
                )
            )
            .order_by(StopModel.name)
            .all()
        )

    return stops
