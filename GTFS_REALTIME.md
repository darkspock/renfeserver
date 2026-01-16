# GTFS Realtime Implementation

## Overview

GTFS-RT (Realtime) provides live updates for transit data including vehicle positions, trip delays, and service alerts. This implementation fetches data from Renfe's official GTFS-RT endpoints and stores it in the database.

**Note:** Renfe's GTFS-RT feeds may be empty at times. The system is ready to capture data when available.

## Data Sources

Renfe provides three GTFS-RT feeds:

| Feed | URL | Description |
|------|-----|-------------|
| Vehicle Positions | `https://gtfsrt.renfe.com/vehicle_positions.json` | Live train locations |
| Trip Updates | `https://gtfsrt.renfe.com/trip_updates.json` | Delays and schedule changes |
| Alerts | `https://gtfsrt.renfe.com/alerts.json` | Service disruptions and notices |

## Database Tables

### GTFS-RT Tables (created in migration 002 and 014)

```sql
-- Vehicle positions (real-time train locations)
gtfs_rt_vehicle_positions
  - vehicle_id (PK)
  - trip_id
  - latitude, longitude
  - current_status (INCOMING_AT, STOPPED_AT, IN_TRANSIT_TO)
  - stop_id
  - timestamp

-- Trip updates (delays)
gtfs_rt_trip_updates
  - trip_id (PK)
  - delay (seconds)
  - vehicle_id
  - timestamp

-- Stop time updates (per-stop delays)
gtfs_rt_stop_time_updates
  - trip_id (FK)
  - stop_id
  - arrival_delay, departure_delay (seconds)
  - arrival_time, departure_time

-- Alerts (service disruptions)
gtfs_rt_alerts
  - alert_id (PK)
  - cause (MAINTENANCE, STRIKE, WEATHER, etc.)
  - effect (NO_SERVICE, REDUCED_SERVICE, SIGNIFICANT_DELAYS, etc.)
  - header_text, description_text
  - active_period_start, active_period_end

-- Alert entities (what's affected)
gtfs_rt_alert_entities
  - alert_id (FK)
  - route_id, stop_id, trip_id
```

## API Endpoints

### Fetch/Update Data

```
POST /api/v1/gtfs/realtime/fetch
```
Fetches all three GTFS-RT feeds and stores in database. Returns counts:
```json
{
  "vehicle_positions": 45,
  "trip_updates": 120,
  "alerts": 52,
  "message": "GTFS-RT data fetched and stored successfully"
}
```

### Vehicle Positions

```
GET /api/v1/gtfs/realtime/vehicles
GET /api/v1/gtfs/realtime/vehicles/{vehicle_id}
```
Query params: `stop_id`, `trip_id`

### Trip Delays

```
GET /api/v1/gtfs/realtime/delays
GET /api/v1/gtfs/realtime/stops/{stop_id}/delays
```
Query params: `min_delay`, `trip_id`

### Service Alerts

```
GET /api/v1/gtfs/realtime/alerts
GET /api/v1/gtfs/realtime/routes/{route_id}/alerts
GET /api/v1/gtfs/realtime/stops/{stop_id}/alerts
```
Query params: `route_id`, `stop_id`, `active_only`

### Departures (with integrated delays)

```
GET /api/v1/gtfs/stops/{stop_id}/departures
```
Returns scheduled departures with realtime delay information:
```json
{
  "trip_id": "6012V26500C3",
  "route_id": "RENFE_C3_28",
  "route_short_name": "C3",
  "departure_time": "05:00:00",
  "minutes_until": 48,
  "delay_seconds": 180,
  "realtime_departure_time": "05:03:00",
  "realtime_minutes_until": 51,
  "is_delayed": true
}
```

## Files Modified/Created

### New Files
- `src/gtfs_bc/realtime/domain/entities/alert.py` - Alert domain entity
- `src/gtfs_bc/realtime/infrastructure/models/alert.py` - Alert SQLAlchemy models
- `alembic/versions/014_create_gtfs_rt_alerts_tables.py` - Database migration

### Modified Files
- `src/gtfs_bc/realtime/infrastructure/services/gtfs_rt_fetcher.py` - Added alerts support
- `adapters/http/api/gtfs/routers/realtime_router.py` - Added alerts endpoints
- `adapters/http/api/gtfs/routers/query_router.py` - Integrated delays into /departures

## Usage

### Manual Fetch
```bash
curl -X POST https://redcercanias.com/api/v1/gtfs/realtime/fetch
```

### Periodic Updates (Cron)
For production, set up a cron job or scheduled task to fetch data every 30-60 seconds:
```bash
*/1 * * * * curl -s -X POST https://redcercanias.com/api/v1/gtfs/realtime/fetch > /dev/null
```

## Notes

- Vehicle positions and trip updates are typically empty during night hours (no trains running)
- Alerts persist until their `active_period_end` or until updated by Renfe
- The `/departures` endpoint automatically includes delay info when available
- Route IDs in alerts use GTFS format (e.g., `10T0025C9`) not our format (`RENFE_C9_34`)
