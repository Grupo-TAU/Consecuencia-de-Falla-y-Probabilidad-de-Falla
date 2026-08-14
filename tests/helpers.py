"""Capas sinteticas compartidas por los tests.

Todo lo que se arma aca es en memoria o en un directorio temporal: los tests
nunca tocan G: ni las salidas reales del proyecto.
"""
import geopandas as gpd
from shapely.geometry import LineString, Point

from cf_pf_core.calculos import criticidad as C

CRS = "EPSG:32721"  # el que usa el proyecto (UTM 21S, metros)


def lineas(n, paso=100):
    """n tramos rectos, separados `paso` metros sobre el eje X."""
    return [LineString([(i * paso, 0), (i * paso, 10)]) for i in range(n)]


def colectores(n=3, clave="ELEMRED", **columnas):
    """Capa de Colectores con todos los CF en 3 y las columnas que se pidan.

    Los CF vienen precargados para que los pasos que los combinan (criticidad,
    riesgo) tengan de donde leer sin correr los diez calculos antes.
    """
    datos = {p: [3] * n for p in C.PARAMS_DISPONIBLES}
    datos[clave] = list(range(1, n + 1))
    datos.update(columnas)
    return gpd.GeoDataFrame(datos, geometry=lineas(n), crs=CRS)


def objetivos(distancias):
    """Capa de objetivos (cursos de agua, sitios) a las distancias dadas del
    primer colector, que esta en x=0."""
    return gpd.GeoDataFrame(
        {"i": list(range(len(distancias)))},
        geometry=[Point(d, 0) for d in distancias], crs=CRS)


def tabla(df, columna):
    """La columna como lista, para comparar sin arrastrar el indice."""
    return list(df[columna])
