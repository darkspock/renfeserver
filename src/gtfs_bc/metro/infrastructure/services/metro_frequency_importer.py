"""Service to import Metro Madrid frequencies from GTFS."""
import csv
import logging
import zipfile
from datetime import time
from io import TextIOWrapper
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from src.gtfs_bc.route.infrastructure.models import RouteModel, RouteFrequencyModel

logger = logging.getLogger(__name__)


# Mapping from CRTM GTFS route IDs to our Metro route IDs
CRTM_TO_METRO_ROUTE = {
    # Metro Madrid
    '4__1___': 'METRO_1',
    '4__2___': 'METRO_2',
    '4__3___': 'METRO_3',
    '4__4___': 'METRO_4',
    '4__5___': 'METRO_5',
    '4__6___': 'METRO_6',
    '4__7___': 'METRO_7',
    '4__8___': 'METRO_8',
    '4__9___': 'METRO_9',
    '4__10___': 'METRO_10',
    '4__11___': 'METRO_11',
    '4__12___': 'METRO_12',
    '4__R___': 'METRO_R',
    # Metro Ligero
    '10__ML1___': 'ML_ML1',
    '10__ML2___': 'ML_ML2',
    '10__ML3___': 'ML_ML3',
    '10__ML4___': 'ML_ML4',
}

# Mapping from CRTM service IDs to day types
# I12 = Laborables (weekday), I13 = Sabados (saturday), I14 = Domingos (sunday), I15 = Festivos (holiday)
SERVICE_TO_DAY_TYPE = {
    'I12': 'weekday',
    'I13': 'saturday',
    'I14': 'sunday',
    'I15': 'sunday',  # Treat holidays as Sunday schedule
}


class MetroFrequencyImporter:
    """Import Metro Madrid frequencies from GTFS zip file."""

    def __init__(self, db: Session):
        self.db = db

    def import_from_gtfs_zip(self, gtfs_zip_path: str, clear_prefix: str = 'METRO_%') -> Dict[str, int]:
        """Import frequencies from a GTFS zip file.

        Args:
            gtfs_zip_path: Path to the GTFS zip file (e.g., google_transit_M4.zip)
            clear_prefix: SQL LIKE pattern for routes to clear before importing

        Returns:
            Dict with import statistics
        """
        logger.info(f"Importing frequencies from {gtfs_zip_path}")

        # Load trip → route mapping
        trip_to_route = self._load_trips(gtfs_zip_path)
        logger.info(f"Loaded {len(trip_to_route)} trip mappings")

        # Load and process frequencies
        frequencies = self._load_frequencies(gtfs_zip_path, trip_to_route)
        logger.info(f"Loaded {len(frequencies)} frequency records")

        # Clear existing frequencies for the specified routes
        deleted = self.db.query(RouteFrequencyModel).filter(
            RouteFrequencyModel.route_id.like(clear_prefix)
        ).delete(synchronize_session=False)
        logger.info(f"Deleted {deleted} existing frequency records for {clear_prefix}")

        # Insert new frequencies
        count = 0
        for freq in frequencies:
            # Verify route exists
            route = self.db.query(RouteModel).filter(RouteModel.id == freq['route_id']).first()
            if not route:
                logger.warning(f"Route {freq['route_id']} not found, skipping frequency")
                continue

            freq_model = RouteFrequencyModel(
                route_id=freq['route_id'],
                start_time=freq['start_time'],
                end_time=freq['end_time'],
                headway_secs=freq['headway_secs'],
                day_type=freq['day_type'],
            )
            self.db.add(freq_model)
            count += 1

        self.db.commit()
        logger.info(f"Imported {count} frequency records")

        return {
            'trips_loaded': len(trip_to_route),
            'frequencies_imported': count,
        }

    def import_all_metro_frequencies(
        self,
        metro_gtfs_path: str,
        metro_ligero_gtfs_path: str,
    ) -> Dict[str, int]:
        """Import frequencies from both Metro and Metro Ligero GTFS files.

        Args:
            metro_gtfs_path: Path to Metro Madrid GTFS zip
            metro_ligero_gtfs_path: Path to Metro Ligero GTFS zip

        Returns:
            Combined import statistics
        """
        # Import Metro Madrid
        metro_stats = self.import_from_gtfs_zip(metro_gtfs_path, clear_prefix='METRO_%')

        # Import Metro Ligero
        ml_stats = self.import_from_gtfs_zip(metro_ligero_gtfs_path, clear_prefix='ML_%')

        return {
            'metro_trips_loaded': metro_stats['trips_loaded'],
            'metro_frequencies_imported': metro_stats['frequencies_imported'],
            'ml_trips_loaded': ml_stats['trips_loaded'],
            'ml_frequencies_imported': ml_stats['frequencies_imported'],
            'total_frequencies': metro_stats['frequencies_imported'] + ml_stats['frequencies_imported'],
        }

    def _load_trips(self, gtfs_zip_path: str) -> Dict[str, str]:
        """Load trip_id → route_id mapping from trips.txt."""
        trip_to_route = {}

        with zipfile.ZipFile(gtfs_zip_path, 'r') as zf:
            with zf.open('trips.txt') as f:
                # Handle BOM
                reader = csv.DictReader(TextIOWrapper(f, 'utf-8-sig'))
                for row in reader:
                    trip_id = row['trip_id']
                    crtm_route_id = row['route_id']

                    # Map to our Metro route ID
                    metro_route_id = CRTM_TO_METRO_ROUTE.get(crtm_route_id)
                    if metro_route_id:
                        # Also store service_id for day type mapping
                        service_id = row.get('service_id', '')
                        trip_to_route[trip_id] = {
                            'route_id': metro_route_id,
                            'service_id': service_id,
                        }

        return trip_to_route

    def _load_frequencies(
        self, gtfs_zip_path: str, trip_to_route: Dict[str, dict]
    ) -> List[dict]:
        """Load and deduplicate frequencies from frequencies.txt."""
        # Use dict to deduplicate by (route_id, day_type, start_time, end_time)
        freq_map: Dict[tuple, dict] = {}

        with zipfile.ZipFile(gtfs_zip_path, 'r') as zf:
            with zf.open('frequencies.txt') as f:
                reader = csv.DictReader(TextIOWrapper(f, 'utf-8-sig'))
                for row in reader:
                    trip_id = row['trip_id']

                    if trip_id not in trip_to_route:
                        continue

                    trip_info = trip_to_route[trip_id]
                    route_id = trip_info['route_id']
                    service_id = trip_info['service_id']

                    # Determine day type from service_id (e.g., "4_I12" → "I12" → "weekday")
                    day_type = 'weekday'  # default
                    for svc_code, dtype in SERVICE_TO_DAY_TYPE.items():
                        if svc_code in service_id:
                            day_type = dtype
                            break

                    # Parse times
                    start_time = self._parse_time(row['start_time'])
                    end_time = self._parse_time(row['end_time'])
                    headway_secs = int(row['headway_secs'])

                    if start_time is None or end_time is None:
                        continue

                    # Create key for deduplication
                    key = (route_id, day_type, start_time, end_time)

                    # Keep the lowest headway (most frequent service)
                    if key not in freq_map or headway_secs < freq_map[key]['headway_secs']:
                        freq_map[key] = {
                            'route_id': route_id,
                            'day_type': day_type,
                            'start_time': start_time,
                            'end_time': end_time,
                            'headway_secs': headway_secs,
                        }

        return list(freq_map.values())

    def _parse_time(self, time_str: str) -> Optional[time]:
        """Parse GTFS time string (may be >24:00 for overnight service)."""
        try:
            parts = time_str.split(':')
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2]) if len(parts) > 2 else 0

            # Handle times >= 24:00 (overnight service)
            # Normalize to 0-23 range
            hours = hours % 24

            return time(hours, minutes, seconds)
        except (ValueError, IndexError):
            return None
