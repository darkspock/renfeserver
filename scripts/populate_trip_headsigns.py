#!/usr/bin/env python3
"""Populate trip headsigns from the last stop of each trip.

Since Renfe's GTFS data doesn't include headsigns, we calculate them
by finding the last stop (highest stop_sequence) for each trip.

Usage:
    python scripts/populate_trip_headsigns.py
"""

import sys
import logging
from sqlalchemy import text
from core.database import SessionLocal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BATCH_SIZE = 5000


def populate_headsigns():
    """Calculate and populate headsigns for all trips."""
    db = SessionLocal()

    try:
        # Count trips without headsign
        count_result = db.execute(text("""
            SELECT COUNT(*) FROM gtfs_trips
            WHERE headsign IS NULL OR headsign = '' OR headsign = 'CIVIS'
        """)).scalar()

        logger.info(f"Found {count_result} trips without proper headsign")

        if count_result == 0:
            logger.info("All trips already have headsigns")
            return

        # Update headsigns using the last stop name for each trip
        # This query finds the stop with the highest stop_sequence for each trip
        logger.info("Calculating headsigns from last stop of each trip...")

        result = db.execute(text("""
            UPDATE gtfs_trips t
            SET headsign = s.name
            FROM (
                SELECT DISTINCT ON (st.trip_id)
                    st.trip_id,
                    stops.name
                FROM gtfs_stop_times st
                JOIN gtfs_stops stops ON st.stop_id = stops.id
                ORDER BY st.trip_id, st.stop_sequence DESC
            ) s
            WHERE t.id = s.trip_id
            AND (t.headsign IS NULL OR t.headsign = '' OR t.headsign = 'CIVIS')
        """))

        db.commit()

        updated_count = result.rowcount
        logger.info(f"Updated {updated_count} trips with calculated headsigns")

        # Show some examples
        examples = db.execute(text("""
            SELECT id, headsign, route_id
            FROM gtfs_trips
            WHERE headsign IS NOT NULL AND headsign != ''
            LIMIT 10
        """)).fetchall()

        logger.info("Example headsigns:")
        for trip in examples:
            logger.info(f"  {trip[0]}: {trip[1]} (route: {trip[2]})")

    except Exception as e:
        logger.error(f"Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    populate_headsigns()
