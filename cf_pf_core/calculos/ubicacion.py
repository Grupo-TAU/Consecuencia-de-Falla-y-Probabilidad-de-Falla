"""
CF Ubicacion de la Tuberia — clasifica cada colector segun el tipo de via sobre
la que esta ubicado (punto medio del colector + buffer).

Logica portada IDENTICA a scripts/run_cf_ubicacion.py:
  - Dos pasadas: 1ra radio 5 m (todos), 2da radio 10 m (solo los sin via).
  - En el punto medio se toma la clase MAXIMA entre las vias intersectadas.
  - Sin via en ninguna pasada -> clase 1.
"""
import unicodedata

import pandas as pd
from shapely.strtree import STRtree

from cf_pf_core.geo import alinear_crs


def _strip(texto):
    """Minusculas sin acentos (para que 'Centrica' matchee 'Céntrica')."""
    s = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip().lower()

CAMPO_SALIDA_DEFAULT = "CF_Ubicacion"
CAMPO_TIPO_DEFAULT = "TIPO"
BUFFER_1_DEFAULT = 5.0
BUFFER_2_DEFAULT = 10.0
TIPO_MAPPING_DEFAULT = (
    "Sin pavimentar:1; Local menor:2; Local mayor:3; "
    "Centrica:4; Via colectora/Edificaciones:5; Arteria/Canal:6"
)


def parse_mapping(texto):
    mapping = []
    for par in str(texto).split(";"):
        par = par.strip()
        if ":" not in par:
            continue
        key, _, val = par.partition(":")
        key = _strip(key)
        if not key:
            continue
        try:
            mapping.append((key, int(val.strip())))
        except ValueError:
            continue
    return mapping


def _clasificar_tipo(tipo_raw, mapping):
    if tipo_raw is None or (isinstance(tipo_raw, float) and pd.isna(tipo_raw)):
        return 1
    try:
        val = int(str(tipo_raw).strip())
        if 1 <= val <= 6:
            return val
    except (ValueError, TypeError):
        pass
    norm = _strip(tipo_raw)
    for key, cls in mapping:
        if norm == key:
            return cls
    best_len, best_cls = 0, 1
    for key, cls in mapping:
        if key in norm and len(key) > best_len:
            best_len, best_cls = len(key), cls
    return best_cls if best_len > 0 else 1


def _clase_en_punto_medio(geom_col, buf_dist, tree_vias, via_geoms, attr_tipo, mapping):
    """Retorna (clase_max, es_valido)."""
    try:
        longitud = geom_col.length
        if longitud <= 0:
            return 0, False
        pt_medio = geom_col.interpolate(longitud / 2.0)
        if pt_medio is None or pt_medio.is_empty:
            return 0, False
        buf = pt_medio.buffer(buf_dist)
        clase_max = 0
        for pos in tree_vias.query(buf):
            if via_geoms[pos].intersects(buf):
                cls = _clasificar_tipo(attr_tipo.get(pos), mapping)
                if cls > clase_max:
                    clase_max = cls
        return clase_max, True
    except Exception:
        return 0, False


def calcular(
    colectores_gdf,
    vias_gdf,
    campo_tipo=CAMPO_TIPO_DEFAULT,
    buffer_1=BUFFER_1_DEFAULT,
    buffer_2=BUFFER_2_DEFAULT,
    mapping=TIPO_MAPPING_DEFAULT,
):
    """Devuelve una Serie int (indexada como colectores_gdf) con CF_Ubicacion."""
    c_tipo = None
    lower = {c.lower(): c for c in vias_gdf.columns}
    for cand in (campo_tipo, "tipo", "TIPO"):
        if cand.lower() in lower:
            c_tipo = lower[cand.lower()]
            break
    if not c_tipo:
        raise KeyError(
            f"Campo '{campo_tipo}' no encontrado en Vias. Columnas: {list(vias_gdf.columns)}"
        )

    mapping_parsed = parse_mapping(mapping)

    # Alinear CRS de vias al de colectores.
    vias_gdf = alinear_crs(vias_gdf, colectores_gdf.crs)

    via_geoms, attr_tipo = [], {}
    for _, row in vias_gdf.iterrows():
        g = row.geometry
        if g is not None and not g.is_empty:
            pos = len(via_geoms)
            via_geoms.append(g)
            attr_tipo[pos] = row[c_tipo]
    if not via_geoms:
        return pd.Series(1, index=colectores_gdf.index, dtype="int64")
    tree_vias = STRtree(via_geoms)

    clasificacion, pendientes = {}, []
    for idx, g in colectores_gdf.geometry.items():
        if g is None or g.is_empty:
            continue
        clase_max, valido = _clase_en_punto_medio(
            g, buffer_1, tree_vias, via_geoms, attr_tipo, mapping_parsed
        )
        if not valido:
            continue
        if clase_max > 0:
            clasificacion[idx] = clase_max
        else:
            pendientes.append((idx, g))

    for idx, g in pendientes:
        clase_max, _ = _clase_en_punto_medio(
            g, buffer_2, tree_vias, via_geoms, attr_tipo, mapping_parsed
        )
        clasificacion[idx] = clase_max if clase_max > 0 else 1

    return pd.Series(
        [clasificacion.get(idx, 1) for idx in colectores_gdf.index],
        index=colectores_gdf.index,
        dtype="int64",
    )
