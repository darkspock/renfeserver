"""Service for importing Metro Madrid data from CRTM Feature Service."""

import logging
from typing import Dict, List, Optional, Tuple
import requests
from sqlalchemy.orm import Session

from src.gtfs_bc.agency.infrastructure.models import AgencyModel
from src.gtfs_bc.stop.infrastructure.models import StopModel
from src.gtfs_bc.route.infrastructure.models import RouteModel
from src.gtfs_bc.stop_route_sequence.infrastructure.models import StopRouteSequenceModel

logger = logging.getLogger(__name__)


# Metro line colors from CRTM
METRO_COLORS = {
    '1': '2DBEF0',
    '2': 'ED1C24',
    '3': 'FFD000',
    '4': 'B65518',
    '5': '8FD400',
    '6': '98989B',
    '7': 'EE7518',
    '8': 'EC82B1',
    '9': 'A60084',
    '10': '005AA9',
    '11': '009B3A',
    '12': 'A49800',
    'R': '005AA9',
}

METRO_TEXT_COLORS = {
    '1': 'FFFFFF',
    '2': 'FFFFFF',
    '3': '000000',
    '4': 'FFFFFF',
    '5': 'FFFFFF',
    '6': 'FFFFFF',
    '7': 'FFFFFF',
    '8': 'FFFFFF',
    '9': 'FFFFFF',
    '10': 'FFFFFF',
    '11': 'FFFFFF',
    '12': 'FFFFFF',
    'R': 'FFFFFF',
}

METRO_LONG_NAMES = {
    '1': 'Pinar de Chamartín - Valdecarros',
    '2': 'Las Rosas - Cuatro Caminos',
    '3': 'Moncloa - El Casar',
    '4': 'Argüelles - Pinar de Chamartín',
    '5': 'Alameda de Osuna - Casa de Campo',
    '6': 'Circular',
    '7': 'Hospital del Henares - Pitis',
    '8': 'Nuevos Ministerios - Aeropuerto T4',
    '9': 'Paco de Lucía - Arganda del Rey',
    '10': 'Hospital Infanta Sofía - Puerta del Sur',
    '11': 'Plaza Elíptica - La Fortuna',
    '12': 'MetroSur (Circular)',
    'R': 'Ópera - Príncipe Pío',
}

# Metro Ligero colors
ML_COLORS = {
    'ML1': '3A7DDA',
    'ML2': 'A60084',
    'ML3': 'ED1C24',
    'ML4': '7DB713',
}

ML_LONG_NAMES = {
    'ML1': 'Pinar de Chamartín - Las Tablas',
    'ML2': 'Colonia Jardín - Estación de Aravaca',
    'ML3': 'Colonia Jardín - Puerta de Boadilla',
    'ML4': 'Tranvía de Parla (Circular)',
}


class CRTMMetroImporter:
    """Import Metro Madrid and Metro Ligero data from CRTM Feature Service."""

    # CRTM Feature Service endpoints
    METRO_STATIONS_URL = "https://services5.arcgis.com/UxADft6QPcvFyDU1/arcgis/rest/services/M4_Red/FeatureServer/0/query"
    METRO_TRAMOS_URL = "https://services5.arcgis.com/UxADft6QPcvFyDU1/arcgis/rest/services/M4_Red/FeatureServer/4/query"

    ML_STATIONS_URL = "https://services5.arcgis.com/UxADft6QPcvFyDU1/arcgis/rest/services/M10_Red/FeatureServer/0/query"
    ML_TRAMOS_URL = "https://services5.arcgis.com/UxADft6QPcvFyDU1/arcgis/rest/services/M10_Red/FeatureServer/4/query"

    # Madrid nucleo
    MADRID_NUCLEO_ID = 10
    MADRID_NUCLEO_NAME = "Madrid"

    def __init__(self, db: Session):
        self.db = db

    def _create_agencies(self) -> int:
        """Create Metro Madrid and Metro Ligero agencies."""
        created = 0

        agencies = [
            {
                'id': 'METRO_MADRID',
                'name': 'Metro de Madrid',
                'url': 'https://www.metromadrid.es',
                'timezone': 'Europe/Madrid',
                'lang': 'es',
            },
            {
                'id': 'METRO_LIGERO',
                'name': 'Metro Ligero de Madrid',
                'url': 'https://www.crtm.es',
                'timezone': 'Europe/Madrid',
                'lang': 'es',
            },
        ]

        for agency_data in agencies:
            existing = self.db.query(AgencyModel).filter(
                AgencyModel.id == agency_data['id']
            ).first()

            if not existing:
                agency = AgencyModel(**agency_data)
                self.db.add(agency)
                created += 1

        self.db.flush()
        logger.info(f"Created {created} agencies")
        return created

    def import_all(self) -> Dict[str, int]:
        """Import both Metro Madrid and Metro Ligero.

        Returns:
            Dictionary with import statistics
        """
        stats = {
            'agencies_created': 0,
            'metro_stops_created': 0,
            'metro_routes_created': 0,
            'metro_sequences_created': 0,
            'ml_stops_created': 0,
            'ml_routes_created': 0,
            'ml_sequences_created': 0,
        }

        try:
            # Create agencies first
            logger.info("Creating agencies...")
            stats['agencies_created'] = self._create_agencies()

            # Import Metro Madrid
            logger.info("Importing Metro Madrid...")
            metro_stats = self._import_metro()
            stats['metro_stops_created'] = metro_stats['stops_created']
            stats['metro_routes_created'] = metro_stats['routes_created']
            stats['metro_sequences_created'] = metro_stats['sequences_created']

            # Import Metro Ligero
            logger.info("Importing Metro Ligero...")
            ml_stats = self._import_metro_ligero()
            stats['ml_stops_created'] = ml_stats['stops_created']
            stats['ml_routes_created'] = ml_stats['routes_created']
            stats['ml_sequences_created'] = ml_stats['sequences_created']

            self.db.commit()
            logger.info("Successfully imported all Metro data")

        except Exception as e:
            logger.error(f"Error during Metro import: {e}")
            self.db.rollback()
            raise

        return stats

    def _import_metro(self) -> Dict[str, int]:
        """Import Metro Madrid data."""
        stats = {'stops_created': 0, 'routes_created': 0, 'sequences_created': 0}

        # Fetch stations
        stations = self._fetch_feature_service(
            self.METRO_STATIONS_URL,
            "DENOMINACION,LINEAS,X,Y,CODIGOESTACION,GRADOACCESIBILIDAD"
        )

        # Fetch tramos (for stop sequences)
        tramos = self._fetch_feature_service(
            self.METRO_TRAMOS_URL,
            "DENOMINACION,NUMEROLINEAUSUARIO,SENTIDO,NUMEROORDEN"
        )

        if not stations:
            logger.warning("No Metro stations fetched")
            return stats

        # Create routes first
        stats['routes_created'] = self._create_metro_routes()

        # Create stops
        stats['stops_created'] = self._create_metro_stops(stations)

        # Create sequences from tramos
        if tramos:
            stats['sequences_created'] = self._create_metro_sequences(tramos)

        return stats

    def _import_metro_ligero(self) -> Dict[str, int]:
        """Import Metro Ligero data."""
        stats = {'stops_created': 0, 'routes_created': 0, 'sequences_created': 0}

        # Fetch stations
        stations = self._fetch_feature_service(
            self.ML_STATIONS_URL,
            "DENOMINACION,LINEAS,X,Y,CODIGOESTACION"
        )

        # Fetch tramos
        tramos = self._fetch_feature_service(
            self.ML_TRAMOS_URL,
            "DENOMINACION,NUMEROLINEAUSUARIO,SENTIDO,NUMEROORDEN"
        )

        if not stations:
            logger.warning("No Metro Ligero stations fetched")
            return stats

        # Create routes
        stats['routes_created'] = self._create_ml_routes()

        # Create stops
        stats['stops_created'] = self._create_ml_stops(stations)

        # Create sequences
        if tramos:
            stats['sequences_created'] = self._create_ml_sequences(tramos)

        return stats

    def _fetch_feature_service(self, base_url: str, out_fields: str) -> List[Dict]:
        """Fetch all features from a CRTM Feature Service layer."""
        features = []
        offset = 0
        batch_size = 1000

        while True:
            params = {
                'where': '1=1',
                'outFields': out_fields,
                'resultOffset': offset,
                'resultRecordCount': batch_size,
                'f': 'json',
                'outSR': '4326',  # Request WGS84 coordinates
            }

            try:
                response = requests.get(base_url, params=params, timeout=60)
                response.raise_for_status()
                data = response.json()

                batch_features = data.get('features', [])
                if not batch_features:
                    break

                features.extend(batch_features)
                offset += batch_size

                if len(batch_features) < batch_size:
                    break

            except Exception as e:
                logger.error(f"Error fetching from {base_url}: {e}")
                break

        logger.info(f"Fetched {len(features)} features from {base_url}")
        return features

    def _create_metro_routes(self) -> int:
        """Create Metro Madrid routes."""
        created = 0

        for line_num in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', 'R']:
            route_id = f"METRO_{line_num}"

            existing = self.db.query(RouteModel).filter(RouteModel.id == route_id).first()
            if existing:
                continue

            route = RouteModel(
                id=route_id,
                agency_id="METRO_MADRID",
                short_name=line_num,
                long_name=METRO_LONG_NAMES.get(line_num, f"Línea {line_num}"),
                route_type=1,  # Metro/Subway
                color=METRO_COLORS.get(line_num),
                text_color=METRO_TEXT_COLORS.get(line_num, 'FFFFFF'),
                nucleo_id=self.MADRID_NUCLEO_ID,
                nucleo_name=self.MADRID_NUCLEO_NAME,
            )
            self.db.add(route)
            created += 1

        logger.info(f"Created {created} Metro routes")
        return created

    def _create_ml_routes(self) -> int:
        """Create Metro Ligero routes."""
        created = 0

        for line_num in ['ML1', 'ML2', 'ML3', 'ML4']:
            route_id = f"ML_{line_num}"

            existing = self.db.query(RouteModel).filter(RouteModel.id == route_id).first()
            if existing:
                continue

            route = RouteModel(
                id=route_id,
                agency_id="METRO_LIGERO",
                short_name=line_num,
                long_name=ML_LONG_NAMES.get(line_num, f"Línea {line_num}"),
                route_type=0,  # Tram/Light Rail
                color=ML_COLORS.get(line_num),
                text_color='FFFFFF',
                nucleo_id=self.MADRID_NUCLEO_ID,
                nucleo_name=self.MADRID_NUCLEO_NAME,
            )
            self.db.add(route)
            created += 1

        logger.info(f"Created {created} Metro Ligero routes")
        return created

    def _create_metro_stops(self, features: List[Dict]) -> int:
        """Create Metro Madrid stops from Feature Service data."""
        created = 0
        seen_stops = set()

        for feature in features:
            attrs = feature.get('attributes', {})
            geom = feature.get('geometry', {})

            name = attrs.get('DENOMINACION') or ''
            name = name.strip() if name else ''
            codigo = attrs.get('CODIGOESTACION') or ''
            lineas = attrs.get('LINEAS') or ''
            accesibilidad = attrs.get('GRADOACCESIBILIDAD')

            # Get coordinates (already in WGS84 due to outSR=4326)
            lon = geom.get('x') if geom else None
            lat = geom.get('y') if geom else None

            if not name or not lon or not lat:
                continue

            # Create unique stop ID
            stop_id = f"METRO_{codigo}" if codigo else f"METRO_{name.upper().replace(' ', '_')}"

            if stop_id in seen_stops:
                continue
            seen_stops.add(stop_id)

            # Check if stop already exists
            existing = self.db.query(StopModel).filter(StopModel.id == stop_id).first()
            if existing:
                continue

            # Determine wheelchair accessibility
            wheelchair = 1 if accesibilidad and 'accesible' in str(accesibilidad).lower() else 0

            stop = StopModel(
                id=stop_id,
                name=name.title(),
                lat=lat,
                lon=lon,
                code=codigo,
                location_type=0,  # Stop
                wheelchair_boarding=wheelchair,
                lineas=lineas,
                nucleo_id=self.MADRID_NUCLEO_ID,
                nucleo_name=self.MADRID_NUCLEO_NAME,
            )
            self.db.add(stop)
            created += 1

        logger.info(f"Created {created} Metro stops")
        return created

    def _create_ml_stops(self, features: List[Dict]) -> int:
        """Create Metro Ligero stops from Feature Service data."""
        created = 0
        seen_stops = set()

        for feature in features:
            attrs = feature.get('attributes', {})
            geom = feature.get('geometry', {})

            name = attrs.get('DENOMINACION') or ''
            name = name.strip() if name else ''
            codigo = attrs.get('CODIGOESTACION') or ''
            lineas = attrs.get('LINEAS') or ''

            lon = geom.get('x') if geom else None
            lat = geom.get('y') if geom else None

            if not name or not lon or not lat:
                continue

            stop_id = f"ML_{codigo}" if codigo else f"ML_{name.upper().replace(' ', '_')}"

            if stop_id in seen_stops:
                continue
            seen_stops.add(stop_id)

            existing = self.db.query(StopModel).filter(StopModel.id == stop_id).first()
            if existing:
                continue

            stop = StopModel(
                id=stop_id,
                name=name.title(),
                lat=lat,
                lon=lon,
                code=codigo,
                location_type=0,
                lineas=lineas,
                nucleo_id=self.MADRID_NUCLEO_ID,
                nucleo_name=self.MADRID_NUCLEO_NAME,
            )
            self.db.add(stop)
            created += 1

        logger.info(f"Created {created} Metro Ligero stops")
        return created

    def _create_metro_sequences(self, tramos: List[Dict]) -> int:
        """Create stop sequences for Metro routes from tramos data."""
        created = 0

        # Group tramos by line and direction, then order by NUMEROORDEN
        line_stops = {}  # {line_num: [(stop_name, order), ...]}

        for tramo in tramos:
            attrs = tramo.get('attributes', {})
            line = (attrs.get('NUMEROLINEAUSUARIO') or '').strip()
            stop_name = (attrs.get('DENOMINACION') or '').strip()
            sentido = attrs.get('SENTIDO')
            orden = attrs.get('NUMEROORDEN') or 0

            if not line or not stop_name:
                continue

            # Normalize line number (remove a/b variants for now)
            base_line = line.rstrip('ab').rstrip('AB').replace('-1', '').replace('-2', '')

            # Use sentido 1 for main direction (or 2 if 1 not available)
            key = (base_line, sentido)
            if key not in line_stops:
                line_stops[key] = []

            line_stops[key].append((stop_name, orden))

        # For each line, create sequences
        for (line_num, sentido), stops in line_stops.items():
            # Sort by order
            stops.sort(key=lambda x: x[1])

            route_id = f"METRO_{line_num}"
            route = self.db.query(RouteModel).filter(RouteModel.id == route_id).first()
            if not route:
                continue

            seen_stops = set()
            sequence = 0

            for stop_name, _ in stops:
                if stop_name in seen_stops:
                    continue
                seen_stops.add(stop_name)

                # Find matching stop
                stop = self.db.query(StopModel).filter(
                    StopModel.name.ilike(stop_name),
                    StopModel.id.like('METRO_%')
                ).first()

                if not stop:
                    # Try partial match
                    stop = self.db.query(StopModel).filter(
                        StopModel.name.ilike(f'%{stop_name}%'),
                        StopModel.id.like('METRO_%')
                    ).first()

                if not stop:
                    continue

                # Check if sequence already exists
                existing = self.db.query(StopRouteSequenceModel).filter(
                    StopRouteSequenceModel.stop_id == stop.id,
                    StopRouteSequenceModel.route_id == route_id
                ).first()

                if not existing:
                    seq = StopRouteSequenceModel(
                        stop_id=stop.id,
                        route_id=route_id,
                        sequence=sequence
                    )
                    self.db.add(seq)
                    created += 1

                sequence += 1

        logger.info(f"Created {created} Metro stop sequences")
        return created

    def _create_ml_sequences(self, tramos: List[Dict]) -> int:
        """Create stop sequences for Metro Ligero routes."""
        created = 0

        line_stops = {}

        for tramo in tramos:
            attrs = tramo.get('attributes', {})
            line = (attrs.get('NUMEROLINEAUSUARIO') or '').strip()
            stop_name = (attrs.get('DENOMINACION') or '').strip()
            sentido = attrs.get('SENTIDO')
            orden = attrs.get('NUMEROORDEN') or 0

            if not line or not stop_name:
                continue

            key = (line, sentido)
            if key not in line_stops:
                line_stops[key] = []

            line_stops[key].append((stop_name, orden))

        for (line_num, sentido), stops in line_stops.items():
            stops.sort(key=lambda x: x[1])

            route_id = f"ML_{line_num}"
            route = self.db.query(RouteModel).filter(RouteModel.id == route_id).first()
            if not route:
                continue

            seen_stops = set()
            sequence = 0

            for stop_name, _ in stops:
                if stop_name in seen_stops:
                    continue
                seen_stops.add(stop_name)

                stop = self.db.query(StopModel).filter(
                    StopModel.name.ilike(stop_name),
                    StopModel.id.like('ML_%')
                ).first()

                if not stop:
                    continue

                existing = self.db.query(StopRouteSequenceModel).filter(
                    StopRouteSequenceModel.stop_id == stop.id,
                    StopRouteSequenceModel.route_id == route_id
                ).first()

                if not existing:
                    seq = StopRouteSequenceModel(
                        stop_id=stop.id,
                        route_id=route_id,
                        sequence=sequence
                    )
                    self.db.add(seq)
                    created += 1

                sequence += 1

        logger.info(f"Created {created} Metro Ligero stop sequences")
        return created
