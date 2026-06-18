"""
CF Ubicacion de la Tuberia - standalone sin QGIS.
Requiere: pip install shapely

Clasifica cada colector segun el tipo de via sobre la que esta ubicado.
Usa el punto medio del colector + buffer para buscar vias intersectantes.

DOS PASADAS:
  1ra: radio 5m — todos los colectores.
  2da: radio 10m — solo los sin via en la 1ra.
Sin via en ninguna pasada → clase 1.

Mapeo por defecto (TIPO → clase):
  Sin pavimentar:1; Local menor:2; Local mayor:3;
  Centrica:4; Via colectora/Edificaciones:5; Arteria/Canal:6

Uso:
    python scripts\\run_cf_ubicacion.py \\
        --gpkg-col <ruta> --gpkg-vias <ruta> --campo-tipo TIPO
"""
import argparse, sqlite3, sys, os

try:
    from shapely import wkb as shapely_wkb
    from shapely.strtree import STRtree
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

CAMPO_CLASIFICACION_DEFAULT = "CF_Ubicacion"
CAMPO_TIPO_DEFAULT          = "TIPO"
BUFFER_1_DEFAULT            = 5.0
BUFFER_2_DEFAULT            = 10.0
TIPO_MAPPING_DEFAULT = (
    "Sin pavimentar:1; Local menor:2; Local mayor:3; "
    "Centrica:4; Via colectora/Edificaciones:5; Arteria/Canal:6"
)


def _detectar_capa(con, layer_name, etiqueta="capa"):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print(f"ERROR: Sin capas en {etiqueta}."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no existe. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1: return capas[0]
    print(f"Varias capas en {etiqueta}: {capas}."); sys.exit(1)


def _columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _campo(cols, *nombres):
    lower = {c.lower(): c for c in cols}
    for n in nombres:
        if n.lower() in lower: return lower[n.lower()]
    return None


def _geom_col(con, tabla):
    rows = con.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (tabla,)
    ).fetchall()
    return rows[0][0] if rows else "geom"


def _wkb_offset(blob):
    if blob is None or len(blob) < 8: return -1
    if bytes(blob[:2]) != b'GP': return -1
    flags = blob[3]
    env_type = (flags & 0x0E) >> 1
    env_sizes = [0, 32, 48, 48, 64]
    return 8 + (env_sizes[env_type] if env_type <= 4 else 0)


def _blob_to_geom(blob):
    offset = _wkb_offset(blob)
    if offset < 0: return None
    try:
        return shapely_wkb.loads(bytes(blob[offset:]))
    except Exception:
        return None


def _parse_mapping(texto):
    mapping = []
    for par in str(texto).split(";"):
        par = par.strip()
        if ":" not in par: continue
        key, _, val = par.partition(":")
        key = key.strip().lower()
        if not key: continue
        try: mapping.append((key, int(val.strip())))
        except ValueError: continue
    return mapping


def _clasificar_tipo(tipo_raw, mapping):
    if tipo_raw is None: return 1
    try:
        val = int(str(tipo_raw).strip())
        if 1 <= val <= 6: return val
    except (ValueError, TypeError): pass
    norm = str(tipo_raw).strip().lower()
    for key, cls in mapping:
        if norm == key: return cls
    best_len, best_cls = 0, 1
    for key, cls in mapping:
        if key in norm and len(key) > best_len:
            best_len, best_cls = len(key), cls
    return best_cls if best_len > 0 else 1


def _clase_en_punto_medio(geom_col, buf_dist, tree_vias, via_geoms, attr_tipo, mapping):
    """Retorna (clase_max, es_valido)."""
    try:
        longitud = geom_col.length
        if longitud <= 0: return 0, False
        pt_medio = geom_col.interpolate(longitud / 2.0)
        if pt_medio is None or pt_medio.is_empty: return 0, False
        buf = pt_medio.buffer(buf_dist)
        clase_max = 0
        for idx in tree_vias.query(buf):
            if via_geoms[idx].intersects(buf):
                cls = _clasificar_tipo(attr_tipo.get(idx), mapping)
                if cls > clase_max: clase_max = cls
        return clase_max, True
    except Exception:
        return 0, False


def run(gpkg_col, gpkg_vias,
        layer_col=None, layer_vias=None,
        campo_cf=CAMPO_CLASIFICACION_DEFAULT,
        campo_tipo=CAMPO_TIPO_DEFAULT,
        buffer_1=BUFFER_1_DEFAULT,
        buffer_2=BUFFER_2_DEFAULT,
        mapping_str=TIPO_MAPPING_DEFAULT):

    if not HAS_SHAPELY:
        print("ERROR: shapely no encontrado. Instala con: pip install shapely"); sys.exit(1)

    gpkg_col  = os.path.normpath(gpkg_col)
    if gpkg_vias is None: gpkg_vias = gpkg_col
    gpkg_vias = os.path.normpath(gpkg_vias)
    for path in (gpkg_col, gpkg_vias):
        if not os.path.isfile(path): print(f"ERROR: No existe '{path}'"); sys.exit(1)

    mapping = _parse_mapping(mapping_str)
    print(f"Mapeo TIPO ({len(mapping)} entradas), buffer 1ra={buffer_1}m, 2da={buffer_2}m")

    # Cargar vias
    con_via = sqlite3.connect(gpkg_vias)
    tabla_via = _detectar_capa(con_via, layer_vias, "vias")
    cols_via  = _columnas(con_via, tabla_via)
    gc_via    = _geom_col(con_via, tabla_via)
    c_tipo    = _campo(cols_via, campo_tipo, "tipo", "TIPO")
    if not c_tipo:
        print(f"ERROR: Campo '{campo_tipo}' no encontrado en Vias. Disponibles: {cols_via}")
        con_via.close(); sys.exit(1)

    via_rows = con_via.execute(f'SELECT "{gc_via}", "{c_tipo}" FROM "{tabla_via}"').fetchall()
    con_via.close()

    via_geoms  = []
    attr_tipo  = {}
    for blob, tipo_val in via_rows:
        g = _blob_to_geom(blob)
        if g is not None and not g.is_empty:
            idx = len(via_geoms)
            via_geoms.append(g)
            attr_tipo[idx] = tipo_val
    tree_vias = STRtree(via_geoms)
    print(f"Vias indexadas: {len(via_geoms)}")

    # Cargar colectores
    con_col = sqlite3.connect(gpkg_col)
    con_col.execute("PRAGMA journal_mode=WAL")
    tabla_col = _detectar_capa(con_col, layer_col, "colectores")
    cols_col  = _columnas(con_col, tabla_col)
    gc_col    = _geom_col(con_col, tabla_col)

    if not _campo(cols_col, campo_cf):
        con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{campo_cf}" INTEGER')

    filas = con_col.execute(
        f'SELECT fid, "{gc_col}", "{campo_cf}" FROM "{tabla_col}"'
    ).fetchall()
    print(f"Colectores: {len(filas)}")

    clasificacion = {}  # fid -> clase
    pendientes    = []  # filas sin via en 1ra pasada

    print(f"1ra pasada ({buffer_1} m)...")
    for fid, blob, _ in filas:
        g = _blob_to_geom(blob)
        if g is None or g.is_empty: continue
        clase_max, valido = _clase_en_punto_medio(g, buffer_1, tree_vias, via_geoms, attr_tipo, mapping)
        if not valido: continue
        if clase_max > 0:
            clasificacion[fid] = clase_max
        else:
            pendientes.append((fid, g))

    print(f"  {len(filas) - len(pendientes)} colectores con via encontrada.")
    print(f"2da pasada ({buffer_2} m) — {len(pendientes)} colectores sin via...")
    resueltos = 0
    for fid, g in pendientes:
        clase_max, _ = _clase_en_punto_medio(g, buffer_2, tree_vias, via_geoms, attr_tipo, mapping)
        clasificacion[fid] = clase_max if clase_max > 0 else 1
        if clase_max > 0: resueltos += 1
    print(f"  {resueltos} resueltos en 2da pasada.")

    triggers = con_col.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_col,)
    ).fetchall()
    for name, _ in triggers: con_col.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for fid, _, cf_actual in filas:
        nueva = clasificacion.get(fid, 1)
        if cf_actual != nueva:
            con_col.execute(
                f'UPDATE "{tabla_col}" SET "{campo_cf}"=? WHERE fid=?', (nueva, fid)
            )
            actualizadas += 1

    for _, sql in triggers:
        if sql: con_col.execute(sql)
    con_col.commit(); con_col.close()
    print(f"OK. '{campo_cf}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="CF Ubicacion standalone")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--layer-col",  default=None)
    p.add_argument("--gpkg-vias",  default=None,
                   help="GeoPackage con Vias (default: mismo que --gpkg)")
    p.add_argument("--layer-vias", default=None)
    p.add_argument("--campo-cf",   default=CAMPO_CLASIFICACION_DEFAULT)
    p.add_argument("--campo-tipo", default=CAMPO_TIPO_DEFAULT,
                   help="Nombre del campo TIPO en la capa Vias")
    p.add_argument("--buffer-1",   default=BUFFER_1_DEFAULT, type=float,
                   help="Radio 1ra pasada en metros (default 5)")
    p.add_argument("--buffer-2",   default=BUFFER_2_DEFAULT, type=float,
                   help="Radio 2da pasada en metros (default 10)")
    p.add_argument("--mapping",    default=TIPO_MAPPING_DEFAULT,
                   help="Ej: 'Sin pavimentar:1; Local menor:2; ...'")
    a = p.parse_args()
    run(a.gpkg_col, a.gpkg_vias, a.layer_col, a.layer_vias,
        a.campo_cf, a.campo_tipo, a.buffer_1, a.buffer_2, a.mapping)

if __name__ == "__main__":
    main()
