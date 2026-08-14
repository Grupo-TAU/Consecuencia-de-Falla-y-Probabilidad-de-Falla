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
import numpy as np
import pandas as pd
import shapely
from shapely.strtree import STRtree

from cf_pf_core.geo import alinear_crs, trocear_todas

RANGOS_SITIOS_DEFAULT = "50=6; 100=5; 200=4; 400=3; 800=2"
CAMPO_SITIOS_DEFAULT = "CF_Prox_SitiosInteres"

RANGOS_MEDIOAMBIENTAL_DEFAULT = "25=6; 50=5; 100=4; 200=3; 400=2"
CAMPO_MEDIOAMBIENTAL_DEFAULT = "CF_Prox_MedioAmbiental"

# Distancia al objetivo mas cercano, en las unidades del CRS de los colectores.
# Es el numero que origino la clase; se guarda para poder mostrarlo.
CAMPO_DIST_SITIOS_DEFAULT = "Dist_Prox_SitiosInteres"
CAMPO_DIST_MEDIOAMBIENTAL_DEFAULT = "Dist_Prox_MedioAmbiental"


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


def clase_de_distancia(distancia, rangos):
    """Clase que le corresponde a una distancia. Mas alla del ultimo rango -> 1.

    El corte es <= porque la version por buffers usaba intersects(), y un
    colector que roza el borde del buffer cuenta como dentro.
    """
    if distancia is None or distancia != distancia:  # None / NaN
        return 1
    for limite, clase in rangos:  # ascendente
        if distancia <= limite:
            return clase
    return 1


def calcular_detalle(colectores_gdf, objetivos_gdf, rango):
    """Devuelve (clase, distancia) como dos Series indexadas como colectores_gdf.

    La distancia es al objetivo MAS CERCANO, en las unidades del CRS de los
    colectores. Donde no hay objetivos o la geometria esta vacia: distancia NaN
    y clase 1.

    Sustituye a la version por buffers crecientes, que recorria los objetivos en
    orden y congelaba la clase con el PRIMERO que alcanzaba al colector (habia un
    `if fid in clasificacion: continue`). Eso hacia que el resultado dependiera
    del orden de las filas de la capa de objetivos: un objetivo lejano listado
    antes le ganaba a uno cercano listado despues. Tomar el minimo no depende del
    orden, y de paso da la distancia real para mostrar.
    """
    rangos = parse_rangos(rango)
    if not rangos:
        raise ValueError(f"Rangos invalidos: {rango!r}")

    # Alinear CRS de los objetivos al de los colectores (p.ej. KML 4326 -> 32721).
    objetivos_gdf = alinear_crs(objetivos_gdf, colectores_gdf.crs)

    # Geometrias de objetivos (no vacias), troceando las enormes: el STRtree
    # indexa por bounding box, y un solo poligono gigante (el Rio de la Plata)
    # obliga a medir contra el desde cada tramo. Ver geo.subdividir.
    obj_geoms = trocear_todas(
        [g for g in objetivos_gdf.geometry if g is not None and not g.is_empty])

    # Geometrias de colectores no vacias + mapeo posicion -> indice del gdf.
    col_geoms, col_index = [], []
    for idx, g in colectores_gdf.geometry.items():
        if g is not None and not g.is_empty:
            col_geoms.append(g)
            col_index.append(idx)

    distancias = {}
    if obj_geoms and col_geoms:
        tree = STRtree(obj_geoms)
        # nearest() resuelve todos los colectores de una; devuelve, por cada uno,
        # la posicion del objetivo mas cercano del arbol.
        cercanos = tree.nearest(col_geoms)
        # La distancia tambien va vectorizada: con 100k+ tramos contra poligonos
        # de muchos vertices, hacerlo en un bucle de Python domina el tiempo.
        col_arr = np.asarray(col_geoms, dtype=object)
        obj_arr = np.asarray(obj_geoms, dtype=object)[cercanos]
        distancias = dict(zip(col_index, shapely.distance(col_arr, obj_arr)))

    dist = pd.Series(
        [distancias.get(idx, float("nan")) for idx in colectores_gdf.index],
        index=colectores_gdf.index, dtype="float64",
    )
    clase = pd.Series(
        [clase_de_distancia(d, rangos) for d in dist],
        index=colectores_gdf.index, dtype="int64",
    )
    return clase, dist


def calcular(colectores_gdf, objetivos_gdf, rango):
    """Solo la clase de proximidad. Sin objetivo dentro de rango -> 1.

    colectores_gdf : GeoDataFrame de colectores (lineas).
    objetivos_gdf  : GeoDataFrame de objetivos (poligonos/lineas/puntos).
    rango          : str tipo '50=6; 100=5; ...' (distancia=clase).
    """
    clase, _ = calcular_detalle(colectores_gdf, objetivos_gdf, rango)
    return clase
