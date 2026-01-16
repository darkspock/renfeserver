"""Service for importing Renfe GeoJSON data and populating nucleo information."""

import logging
from typing import Dict, List, Optional, Tuple
import requests
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.gtfs_bc.nucleo.infrastructure.models import NucleoModel
from src.gtfs_bc.stop.infrastructure.models import StopModel
from src.gtfs_bc.route.infrastructure.models import RouteModel
from src.gtfs_bc.stop_route_sequence.infrastructure.models import StopRouteSequenceModel

logger = logging.getLogger(__name__)


class RenfeGeoJSONImporter:
    """Import núcleo data from Renfe's official GeoJSON sources."""

    ESTACIONES_URL = "https://tiempo-real.renfe.com/data/estaciones.geojson"
    LINEAS_URL = "https://tiempo-real.renfe.com/data/lineasnucleos.geojson"

    def __init__(self, db: Session):
        """Initialize importer with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db

    def import_nucleos(self) -> Dict[str, int]:
        """Import all nucleos, stations, and line geometries.

        Returns:
            Dictionary with import statistics:
            - nucleos_created: Number of nucleos imported
            - nucleos_updated: Number of nucleos updated
            - stops_updated: Number of stops updated
            - routes_updated: Number of routes updated
            - stops_not_matched: Number of stops without match
            - routes_not_matched: Number of routes without match
        """
        stats = {
            'nucleos_created': 0,
            'nucleos_updated': 0,
            'stops_updated': 0,
            'stops_created': 0,
            'routes_updated': 0,
            'routes_created': 0,
        }

        try:
            # Download GeoJSON files
            logger.info("Downloading Renfe GeoJSON files...")
            estaciones_data = self._download_geojson(self.ESTACIONES_URL)
            lineas_data = self._download_geojson(self.LINEAS_URL)

            if not estaciones_data or not lineas_data:
                logger.error("Failed to download GeoJSON files")
                return stats

            # Extract and import nucleos
            logger.info("Extracting nucleos from estaciones data...")
            nucleos = self._extract_nucleos(estaciones_data)
            created, updated = self._import_nucleos_table(nucleos)
            stats['nucleos_created'] = created
            stats['nucleos_updated'] = updated
            logger.info(f"Nucleos: {created} created, {updated} updated")

            # Update stops with nucleo data
            logger.info("Updating stops with nucleo data...")
            stops_updated, stops_created = self._update_stops_with_nucleo(estaciones_data)
            stats['stops_updated'] = stops_updated
            stats['stops_created'] = stops_created
            logger.info(f"Stops: {stops_updated} updated, {stops_created} created")

            # Update routes with nucleo data and geometry
            logger.info("Updating routes with nucleo data and geometry...")
            routes_updated, routes_created = self._update_routes_with_nucleo(lineas_data)
            stats['routes_updated'] = routes_updated
            stats['routes_created'] = routes_created
            logger.info(f"Routes: {routes_updated} updated, {routes_created} created")

            # Populate stop route sequences based on geometry
            logger.info("Calculating stop positions in routes...")
            sequences_created = self._populate_stop_route_sequences(estaciones_data, lineas_data)
            stats['sequences_created'] = sequences_created
            logger.info(f"Stop sequences: {sequences_created} created")

            self.db.commit()
            logger.info("Successfully imported all Renfe data")

        except Exception as e:
            logger.error(f"Error during import: {e}")
            self.db.rollback()
            raise

        return stats

    def _download_geojson(self, url: str) -> Optional[Dict]:
        """Download GeoJSON file from URL.

        Args:
            url: URL to download from

        Returns:
            Parsed GeoJSON data or None if download fails
        """
        try:
            logger.debug(f"Downloading {url}...")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to download {url}: {e}")
            return None
        except ValueError as e:
            logger.error(f"Failed to parse JSON from {url}: {e}")
            return None

    def _extract_nucleos(self, estaciones_data: Dict) -> List[Dict]:
        """Extract unique nucleos from estaciones GeoJSON.

        Args:
            estaciones_data: Parsed estaciones.geojson data

        Returns:
            List of nucleos with geographic boundaries
        """
        nucleos_dict = {}
        features = estaciones_data.get('features', [])

        for feature in features:
            properties = feature.get('properties', {})
            nucleo_id = properties.get('NUCLEO')
            nucleo_name = properties.get('NOMBRE_NUCLEO')
            lat = properties.get('LATITUD')
            lon = properties.get('LONGITUD')
            color = properties.get('COLOR')

            if not nucleo_id or not nucleo_name:
                continue

            if nucleo_id not in nucleos_dict:
                nucleos_dict[nucleo_id] = {
                    'id': nucleo_id,
                    'name': nucleo_name,
                    'color': color,
                    'lats': [],
                    'lons': [],
                }

            # Collect coordinates for bounding box calculation
            if lat is not None and lon is not None:
                nucleos_dict[nucleo_id]['lats'].append(lat)
                nucleos_dict[nucleo_id]['lons'].append(lon)

        # Calculate bounding boxes and center points
        nucleos = []
        for nucleo_id, data in nucleos_dict.items():
            if data['lats'] and data['lons']:
                data['bounding_box_min_lat'] = min(data['lats'])
                data['bounding_box_max_lat'] = max(data['lats'])
                data['bounding_box_min_lon'] = min(data['lons'])
                data['bounding_box_max_lon'] = max(data['lons'])
                data['center_lat'] = sum(data['lats']) / len(data['lats'])
                data['center_lon'] = sum(data['lons']) / len(data['lons'])

                # Remove temporary coordinate lists
                del data['lats']
                del data['lons']
                nucleos.append(data)

        logger.info(f"Extracted {len(nucleos)} unique nucleos")
        return nucleos

    def _import_nucleos_table(self, nucleos: List[Dict]) -> Tuple[int, int]:
        """Import nucleos into gtfs_nucleos table.

        Args:
            nucleos: List of nucleos to import

        Returns:
            Tuple of (created_count, updated_count)
        """
        created = 0
        updated = 0

        for nucleo_data in nucleos:
            try:
                nucleo = self.db.query(NucleoModel).filter(
                    NucleoModel.id == nucleo_data['id']
                ).first()

                if nucleo:
                    # Update existing nucleo
                    nucleo.name = nucleo_data['name']
                    nucleo.color = nucleo_data.get('color')
                    nucleo.bounding_box_min_lat = nucleo_data.get('bounding_box_min_lat')
                    nucleo.bounding_box_max_lat = nucleo_data.get('bounding_box_max_lat')
                    nucleo.bounding_box_min_lon = nucleo_data.get('bounding_box_min_lon')
                    nucleo.bounding_box_max_lon = nucleo_data.get('bounding_box_max_lon')
                    nucleo.center_lat = nucleo_data.get('center_lat')
                    nucleo.center_lon = nucleo_data.get('center_lon')
                    updated += 1
                else:
                    # Create new nucleo
                    nucleo = NucleoModel(
                        id=nucleo_data['id'],
                        name=nucleo_data['name'],
                        color=nucleo_data.get('color'),
                        bounding_box_min_lat=nucleo_data.get('bounding_box_min_lat'),
                        bounding_box_max_lat=nucleo_data.get('bounding_box_max_lat'),
                        bounding_box_min_lon=nucleo_data.get('bounding_box_min_lon'),
                        bounding_box_max_lon=nucleo_data.get('bounding_box_max_lon'),
                        center_lat=nucleo_data.get('center_lat'),
                        center_lon=nucleo_data.get('center_lon'),
                    )
                    self.db.add(nucleo)
                    created += 1

            except Exception as e:
                logger.error(f"Error importing nucleo {nucleo_data.get('id')}: {e}")

        return created, updated

    def _update_stops_with_nucleo(self, estaciones_data: Dict) -> Tuple[int, int]:
        """Update GTFS stops with Renfe nucleo and metadata.

        If no matching GTFS stop exists, creates new stop from Renfe data.

        Args:
            estaciones_data: Parsed estaciones.geojson data

        Returns:
            Tuple of (updated_count, created_count)
        """
        updated = 0
        created = 0
        features = estaciones_data.get('features', [])

        for feature in features:
            properties = feature.get('properties', {})
            renfe_name = properties.get('NOMBRE_ESTACION', '').strip()
            lat = properties.get('LATITUD')
            lon = properties.get('LONGITUD')
            nucleo_id = properties.get('NUCLEO')
            nucleo_name = properties.get('NOMBRE_NUCLEO')
            codigo_estacion = properties.get('CODIGO_ESTACION')
            color = properties.get('COLOR')
            lineas = properties.get('LINEAS')  # Lines serving this stop
            parking_bicis = properties.get('PARKING_BICIS')
            accesibilidad = properties.get('ACCESIBILIDAD')
            cor_bus = properties.get('COR_BUS')
            cor_metro = properties.get('COR_METRO')

            if not codigo_estacion or not lat or not lon:
                logger.debug(f"Skipping station with missing data: {renfe_name}")
                continue

            # Try to match GTFS stop to Renfe station
            gtfs_stop = self._find_matching_gtfs_stop(renfe_name, lat, lon)

            if gtfs_stop:
                # Update existing stop with Renfe data
                gtfs_stop.nucleo_id = nucleo_id
                gtfs_stop.nucleo_name = nucleo_name
                gtfs_stop.renfe_codigo_estacion = codigo_estacion
                gtfs_stop.color = color
                gtfs_stop.lineas = lineas  # Store lines serving this stop
                gtfs_stop.parking_bicis = parking_bicis
                gtfs_stop.accesibilidad = accesibilidad
                gtfs_stop.cor_bus = cor_bus
                gtfs_stop.cor_metro = cor_metro
                updated += 1
            else:
                # No matching GTFS stop, create new one from Renfe data
                new_stop = StopModel(
                    id=f"RENFE_{codigo_estacion}",
                    name=renfe_name,
                    lat=lat,
                    lon=lon,
                    nucleo_id=nucleo_id,
                    nucleo_name=nucleo_name,
                    renfe_codigo_estacion=codigo_estacion,
                    color=color,
                    lineas=lineas,  # Store lines serving this stop
                    parking_bicis=parking_bicis,
                    accesibilidad=accesibilidad,
                    cor_bus=cor_bus,
                    cor_metro=cor_metro,
                    location_type=0,  # 0 = stop, 1 = station
                )
                self.db.add(new_stop)
                created += 1
                logger.debug(f"Created new stop from Renfe station: {renfe_name}")

        return updated, created

    def _update_routes_with_nucleo(self, lineas_data: Dict) -> Tuple[int, int]:
        """Update GTFS routes with Renfe nucleo and geometry.

        If no matching GTFS route exists, creates new route from Renfe data.

        Args:
            lineas_data: Parsed lineasnucleos.geojson data

        Returns:
            Tuple of (updated_count, created_count)
        """
        updated = 0
        created = 0
        features = lineas_data.get('features', [])

        for feature in features:
            properties = feature.get('properties', {})
            codigo = properties.get('CODIGO', '').strip()
            nucleo_id = properties.get('IDNUCLEO')
            nucleo_name = properties.get('NUCLEO')
            nombre = properties.get('NOMBRE', codigo).strip()
            idlinea = properties.get('IDLINEA')
            color = properties.get('COLOR')  # Hex color from Renfe (e.g., "#EF7100")
            geometry = feature.get('geometry', {})

            if not codigo:
                continue

            # Try to match GTFS route to Renfe line using IDLINEA for precision
            gtfs_route = self._find_matching_gtfs_route_by_idlinea(codigo, idlinea)

            if gtfs_route:
                # Update existing route with Renfe data and geometry
                gtfs_route.nucleo_id = nucleo_id
                gtfs_route.nucleo_name = nucleo_name
                gtfs_route.renfe_idlinea = idlinea
                gtfs_route.color = color  # Set color from Renfe

                # Store geometry as WKT LineString if available
                if geometry.get('type') == 'LineString':
                    coordinates = geometry.get('coordinates', [])
                    if coordinates:
                        # Create WKT representation: LINESTRING (lon lat, lon lat, ...)
                        wkt_coords = ','.join([f'{lon} {lat}' for lon, lat in coordinates])
                        wkt = f'LINESTRING({wkt_coords})'
                        gtfs_route.geometry = wkt
                        logger.debug(f"Set geometry for route {codigo}")

                updated += 1
            else:
                # No matching GTFS route, create new one from Renfe data
                new_route = RouteModel(
                    id=f"RENFE_{codigo}_{idlinea}",  # Unique ID combining Renfe code and line ID
                    agency_id="1071VC",  # Renfe Cercanias
                    short_name=codigo,
                    long_name=nombre,
                    route_type=2,  # Rail
                    color=color,  # Set color from Renfe
                    nucleo_id=nucleo_id,
                    nucleo_name=nucleo_name,
                    renfe_idlinea=idlinea,
                )

                # Store geometry as WKT LineString if available
                if geometry.get('type') == 'LineString':
                    coordinates = geometry.get('coordinates', [])
                    if coordinates:
                        # Create WKT representation: LINESTRING (lon lat, lon lat, ...)
                        wkt_coords = ','.join([f'{lon} {lat}' for lon, lat in coordinates])
                        wkt = f'LINESTRING({wkt_coords})'
                        new_route.geometry = wkt

                self.db.add(new_route)
                created += 1
                logger.debug(f"Created new route from Renfe line: {codigo}")

        return updated, created

    def _find_matching_gtfs_stop(
        self,
        renfe_name: str,
        renfe_lat: Optional[float],
        renfe_lon: Optional[float],
        max_distance: float = 0.001  # ~100m at equator
    ) -> Optional[StopModel]:
        """Find matching GTFS stop for Renfe station.

        Uses multiple strategies:
        1. Exact name match (case-insensitive, normalized)
        2. Coordinate proximity
        3. Fuzzy name match

        Args:
            renfe_name: Name from Renfe GeoJSON
            renfe_lat: Latitude from Renfe
            renfe_lon: Longitude from Renfe
            max_distance: Maximum distance threshold in degrees

        Returns:
            Matching StopModel or None
        """
        # Strategy 1: Exact name match (normalized)
        normalized_renfe = renfe_name.lower().strip()
        stop = self.db.query(StopModel).filter(
            StopModel.name.ilike(f'%{renfe_name}%'),
            StopModel.location_type != 1  # Not a station parent
        ).first()

        if stop:
            return stop

        # Strategy 2: Coordinate proximity (if coordinates available)
        if renfe_lat is not None and renfe_lon is not None:
            stop = self.db.query(StopModel).filter(
                StopModel.lat.between(renfe_lat - max_distance, renfe_lat + max_distance),
                StopModel.lon.between(renfe_lon - max_distance, renfe_lon + max_distance),
                StopModel.location_type != 1
            ).first()

            if stop:
                return stop

        return None

    def _find_matching_gtfs_route_by_idlinea(self, renfe_codigo: str, idlinea: Optional[int]) -> Optional[RouteModel]:
        """Find matching GTFS route for Renfe line using IDLINEA for precision.

        First tries to find by exact ID (RENFE_{CODIGO}_{IDLINEA}),
        then falls back to regular matching by code.

        Args:
            renfe_codigo: Code from Renfe GeoJSON (e.g., "C1", "R17")
            idlinea: IDLINEA from Renfe GeoJSON for precise matching

        Returns:
            Matching RouteModel or None
        """
        # Strategy 0: Exact ID match using RENFE_{CODIGO}_{IDLINEA} format
        if idlinea:
            exact_id = f"RENFE_{renfe_codigo}_{idlinea}"
            route = self.db.query(RouteModel).filter(
                RouteModel.id == exact_id
            ).first()
            if route:
                return route

        # Fall back to regular code matching
        return self._find_matching_gtfs_route(renfe_codigo)

    def _find_matching_gtfs_route(self, renfe_codigo: str) -> Optional[RouteModel]:
        """Find matching GTFS route for Renfe line.

        Uses strategies:
        1. Exact code match (short_name)
        2. Case-insensitive match
        3. Handle variants (C4a, C4A)

        Args:
            renfe_codigo: Code from Renfe GeoJSON (e.g., "C1", "R17")

        Returns:
            Matching RouteModel or None
        """
        # Strategy 1: Exact match
        route = self.db.query(RouteModel).filter(
            RouteModel.short_name == renfe_codigo
        ).first()

        if route:
            return route

        # Strategy 2: Case-insensitive match
        route = self.db.query(RouteModel).filter(
            RouteModel.short_name.ilike(renfe_codigo)
        ).first()

        if route:
            return route

        # Strategy 3: Handle variants by checking base name
        # If looking for "C1", also match "C1A", "C1B", etc.
        normalized = renfe_codigo.lower()
        routes = self.db.query(RouteModel).filter(
            RouteModel.short_name.ilike(f'{normalized}%')
        ).all()

        if routes:
            # Return first match (prefer exact over variants)
            return routes[0]

        return None

    def _populate_stop_route_sequences(
        self,
        estaciones_data: Dict,
        lineas_data: Dict
    ) -> int:
        """Calculate and store the sequence (position) of each stop in each route.

        For each route's LineString geometry, find the closest point on the line
        for each stop that serves that route, and store that index as the sequence.

        Args:
            estaciones_data: Parsed estaciones.geojson data
            lineas_data: Parsed lineasnucleos.geojson data

        Returns:
            Number of sequences created
        """
        from math import sqrt

        sequences_created = 0
        lineas_features = lineas_data.get('features', [])
        sequences_to_add = {}  # Deduplicator: (stop_id, route_id) -> sequence

        # For each route (line) in the GeoJSON
        for line_feature in lineas_features:
            line_props = line_feature.get('properties', {})
            codigo = line_props.get('CODIGO', '').strip()
            idlinea = line_props.get('IDLINEA')
            line_geometry = line_feature.get('geometry', {})

            if not codigo or line_geometry.get('type') != 'LineString':
                continue

            # Get coordinates from the LineString
            line_coords = line_geometry.get('coordinates', [])
            if not line_coords:
                continue

            # Find the matching GTFS route using IDLINEA for precision
            gtfs_route = self._find_matching_gtfs_route_by_idlinea(codigo, idlinea)
            if not gtfs_route:
                continue

            # Get all stops for this route
            estaciones_features = estaciones_data.get('features', [])

            for station_feature in estaciones_features:
                station_props = station_feature.get('properties', {})
                lineas_str = station_props.get('LINEAS', '')
                station_name = station_props.get('NOMBRE_ESTACION', '')

                # Check if this station has this line
                lineas_list = [x.strip() for x in lineas_str.split(',') if x.strip()]
                if codigo not in lineas_list:
                    continue

                # Get station coordinates
                station_geom = station_feature.get('geometry', {})
                if station_geom.get('type') != 'Point':
                    continue

                station_coords = station_geom.get('coordinates')  # [lon, lat]
                if not station_coords:
                    continue

                # Find the closest point on the line to this station
                min_distance = float('inf')
                closest_index = -1

                for i, line_coord in enumerate(line_coords):
                    # Calculate Euclidean distance
                    distance = sqrt(
                        (station_coords[0] - line_coord[0]) ** 2 +
                        (station_coords[1] - line_coord[1]) ** 2
                    )
                    if distance < min_distance:
                        min_distance = distance
                        closest_index = i

                if closest_index >= 0:
                    # Find or create the stop in GTFS
                    gtfs_stop = self._find_matching_gtfs_stop(
                        station_name,
                        station_coords[1],  # lat
                        station_coords[0]   # lon
                    )

                    if gtfs_stop:
                        # Only assign stops from the same nucleo as the route
                        if gtfs_stop.nucleo_id == gtfs_route.nucleo_id:

                            # Verify that the stop actually has this line
                            if gtfs_stop.lineas:
                                stop_lineas_list = [x.strip() for x in gtfs_stop.lineas.split(',') if x.strip()]
                                if codigo not in stop_lineas_list:
                                    logger.debug(f"Skipping {gtfs_stop.name}: has lineas={gtfs_stop.lineas}, looking for {codigo}")
                                    continue

                            # Deduplicate: keep only first occurrence for each stop/route pair
                            key = (gtfs_stop.id, gtfs_route.id)
                            if key not in sequences_to_add:
                                sequences_to_add[key] = closest_index

        # Add all sequences, checking for existing ones in database
        for (stop_id, route_id), sequence in sequences_to_add.items():
            existing = self.db.query(StopRouteSequenceModel).filter(
                StopRouteSequenceModel.stop_id == stop_id,
                StopRouteSequenceModel.route_id == route_id
            ).first()

            if not existing:
                seq = StopRouteSequenceModel(
                    stop_id=stop_id,
                    route_id=route_id,
                    sequence=sequence
                )
                self.db.add(seq)
                sequences_created += 1

        return sequences_created
