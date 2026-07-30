"""
CF Acceso Mantenimiento — clasifica colectores por accesibilidad.

Logica portada IDENTICA a scripts/run_cf_acceso_mantenimiento.py:
  Cada REGISTRO (punto) se clasifica por contencion en capas auxiliares, en orden
  de prioridad:
      6 = construcciones o asentamientos
      5 = padrones
      4 = espacios peatonales
      3 = espacios verdes
      2 = calles cuyo Tipo_Via es "dificil" (a <=1 m del punto)
      1 = resto
  El colector toma MIN(clase_registro_inicial, clase_registro_final); si solo hay
  uno, ese; si no hay ninguno, NULL.

Todas las capas auxiliares son opcionales (si falta una, se omite ese nivel).
"""
import pandas as pd
from shapely.strtree import STRtree

from cf_pf_core.geo import alinear_crs

CAMPO_SALIDA_DEFAULT = "CF_Acceso_Mantenimiento"
CAMPO_REG_INI_DEFAULT = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT = "Registro_Final"
CAMPO_ID_REG_DEFAULT = "ID"
CAMPO_TIPO_VIA_DEFAULT = "Tipo_Via"
BUFFER_CALLES_DEFAULT = 1.0
DESCRIPTORES_CLASE_2 = {"Local mayor", "Centrica", "Via colectora/Edificaciones", "Arteria/Canal"}


def _norm_id(v):
    """Normaliza un id a texto. Enteros leidos como float (por NULLs en la
    columna) se vuelven '123', no '123.0', para matchear como en el script (SQL)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _tree(gdf):
    """(STRtree, lista_geoms) desde un GeoDataFrame, o (None, []) si es None/vacio."""
    if gdf is None or len(gdf) == 0:
        return None, []
    geoms = [g for g in gdf.geometry if g is not None and not g.is_empty]
    if not geoms:
        return None, []
    return STRtree(geoms), geoms


def _point_in_any(pt, tree, geoms):
    if tree is None:
        return False
    for idx in tree.query(pt):
        if geoms[idx].contains(pt):
            return True
    return False


def _calles_tipos(pt, tree, geoms, tipos_por_pos, buf):
    if tree is None:
        return set()
    pt_buf = pt.buffer(buf)
    result = set()
    for idx in tree.query(pt_buf):
        if geoms[idx].intersects(pt_buf):
            val = tipos_por_pos.get(idx, "") or ""
            result.add(str(val).strip().lower())
    return result


def calcular(
    colectores_gdf,
    registros_gdf,
    construcciones=None,
    asentamientos=None,
    padrones=None,
    peatonales=None,
    verde=None,
    calles=None,
    campo_reg_ini=CAMPO_REG_INI_DEFAULT,
    campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
    campo_id_reg=CAMPO_ID_REG_DEFAULT,
    campo_tipo_via=CAMPO_TIPO_VIA_DEFAULT,
    descriptores_clase2=None,
    buffer_calles=BUFFER_CALLES_DEFAULT,
):
    """Devuelve una Serie (indexada como colectores_gdf) con CF_Acceso_Mantenimiento.
    Colectores sin registro clasificable quedan en NA."""
    descriptores = set(descriptores_clase2) if descriptores_clase2 else set(DESCRIPTORES_CLASE_2)

    def _col(gdf, *cands):
        lower = {c.lower(): c for c in gdf.columns}
        for n in cands:
            if n.lower() in lower:
                return lower[n.lower()]
        return None

    c_ini = _col(colectores_gdf, campo_reg_ini)
    c_fin = _col(colectores_gdf, campo_reg_fin, "Registro_FInal")
    if not c_ini:
        raise KeyError(f"'{campo_reg_ini}' no encontrado en Colectores.")
    if not c_fin:
        raise KeyError(f"'{campo_reg_fin}' no encontrado en Colectores.")
    c_id = _col(registros_gdf, campo_id_reg, "ID", "Id")
    if not c_id:
        raise KeyError(f"Campo ID no encontrado en Registros.")

    # Alinear CRS de todas las capas auxiliares al de los registros (p.ej. KML 4326).
    crs_ref = registros_gdf.crs
    construcciones = alinear_crs(construcciones, crs_ref)
    asentamientos = alinear_crs(asentamientos, crs_ref)
    padrones = alinear_crs(padrones, crs_ref)
    peatonales = alinear_crs(peatonales, crs_ref)
    verde = alinear_crs(verde, crs_ref)
    calles = alinear_crs(calles, crs_ref)

    tree_constr = _tree(construcciones)
    tree_asent = _tree(asentamientos)
    tree_pad = _tree(padrones)
    tree_peat = _tree(peatonales)
    tree_verde = _tree(verde)
    tree_calles, geoms_calles = _tree(calles)

    tipos_calles = {}
    if calles is not None and geoms_calles:
        c_tipo = _col(calles, campo_tipo_via)
        if c_tipo:
            pos = 0
            for g, val in zip(calles.geometry, calles[c_tipo]):
                if g is not None and not g.is_empty:
                    tipos_calles[pos] = val
                    pos += 1

    def _clasificar_punto(pt):
        if _point_in_any(pt, *tree_constr):
            return 6
        if _point_in_any(pt, *tree_asent):
            return 6
        if _point_in_any(pt, *tree_pad):
            return 5
        if _point_in_any(pt, *tree_peat):
            return 4
        if _point_in_any(pt, *tree_verde):
            return 3
        if tree_calles is not None:
            tipos = _calles_tipos(pt, tree_calles, geoms_calles, tipos_calles, buffer_calles)
            if tipos & descriptores:
                return 2
        return 1

    clase_por_id = {}
    for rid_val, g in zip(registros_gdf[c_id], registros_gdf.geometry):
        rid = _norm_id(rid_val)
        if not rid or g is None or g.is_empty:
            continue
        clase_por_id[rid] = _clasificar_punto(g)

    def _cf_colector(ini, fin):
        c_i = clase_por_id.get(_norm_id(ini))
        c_f = clase_por_id.get(_norm_id(fin))
        if c_i is not None and c_f is not None:
            return min(c_i, c_f)
        if c_i is not None:
            return c_i
        if c_f is not None:
            return c_f
        return None

    valores = [
        _cf_colector(ini, fin)
        for ini, fin in zip(colectores_gdf[c_ini], colectores_gdf[c_fin])
    ]
    return pd.Series(valores, index=colectores_gdf.index, dtype="Int64")
