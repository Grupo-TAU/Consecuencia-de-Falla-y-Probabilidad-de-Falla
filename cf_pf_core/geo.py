"""Utilidades geoespaciales compartidas por los calculos del core."""


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
