"""
Puente entre QGIS y cf_pf_core.

El plugin ya no implementa ningun calculo: traduce entre el mundo de QGIS
(QgsVectorLayer, feedback, parametros) y el del core (GeoDataFrames, funciones
puras) y deja que cf_pf_core haga el trabajo. Toda la logica vive en una sola
copia, compartida con la app Streamlit y los scripts run_*.

El core se resuelve en dos escenarios:
  - plugin instalado en QGIS: cf_pf_core viene vendorizado adentro del plugin
    (lo copia scripts/deploy_plugin.py).
  - repo de desarrollo: cf_pf_core esta un nivel mas arriba, junto al plugin.
"""
import os
import sys


def asegurar_core():
    """Deja cf_pf_core importable. Idempotente."""
    try:
        import cf_pf_core  # noqa: F401
        return
    except ImportError:
        pass

    aqui = os.path.dirname(os.path.abspath(__file__))
    for candidato in (aqui, os.path.dirname(aqui)):
        if os.path.isdir(os.path.join(candidato, "cf_pf_core")):
            if candidato not in sys.path:
                sys.path.insert(0, candidato)
            return
    raise ImportError(
        "No se encontro 'cf_pf_core'. Si estas usando el plugin instalado, "
        "reinstalalo con scripts/deploy_plugin.py para que copie el core adentro."
    )


asegurar_core()


def _verificar_dependencias():
    """Falla con un mensaje entendible si al Python de QGIS le falta geopandas.

    Todo el core es geopandas puro. Las instalaciones recientes de QGIS lo traen,
    pero las viejas no, y ahi el plugin instala bien y despues revienta con un
    ImportError que no dice que hacer. Mejor decirlo de una.
    """
    faltan = []
    for modulo in ("geopandas", "shapely", "pandas"):
        try:
            __import__(modulo)
        except ImportError:
            faltan.append(modulo)
    if faltan:
        raise ImportError(
            "Al Python de QGIS le falta: " + ", ".join(faltan) + ". "
            "Este plugin los necesita. Instalalos desde el instalador de OSGeo4W "
            "(paquete python3-geopandas) o actualiza QGIS a una version que los "
            "incluya."
        )


_verificar_dependencias()

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
from shapely import wkb as _wkb  # noqa: E402

from qgis.core import QgsProcessingContext, QgsProcessingException  # noqa: E402

from cf_pf_core import gpkg_io  # noqa: E402


# ── Log ──────────────────────────────────────────────────────────────────────

def log_de(feedback):
    """Adapta el feedback de QGIS al callback log(msg, nivel) que espera el core."""
    def _log(msg, nivel="info"):
        if feedback is None:
            return
        if nivel == "error":
            feedback.reportError(msg)
        elif nivel == "warn":
            feedback.pushWarning(msg)
        else:
            feedback.pushInfo(msg)
    return _log


# ── Lectura: capa de QGIS -> GeoDataFrame ────────────────────────────────────

def _a_python(valor):
    """Valor de atributo de QGIS a tipo Python (los NULL de QGIS no son None)."""
    if valor is None:
        return None
    try:
        from qgis.core import QgsVariantUtils
        if QgsVariantUtils.isNull(valor):
            return None
    except (ImportError, AttributeError):
        from qgis.core import NULL
        if valor == NULL:
            return None
    return valor


def _crs_de(fuente):
    crs = fuente.sourceCrs() if hasattr(fuente, "sourceCrs") else fuente.crs()
    if crs is None or not crs.isValid():
        return None
    # authid ('EPSG:32721') es lo que mejor entiende pyproj; el WKT cubre los
    # CRS custom, que no tienen codigo EPSG.
    return crs.authid() or crs.toWkt()


def capa_a_gdf(fuente, feedback=None):
    """QgsVectorLayer o QgsFeatureSource -> GeoDataFrame listo para el core."""
    if fuente is None:
        return None
    nombres = [f.name() for f in fuente.fields()]
    filas, geometrias = [], []
    for feat in fuente.getFeatures():
        filas.append([_a_python(v) for v in feat.attributes()])
        geom = feat.geometry()
        if geom is None or geom.isEmpty() or geom.isNull():
            geometrias.append(None)
        else:
            geometrias.append(_wkb.loads(bytes(geom.asWkb())))

    df = pd.DataFrame(filas, columns=nombres)
    gdf = gpd.GeoDataFrame(df, geometry=geometrias, crs=_crs_de(fuente))
    if feedback is not None:
        feedback.pushInfo(f"  {len(gdf)} entidades leidas (CRS {gdf.crs}).")
    return gdf


def ruta_y_capa(layer):
    """Ruta del .gpkg y nombre de capa de un QgsVectorLayer basado en archivo.

    Lo usan los pasos de preparacion, que editan el GeoPackage directamente en
    vez de pasar por GeoDataFrames.
    """
    if layer is None:
        raise QgsProcessingException("No se pudo leer la capa.")
    uri = layer.source()
    ruta, _sep, resto = uri.partition("|")
    capa = None
    for parte in resto.split("|"):
        if parte.startswith("layername="):
            capa = parte.split("=", 1)[1]
    if not ruta.lower().endswith(".gpkg"):
        raise QgsProcessingException(
            f"'{layer.name()}' no es una capa de GeoPackage ({ruta}). "
            "Los pasos de preparacion editan el .gpkg directamente."
        )
    return ruta, capa


# ── Escritura: resultados -> capa DatosConsecuenciaDeFalla ───────────────────

def salida_por_defecto(colectores_layer):
    """<carpeta de colectores>/<nombre>_ConsecuenciaDeFalla.gpkg"""
    try:
        ruta, _capa = ruta_y_capa(colectores_layer)
    except QgsProcessingException:
        return ""
    base = os.path.splitext(os.path.basename(ruta))[0]
    return os.path.join(os.path.dirname(ruta), f"{base}_ConsecuenciaDeFalla.gpkg")


def leer_base(destino, capa_salida):
    """Resultados de corridas anteriores, o None si todavia no hay."""
    if destino and gpkg_io.capa_existe(destino, capa_salida):
        return gpkg_io.leer_capa(destino, capa_salida)
    return None


def escribir_salida(res_gdf, destino, capa_salida, clave, context=None, feedback=None,
                    reemplazar=False):
    """Escribe los resultados y programa la carga de la capa en el proyecto."""
    gpkg_io.escribir_resultados(res_gdf, destino, capa_salida, clave=clave,
                                reemplazar=reemplazar)
    if feedback is not None:
        feedback.pushInfo(f"Resultados en {destino} (capa {capa_salida}).")

    if context is not None:
        uri = f"{destino}|layername={capa_salida}"
        detalles = QgsProcessingContext.LayerDetails(
            capa_salida, context.project(), capa_salida)
        context.addLayerToLoadOnCompletion(uri, detalles)
    return destino
