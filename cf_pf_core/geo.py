"""Utilidades geoespaciales compartidas por los calculos del core."""
import shapely
from shapely.geometry import box

# Un poligono con mas vertices que esto se trocea antes de indexarlo.
MAX_VERTICES_DEFAULT = 256


def subdividir(geom, max_vertices=MAX_VERTICES_DEFAULT, _profundidad=0):
    """Parte una geometria en pedazos de a lo sumo `max_vertices` vertices.

    La union de los pedazos es la geometria original, asi que la distancia minima
    a los pedazos es EXACTAMENTE la distancia a la original: esto acelera sin
    cambiar un solo resultado.

    Hace falta porque un STRtree indexa por bounding box: un unico poligono
    enorme —el Rio de la Plata en la capa de espejos de agua tiene 89.653
    vertices y su bbox cubre todo Montevideo— obliga a calcular la distancia
    exacta contra el por cada tramo, y ahi se va todo el tiempo. Troceado, el
    indice descarta las piezas lejanas.
    """
    if geom is None or geom.is_empty:
        return []
    if shapely.get_num_coordinates(geom) <= max_vertices or _profundidad >= 20:
        return [geom]

    minx, miny, maxx, maxy = geom.bounds
    if maxx - minx >= maxy - miny:  # se parte por el lado mas largo
        medio = (minx + maxx) / 2
        cajas = (box(minx, miny, medio, maxy), box(medio, miny, maxx, maxy))
    else:
        medio = (miny + maxy) / 2
        cajas = (box(minx, miny, maxx, medio), box(minx, medio, maxx, maxy))

    salida = []
    for caja in cajas:
        try:
            parte = geom.intersection(caja)
        except Exception:  # noqa: BLE001  geometria invalida: mejor dejarla entera
            return [geom]
        if not parte.is_empty:
            salida.extend(subdividir(parte, max_vertices, _profundidad + 1))
    return salida or [geom]


def trocear_todas(geoms, max_vertices=MAX_VERTICES_DEFAULT):
    """subdividir() sobre una lista. Si ninguna geometria es grande, no cuesta nada."""
    if not any(shapely.get_num_coordinates(g) > max_vertices
               for g in geoms if g is not None):
        return list(geoms)
    salida = []
    for g in geoms:
        salida.extend(subdividir(g, max_vertices))
    return salida


def alinear_crs(gdf, crs_objetivo):
    """Reproyecta gdf al crs_objetivo si difieren.

    A diferencia de los scripts standalone (que no reproyectan y fallan silenciosamente
    cuando las capas auxiliares vienen en otro CRS, p.ej. EPSG:4326 de un KML frente a
    EPSG:32721 de los colectores), aca alineamos siempre antes de operar.
    """
    if gdf is None or gdf.crs is None or crs_objetivo is None:
        return gdf
    if gdf.crs != crs_objetivo:
        return gdf.to_crs(crs_objetivo)
    return gdf
