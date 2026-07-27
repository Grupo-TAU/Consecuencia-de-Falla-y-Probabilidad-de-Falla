"""
CF Proximidad — clasifica colectores por cercania a una capa de objetivos
(sitios de interes, cursos de agua, etc.) usando buffers crecientes.

Logica portada IDENTICA a scripts/run_cf_prox_sitios_interes.py y
run_cf_prox_cursos_agua.py (mismo algoritmo: por cada objetivo y cada radio en
orden ascendente, se asigna al colector el radio mas chico que lo intersecta;
sin interseccion -> clase 1). Se usa shapely STRtree + buffer + intersects, tal
cual el script, sobre las geometrias de geopandas.

Los dos casos concretos difieren solo en rangos y campo de salida:
  Sitios de interes : RANGOS_SITIOS_DEFAULT        -> CF_Prox_SitiosInteres
  Cursos de agua    : RANGOS_MEDIOAMBIENTAL_DEFAULT -> CF_Prox_MedioAmbiental
"""
import pandas as pd
from shapely.strtree import STRtree

from cf_pf_core.geo import alinear_crs

RANGOS_SITIOS_DEFAULT = "50=6; 100=5; 200=4; 400=3; 800=2"
CAMPO_SITIOS_DEFAULT = "CF_Prox_SitiosInteres"

RANGOS_MEDIOAMBIENTAL_DEFAULT = "25=6; 50=5; 100=4; 200=3; 400=2"
CAMPO_MEDIOAMBIENTAL_DEFAULT = "CF_Prox_MedioAmbiental"


def parse_rangos(texto):
    rangos = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        d, _, c = par.partition("=")
        try:
            rangos.append((float(d.strip()), int(c.strip())))
        except ValueError:
            continue
    return sorted(rangos, key=lambda x: x[0]) if rangos else []


def calcular(colectores_gdf, objetivos_gdf, rango):
    """Devuelve una Serie int (indexada como colectores_gdf) con la clase de
    proximidad. Sin interseccion -> 1.

    colectores_gdf : GeoDataFrame de colectores (lineas).
    objetivos_gdf  : GeoDataFrame de objetivos (poligonos/lineas/puntos).
    rango          : str tipo '50=6; 100=5; ...' (distancia=clase).
    """
    rangos = parse_rangos(rango)
    if not rangos:
        raise ValueError(f"Rangos invalidos: {rango!r}")

    # Alinear CRS de los objetivos al de los colectores (p.ej. KML 4326 -> 32721).
    objetivos_gdf = alinear_crs(objetivos_gdf, colectores_gdf.crs)

    # Geometrias de objetivos (no vacias).
    obj_geoms = [g for g in objetivos_gdf.geometry if g is not None and not g.is_empty]

    # Geometrias de colectores no vacias + mapeo posicion -> indice del gdf.
    col_geoms, col_index = [], []
    for idx, g in colectores_gdf.geometry.items():
        if g is not None and not g.is_empty:
            col_geoms.append(g)
            col_index.append(idx)

    clasificacion = {}
    if obj_geoms and col_geoms:
        tree = STRtree(col_geoms)
        for obj in obj_geoms:
            for dist, clase in rangos:  # ya ordenado ascendente
                buf = obj.buffer(dist)
                for pos in tree.query(buf):
                    fid = col_index[pos]
                    if fid in clasificacion:
                        continue
                    if col_geoms[pos].intersects(buf):
                        clasificacion[fid] = clase

    return pd.Series(
        [clasificacion.get(idx, 1) for idx in colectores_gdf.index],
        index=colectores_gdf.index,
        dtype="int64",
    )
