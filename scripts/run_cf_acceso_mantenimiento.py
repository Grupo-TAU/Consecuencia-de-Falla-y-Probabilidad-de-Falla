"""
CF Acceso Mantenimiento - standalone sin QGIS.
Requiere: pip install shapely

Clasifica colectores por accesibilidad:
  6 = construcciones o asentamientos
  5 = padrones
  4 = espacios peatonales
  3 = espacios verdes
  2 = calles tipo dificil
  1 = resto

Asigna al colector el MIN(clase_ini, clase_fin) de sus registros.

Uso:
    python scripts\\run_cf_acceso_mantenimiento.py \\
        --gpkg-col <ruta> --layer-col <capa> \\
        --gpkg-reg <ruta> --layer-reg <capa> \\
        [--gpkg-constr <ruta>] [--layer-constr <capa>] \\
        [--gpkg-asent <ruta>]  [--layer-asent <capa>]  \\
        [--gpkg-pad <ruta>]    [--layer-pad <capa>]    \\
        [--gpkg-peat <ruta>]   [--layer-peat <capa>]   \\
        [--gpkg-verde <ruta>]  [--layer-verde <capa>]  \\
        [--gpkg-calles <ruta>] [--layer-calles <capa>] \\
        [--campo-tipo-via TIPO]
"""
import argparse, sqlite3, struct, sys, os

try:
    from shapely import wkb as shapely_wkb
    from shapely.strtree import STRtree
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

CAMPO_CF_ACCESO_DEFAULT   = "CF_Acceso_Mantenimiento"
CAMPO_REGISTRO_INICIAL    = "Registro_Inicial"
CAMPO_REGISTRO_FINAL      = "Registro_Final"
CAMPO_ID_REGISTRO         = "ID"
CAMPO_TIPO_VIA            = "Tipo_Via"
BUFFER_CALLES             = 1.0
DESCRIPTORES_CLASE_2      = {"local mayor", "autopista/canal", "arteria/edificaciones"}


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


def _load_layer(gpkg_path, layer_name, label, extra_field=None):
    """Carga geometrias de una capa. Retorna (geoms_list, extras_dict) o (None, None)."""
    if gpkg_path is None: return None, None
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path):
        print(f"  AVISO: No existe '{gpkg_path}' ({label}) — se omite."); return None, None
    con = sqlite3.connect(gpkg_path)
    tabla = _detectar_capa(con, layer_name, label)
    gc = _geom_col(con, tabla)
    cols = _columnas(con, tabla)
    if extra_field:
        c_extra = _campo(cols, extra_field)
        if not c_extra:
            print(f"  AVISO: Campo '{extra_field}' no encontrado en {label} — se omite capa.")
            con.close(); return None, None
        rows = con.execute(f'SELECT "{gc}", "{c_extra}" FROM "{tabla}"').fetchall()
        geoms = []
        extras = {}
        for i, (blob, val) in enumerate(rows):
            g = _blob_to_geom(blob)
            if g is not None:
                geoms.append(g)
                extras[len(geoms) - 1] = val
        con.close()
        print(f"  {label}: {len(geoms)} geometrias")
        return geoms, extras
    else:
        rows = con.execute(f'SELECT "{gc}" FROM "{tabla}"').fetchall()
        geoms = [g for blob, in rows if (g := _blob_to_geom(blob)) is not None]
        con.close()
        print(f"  {label}: {len(geoms)} geometrias")
        return geoms, None


def _build_tree(geoms):
    if not geoms: return None, []
    tree = STRtree(geoms)
    return tree, geoms


def _point_in_any(pt, tree, geoms):
    if tree is None: return False
    for idx in tree.query(pt):
        if geoms[idx].contains(pt): return True
    return False


def _calles_tipo(pt, tree, geoms, extras, buf, descriptores):
    if tree is None: return set()
    pt_buf = pt.buffer(buf)
    result = set()
    for idx in tree.query(pt_buf):
        if geoms[idx].intersects(pt_buf):
            val = extras.get(idx, "") or ""
            result.add(str(val).strip().lower())
    return result


def run(gpkg_col, layer_col=None,
        gpkg_reg=None, layer_reg=None,
        gpkg_constr=None, layer_constr=None,
        gpkg_asent=None, layer_asent=None,
        gpkg_pad=None, layer_pad=None,
        gpkg_peat=None, layer_peat=None,
        gpkg_verde=None, layer_verde=None,
        gpkg_calles=None, layer_calles=None,
        campo_cf=CAMPO_CF_ACCESO_DEFAULT,
        campo_reg_ini=CAMPO_REGISTRO_INICIAL,
        campo_reg_fin=CAMPO_REGISTRO_FINAL,
        campo_id_reg=CAMPO_ID_REGISTRO,
        campo_tipo_via=CAMPO_TIPO_VIA,
        descriptores_str=None,
        buffer_calles=BUFFER_CALLES):

    if not HAS_SHAPELY:
        print("ERROR: shapely no encontrado. Instala con: pip install shapely"); sys.exit(1)

    gpkg_col = os.path.normpath(gpkg_col)
    if not os.path.isfile(gpkg_col): print(f"ERROR: No existe '{gpkg_col}'"); sys.exit(1)
    if gpkg_reg is None: gpkg_reg = gpkg_col

    descriptores_clase_2 = (
        {v.strip().lower() for v in descriptores_str.split(",") if v.strip()}
        if descriptores_str else set(DESCRIPTORES_CLASE_2)
    )

    print("Cargando capas...")
    geoms_constr, _ = _load_layer(gpkg_constr, layer_constr, "Construcciones")
    geoms_asent,  _ = _load_layer(gpkg_asent,  layer_asent,  "Asentamientos")
    geoms_pad,    _ = _load_layer(gpkg_pad,     layer_pad,    "Padrones")
    geoms_peat,   _ = _load_layer(gpkg_peat,    layer_peat,   "Peatonales")
    geoms_verde,  _ = _load_layer(gpkg_verde,   layer_verde,  "Espacios Verdes")
    geoms_calles, extras_calles = _load_layer(gpkg_calles, layer_calles, "Calles", campo_tipo_via)

    tree_constr = _build_tree(geoms_constr)
    tree_asent  = _build_tree(geoms_asent)
    tree_pad    = _build_tree(geoms_pad)
    tree_peat   = _build_tree(geoms_peat)
    tree_verde  = _build_tree(geoms_verde)
    tree_calles = _build_tree(geoms_calles)

    # Registros
    gpkg_reg = os.path.normpath(gpkg_reg)
    con_reg  = sqlite3.connect(gpkg_reg)
    tabla_reg = _detectar_capa(con_reg, layer_reg, "registros")
    cols_reg  = _columnas(con_reg, tabla_reg)
    gc_reg    = _geom_col(con_reg, tabla_reg)
    c_id_reg  = _campo(cols_reg, campo_id_reg, "ID", "Id")
    if not c_id_reg:
        print(f"ERROR: Campo ID no encontrado en Registros."); con_reg.close(); sys.exit(1)

    reg_rows = con_reg.execute(f'SELECT "{c_id_reg}", "{gc_reg}" FROM "{tabla_reg}"').fetchall()
    con_reg.close()
    print(f"Capa registros: {tabla_reg} ({len(reg_rows)} filas)")

    def _clasificar_punto(pt):
        if geoms_constr and _point_in_any(pt, *tree_constr): return 6
        if geoms_asent  and _point_in_any(pt, *tree_asent):  return 6
        if geoms_pad    and _point_in_any(pt, *tree_pad):     return 5
        if geoms_peat   and _point_in_any(pt, *tree_peat):    return 4
        if geoms_verde  and _point_in_any(pt, *tree_verde):   return 3
        if geoms_calles:
            tipos = _calles_tipo(pt, *tree_calles, extras_calles, buffer_calles, descriptores_clase_2)
            if tipos & descriptores_clase_2: return 2
        return 1

    clase_por_id = {}
    for row in reg_rows:
        rid = str(row[0]).strip() if row[0] is not None else ""
        if not rid or row[1] is None: continue
        g = _blob_to_geom(row[1])
        if g is None or g.is_empty: continue
        clase_por_id[rid] = _clasificar_punto(g)
    print(f"Registros clasificados: {len(clase_por_id)}")

    # Colectores
    con_col = sqlite3.connect(gpkg_col)
    con_col.execute("PRAGMA journal_mode=WAL")
    tabla_col = _detectar_capa(con_col, layer_col, "colectores")
    cols_col  = _columnas(con_col, tabla_col)
    c_ini = _campo(cols_col, campo_reg_ini)
    c_fin = _campo(cols_col, campo_reg_fin, "Registro_FInal")
    if not c_ini: print(f"ERROR: '{campo_reg_ini}' no encontrado."); con_col.close(); sys.exit(1)
    if not c_fin: print(f"ERROR: '{campo_reg_fin}' no encontrado."); con_col.close(); sys.exit(1)

    if not _campo(cols_col, campo_cf):
        con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{campo_cf}" INTEGER')

    filas = con_col.execute(
        f'SELECT fid, "{c_ini}", "{c_fin}", "{campo_cf}" FROM "{tabla_col}"'
    ).fetchall()

    triggers = con_col.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_col,)
    ).fetchall()
    for name, _ in triggers: con_col.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for fid, ini, fin, cf_actual in filas:
        id_ini = str(ini).strip() if ini is not None else ""
        id_fin = str(fin).strip() if fin is not None else ""
        c_ini_cl = clase_por_id.get(id_ini)
        c_fin_cl = clase_por_id.get(id_fin)
        if c_ini_cl is not None and c_fin_cl is not None:
            nueva = min(c_ini_cl, c_fin_cl)
        elif c_ini_cl is not None: nueva = c_ini_cl
        elif c_fin_cl is not None: nueva = c_fin_cl
        else: nueva = None
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
    p = argparse.ArgumentParser(description="CF Acceso Mantenimiento standalone")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--layer-col",   default=None)
    p.add_argument("--gpkg-reg",    default=None,
                   help="GeoPackage con Registros (default: mismo que --gpkg)")
    p.add_argument("--layer-reg",   default=None)
    p.add_argument("--gpkg-constr", default=None); p.add_argument("--layer-constr", default=None)
    p.add_argument("--gpkg-asent",  default=None); p.add_argument("--layer-asent",  default=None)
    p.add_argument("--gpkg-pad",    default=None); p.add_argument("--layer-pad",    default=None)
    p.add_argument("--gpkg-peat",   default=None); p.add_argument("--layer-peat",   default=None)
    p.add_argument("--gpkg-verde",  default=None); p.add_argument("--layer-verde",  default=None)
    p.add_argument("--gpkg-calles", default=None); p.add_argument("--layer-calles", default=None)
    p.add_argument("--campo-cf",           default=CAMPO_CF_ACCESO_DEFAULT)
    p.add_argument("--campo-reg-ini",      default=CAMPO_REGISTRO_INICIAL)
    p.add_argument("--campo-reg-fin",      default=CAMPO_REGISTRO_FINAL)
    p.add_argument("--campo-id-reg",       default=CAMPO_ID_REGISTRO)
    p.add_argument("--campo-tipo-via",     default=CAMPO_TIPO_VIA)
    p.add_argument("--descriptores-cl2",   default=None,
                   help="Tipos de via que dan clase 2 (separados por coma)")
    p.add_argument("--buffer-calles",      default=BUFFER_CALLES, type=float)
    a = p.parse_args()
    run(a.gpkg_col, a.layer_col, a.gpkg_reg, a.layer_reg,
        a.gpkg_constr, a.layer_constr, a.gpkg_asent, a.layer_asent,
        a.gpkg_pad, a.layer_pad, a.gpkg_peat, a.layer_peat,
        a.gpkg_verde, a.layer_verde, a.gpkg_calles, a.layer_calles,
        a.campo_cf, a.campo_reg_ini, a.campo_reg_fin, a.campo_id_reg,
        a.campo_tipo_via, a.descriptores_cl2, a.buffer_calles)

if __name__ == "__main__":
    main()
