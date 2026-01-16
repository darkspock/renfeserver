# Corrección: Filtrado de Paradas en Secuencias de Rutas

## Problema Identificado

Actualmente, al calcular la secuencia de paradas para cada ruta, **se están asignando paradas que NO tienen la línea especificada**.

**Ejemplo**: La parada "Delicias" tiene solo "C10" en su campo `lineas`, pero está siendo asignada a la ruta C1 de Madrid.

### Causa Raíz

En el archivo `src/gtfs_bc/nucleo/infrastructure/services/renfe_geojson_importer.py`, en la función `_populate_stop_route_sequences()`, se está calculando la distancia de TODAS las paradas a la geometría de la línea, sin verificar primero que la parada tenga esa línea en su campo LINEAS.

## Solución

### Paso 1: Localizar el Código Problemático

**Archivo**: `src/gtfs_bc/nucleo/infrastructure/services/renfe_geojson_importer.py`

**Función**: `_populate_stop_route_sequences()` (línea ~510-585)

**Código actual problemático** (alrededor de línea 535-546):

```python
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
```

El código **aparentemente** está verificando que la estación tiene la línea, pero el problema es que se está iterando sobre TODAS las estaciones de `estaciones_data` para CADA línea.

### Paso 2: Aplicar el Filtro Correcto

El filtro `if codigo not in lineas_list: continue` **SÍ está presente**, pero necesitamos verificar que este está funcionando correctamente.

**Cambio a realizar** (línea ~544-546):

```python
# Check if this station has this line
lineas_list = [x.strip() for x in lineas_str.split(',') if x.strip()]
if codigo not in lineas_list:
    continue  # SKIP if this station doesn't serve this line
```

Este código **ya existe**, pero necesitamos asegurar que:

1. El `codigo` está siendo tratado correctamente (sin espacios, con case correcto)
2. El `lineas_str` está siendo parseado correctamente

**La verdadera corrección** debería ser agregar más logging/debugging para verificar qué está pasando. Pero primero, necesitamos verificar si el problema es en el import o en cómo se guardan los datos.

### Paso 3: Alternativa - Filtrado Estricto Adicional

Si el filtro existente no funciona, agrega este código adicional después de verificar que la estación tiene la línea:

**Ubicación**: Justo después de la línea que verifica `if codigo not in lineas_list`:

```python
# Check if this station has this line
lineas_list = [x.strip() for x in lineas_str.split(',') if x.strip()]
if codigo not in lineas_list:
    logger.debug(f"Skipping {station_name}: lineas={lineas_list}, codigo={codigo}")
    continue
```

Esto agregará logging para ver qué está pasando.

## Pasos de Corrección

### Opción A: Agregar Logging para Debugging (PRIMERO)

1. Abre el archivo: `src/gtfs_bc/nucleo/infrastructure/services/renfe_geojson_importer.py`

2. Busca la línea ~544-546 donde está:
```python
if codigo not in lineas_list:
    continue
```

3. Reemplázalo con:
```python
if codigo not in lineas_list:
    logger.debug(f"Skipping {station_name}: has lineas={lineas_list}, looking for {codigo}")
    continue
```

4. Sube el archivo a producción y ejecuta el import nuevamente:
```bash
scp -i ~/.ssh/id_ed25519_personal src/gtfs_bc/nucleo/infrastructure/services/renfe_geojson_importer.py root@juanmacias.com:/var/www/renfeserver/src/gtfs_bc/nucleo/infrastructure/services/
```

5. En el servidor, ejecuta:
```bash
cd /var/www/renfeserver
PGPASSWORD=renfeserver_prod_2026 psql -U renfeserver -h localhost renfeserver_prod -c "TRUNCATE TABLE gtfs_stop_route_sequence RESTART IDENTITY;"
PYTHONPATH=/var/www/renfeserver .venv/bin/python3 scripts/import_renfe_nucleos.py 2>&1 | grep -i "delicias\|skipping"
```

6. Revisa los logs para ver si "Delicias" está siendo skipped para C1.

### Opción B: Agregar Filtrado Explícito Adicional (SI OPCIÓN A FALLA)

Si Delicias NO aparece en los logs de "skipping", entonces el problema está en otro lugar.

En ese caso, agrega un filtrado adicional antes de calcular distancias:

**Ubicación**: Después de verificar que el stop existe (línea ~579):

```python
if gtfs_stop:
    # Only assign stops from the same nucleo as the route
    if gtfs_stop.nucleo_id == gtfs_route.nucleo_id:

        # NUEVO: Verificar que el stop realmente tiene esta línea
        if gtfs_stop.lineas:
            stop_lineas_list = [x.strip() for x in gtfs_stop.lineas.split(',') if x.strip()]
            if codigo not in stop_lineas_list:
                logger.debug(f"Skipping {gtfs_stop.name}: has lineas={gtfs_stop.lineas}, looking for {codigo}")
                continue

        # Deduplicate: keep only first occurrence for each stop/route pair
        key = (gtfs_stop.id, gtfs_route.id)
        if key not in sequences_to_add:
            sequences_to_add[key] = closest_index
```

## Validación

Después de aplicar la corrección, verifica:

```bash
# En el servidor:
ssh -i ~/.ssh/id_ed25519_personal root@juanmacias.com

cd /var/www/renfeserver

# Truncar y reimportar
PGPASSWORD=renfeserver_prod_2026 psql -U renfeserver -h localhost renfeserver_prod -c "TRUNCATE TABLE gtfs_stop_route_sequence RESTART IDENTITY;"

PYTHONPATH=/var/www/renfeserver .venv/bin/python3 scripts/import_renfe_nucleos.py

# Verificar que Delicias NO está en C1
PGPASSWORD=renfeserver_prod_2026 psql -U renfeserver -h localhost renfeserver_prod -c "
SELECT s.name, s.lineas
FROM gtfs_stops s
JOIN gtfs_stop_route_sequence srs ON s.id = srs.stop_id
WHERE srs.route_id = 'RENFE_C1_34' AND s.name = 'Delicias';
"

# Si Delicias aparece, el problema persiste
# Si NO aparece, el problema está solucionado
```

## Paso Final: Deployar

```bash
# Desde el ordenador de desarrollo:

# 1. Copiar archivo corregido
scp -i ~/.ssh/id_ed25519_personal src/gtfs_bc/nucleo/infrastructure/services/renfe_geojson_importer.py root@juanmacias.com:/var/www/renfeserver/src/gtfs_bc/nucleo/infrastructure/services/

# 2. En el servidor (via SSH):
ssh -i ~/.ssh/id_ed25519_personal root@juanmacias.com

cd /var/www/renfeserver

# 3. Truncar la tabla
PGPASSWORD=renfeserver_prod_2026 psql -U renfeserver -h localhost renfeserver_prod -c "TRUNCATE TABLE gtfs_stop_route_sequence RESTART IDENTITY;"

# 4. Ejecutar import
PYTHONPATH=/var/www/renfeserver .venv/bin/python3 scripts/import_renfe_nucleos.py

# 5. Reiniciar servicio
systemctl restart renfeserver

# 6. Verificar
systemctl status renfeserver
```

## Resumen

- **Problema**: Paradas sin la línea están siendo asignadas a las secuencias
- **Causa**: El filtrado `if codigo not in lineas_list` podría no estar funcionando correctamente
- **Solución**: Agregar logging/debugging y luego un filtrado adicional a nivel de StopModel
- **Validación**: Verificar que "Delicias" NO aparece en C1 Madrid después del fix
