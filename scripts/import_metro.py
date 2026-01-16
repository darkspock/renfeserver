#!/usr/bin/env python3
"""Script to import Metro Madrid and Metro Ligero data from CRTM Feature Service."""

import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.database import SessionLocal

# Import all models to ensure relationships are configured
from src.gtfs_bc.nucleo.infrastructure.models import NucleoModel
from src.gtfs_bc.stop.infrastructure.models import StopModel
from src.gtfs_bc.route.infrastructure.models import RouteModel
from src.gtfs_bc.stop_route_sequence.infrastructure.models import StopRouteSequenceModel

from src.gtfs_bc.metro.infrastructure.services import CRTMMetroImporter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Run the Metro import."""
    logger.info("Starting Metro Madrid import from CRTM Feature Service...")

    db = SessionLocal()
    try:
        importer = CRTMMetroImporter(db)
        stats = importer.import_all()

        logger.info("=" * 50)
        logger.info("IMPORT COMPLETE")
        logger.info("=" * 50)
        logger.info(f"Metro Madrid:")
        logger.info(f"  - Stops created: {stats['metro_stops_created']}")
        logger.info(f"  - Routes created: {stats['metro_routes_created']}")
        logger.info(f"  - Sequences created: {stats['metro_sequences_created']}")
        logger.info(f"Metro Ligero:")
        logger.info(f"  - Stops created: {stats['ml_stops_created']}")
        logger.info(f"  - Routes created: {stats['ml_routes_created']}")
        logger.info(f"  - Sequences created: {stats['ml_sequences_created']}")

    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
