"""
Utilidades de escritura in-place sobre GeoPackage para los pasos de preparacion.

A diferencia de cf_pf_core.calculos (funciones puras que nunca tocan la fuente),
los pasos de preparacion SI modifican las capas reales de Colectores y Registros:
completan campos que quedan vacios (registros asignados, cotas, pendiente).

Por eso se edita con UPDATE ... WHERE fid=? via sqlite3 en vez de reescribir la
capa con geopandas: se conservan fid, tipos de columna, indices y el resto de los
atributos exactamente como estaban.
"""
import os
import sqlite3
from contextlib import contextmanager

from shapely import wkb

# Bytes de envelope segun el indicador de la cabecera GeoPackage.
_TAM_ENVELOPE = (0, 32, 48, 48, 64)


class PreparacionError(Exception):
    """Error que impide continuar un paso de preparacion."""


def hacer_log(log):
    """Normaliza el callback de log: devuelve siempre algo invocable."""
    def _log(msg, nivel="info"):
        if log:
            log(msg, nivel)
    return _log


# ── Conexion y catalogo ──────────────────────────────────────────────────────

def conectar(path, escritura=False):
    if not path:
        raise PreparacionError("Falta indicar la ruta del GeoPackage.")
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        raise PreparacionError(f"No existe '{path}'")
    con = sqlite3.connect(path)
    if escritura:
        con.execute("PRAGMA journal_mode=WAL")
    return con


def misma_ruta(a, b):
    """True si dos rutas apuntan al mismo archivo (para reusar la conexion)."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def detectar_capa(con, layer=None, etiqueta="capa"):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas:
        raise PreparacionError(f"Sin capas de features en {etiqueta}.")
    if layer:
        if layer not in capas:
            raise PreparacionError(f"La capa '{layer}' no existe en {etiqueta}. Disponibles: {capas}")
        return layer
    if len(capas) == 1:
        return capas[0]
    raise PreparacionError(f"Hay varias capas en {etiqueta}: {capas}. Indica cual usar.")


def columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def buscar_campo(cols, *nombres):
    """Resuelve un nombre de columna case-insensitive entre varios candidatos."""
    lower = {c.lower(): c for c in cols}
    for n in nombres:
        if n and n.lower() in lower:
            return lower[n.lower()]
    return None


def columna_geometria(con, tabla):
    filas = con.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (tabla,)
    ).fetchall()
    return filas[0][0] if filas else "geom"


def asegurar_campo(con, tabla, cols, nombre, tipo="REAL", log=None):
    """Crea la columna si no existe. Devuelve el nombre real de la columna."""
    existente = buscar_campo(cols, nombre)
    if existente:
        return existente
    con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{nombre}" {tipo}')
    cols.append(nombre)
    hacer_log(log)(f"Se creo el campo '{nombre}' en {tabla}.")
    return nombre


@contextmanager
def sin_triggers(con, tabla):
    """Desactiva los triggers de la tabla durante el bloque y los restaura al salir.

    Los GeoPackage traen triggers de mantenimiento del indice rtree que encarecen
    mucho un UPDATE masivo; se recrean tal cual al terminar.
    """
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for nombre, _sql in triggers:
        con.execute(f'DROP TRIGGER IF EXISTS "{nombre}"')
    try:
        yield
    finally:
        for _nombre, sql in triggers:
            if sql:
                con.execute(sql)


# ── Geometria ────────────────────────────────────────────────────────────────

def geometria_de_blob(blob):
    """Geometria shapely a partir de un blob GeoPackage, o None si no se puede leer."""
    if blob is None or len(blob) < 8:
        return None
    b = bytes(blob)
    if b[:2] != b"GP":
        return None
    flags = b[3]
    if flags & 0x10:  # bit de geometria vacia
        return None
    indicador = (flags & 0x0E) >> 1
    if indicador >= len(_TAM_ENVELOPE):
        return None
    try:
        return wkb.loads(b[8 + _TAM_ENVELOPE[indicador]:])
    except Exception:  # noqa: BLE001 — blob corrupto: se trata como sin geometria
        return None


def extremos(geom):
    """(punto_inicial, punto_final) de una geometria lineal, o (None, None).

    Contempla MultiLineString (los scripts viejos solo leian LineString y dejaban
    esos colectores sin asignar).
    """
    if geom is None or geom.is_empty:
        return None, None
    if geom.geom_type == "LineString":
        coords = list(geom.coords)
    elif geom.geom_type == "MultiLineString":
        coords = [c for parte in geom.geoms if not parte.is_empty for c in parte.coords]
    else:
        return None, None
    if not coords:
        return None, None
    return coords[0][:2], coords[-1][:2]


# ── Conversiones de valores ──────────────────────────────────────────────────

def a_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def es_vacio(v):
    if v is None:
        return True
    return str(v).strip().upper() in ("", "NULL")


def normalizar(v):
    """Texto limpio de un identificador: '' si esta vacio o es NULL."""
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.upper() == "NULL" else s
