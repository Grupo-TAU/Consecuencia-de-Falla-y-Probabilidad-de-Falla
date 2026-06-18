"""
Asignar Registro Inicial y Final en Colectores - standalone sin QGIS.
Busca el registro mas cercano a cada extremo del colector (dentro de tolerancia).
Solo asigna si el campo esta vacio.

Requiere que Colectores y Registros sean LineString y Point respectivamente.

Uso:
    python scripts\\run_asignar_registros_colectores.py --gpkg-col <ruta> --gpkg-reg <ruta>
    python scripts\\run_asignar_registros_colectores.py \\
        --gpkg-col <ruta> --gpkg-reg <ruta> --tolerancia 0.5
"""
import argparse, sqlite3, struct, math, sys, os

CAMPO_REG_INI_DEFAULT   = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT   = "Registro_Final"
CAMPO_ID_REG_DEFAULT    = "ID"
TOLERANCIA_DEFAULT      = 0.5


def _detectar_capa(con, layer_name, etiqueta="capa"):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print(f"ERROR: Sin capas en {etiqueta}."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no existe. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1: return capas[0]
    print(f"Varias capas en {etiqueta}: {capas}. Usa el argumento correspondiente."); sys.exit(1)


def _columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _campo(cols, *nombres):
    lower = {c.lower(): c for c in cols}
    for n in nombres:
        if n.lower() in lower: return lower[n.lower()]
    return None


def _normalize(v):
    if v is None: return ""
    return str(v).strip()


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
    env_size = env_sizes[env_type] if env_type <= 4 else 0
    return 8 + env_size


def _endpoints_from_blob(blob):
    """Devuelve ((x0,y0), (x_last,y_last)) de un LineString GeoPackage blob."""
    offset = _wkb_offset(blob)
    if offset < 0: return None, None
    wkb = bytes(blob[offset:])
    if len(wkb) < 9: return None, None
    bo = wkb[0]
    endian = '<' if bo == 1 else '>'
    geom_type = struct.unpack_from(endian + 'I', wkb, 1)[0]
    if geom_type != 2: return None, None
    num_pts = struct.unpack_from(endian + 'I', wkb, 5)[0]
    if num_pts < 1 or len(wkb) < 9 + num_pts * 16: return None, None
    x0, y0 = struct.unpack_from(endian + 'dd', wkb, 9)
    xn, yn = struct.unpack_from(endian + 'dd', wkb, 9 + (num_pts - 1) * 16)
    return (x0, y0), (xn, yn)


def _point_from_blob(blob):
    """Devuelve (x, y) de un Point GeoPackage blob."""
    offset = _wkb_offset(blob)
    if offset < 0: return None
    wkb = bytes(blob[offset:])
    if len(wkb) < 21: return None
    bo = wkb[0]
    endian = '<' if bo == 1 else '>'
    geom_type = struct.unpack_from(endian + 'I', wkb, 1)[0]
    if geom_type != 1: return None
    x, y = struct.unpack_from(endian + 'dd', wkb, 5)
    return (x, y)


def _dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def _nearest(query_pt, reg_pts, tolerancia):
    """Devuelve el ID del registro mas cercano dentro de tolerancia, o None."""
    best_id, best_d = None, float('inf')
    for rid, pt in reg_pts:
        d = _dist(query_pt, pt)
        if d < best_d:
            best_d = d
            best_id = rid
    return best_id if best_d <= tolerancia else None


def run(gpkg_col, gpkg_reg,
        layer_col=None, layer_reg=None,
        campo_reg_ini=CAMPO_REG_INI_DEFAULT,
        campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
        campo_id_reg=CAMPO_ID_REG_DEFAULT,
        tolerancia=TOLERANCIA_DEFAULT):

    gpkg_col = os.path.normpath(gpkg_col)
    gpkg_reg = os.path.normpath(gpkg_reg)
    for path in (gpkg_col, gpkg_reg):
        if not os.path.isfile(path):
            print(f"ERROR: No existe '{path}'"); sys.exit(1)

    con_col = sqlite3.connect(gpkg_col)
    con_col.execute("PRAGMA journal_mode=WAL")
    tabla_col = _detectar_capa(con_col, layer_col, "colectores")
    cols_col  = _columnas(con_col, tabla_col)
    gc_col    = _geom_col(con_col, tabla_col)

    con_reg = sqlite3.connect(gpkg_reg) if gpkg_reg != gpkg_col else con_col
    if gpkg_reg != gpkg_col:
        con_reg.execute("PRAGMA journal_mode=WAL")
    tabla_reg = _detectar_capa(con_reg, layer_reg, "registros")
    cols_reg  = _columnas(con_reg, tabla_reg)
    gc_reg    = _geom_col(con_reg, tabla_reg)

    c_id_reg = _campo(cols_reg, campo_id_reg, "ID", "Id")
    if not c_id_reg:
        print(f"ERROR: Campo '{campo_id_reg}' no encontrado en Registros."); sys.exit(1)

    c_ini = _campo(cols_col, campo_reg_ini)
    c_fin = _campo(cols_col, campo_reg_fin, "Registro_FInal")

    # Crear campos si no existen
    for fname in (campo_reg_ini, campo_reg_fin):
        if not _campo(cols_col, fname):
            con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{fname}" TEXT')
            cols_col.append(fname)
    c_ini = _campo(cols_col, campo_reg_ini)
    c_fin = _campo(cols_col, campo_reg_fin, "Registro_FInal")

    print(f"Capa colectores : {tabla_col}")
    print(f"Capa registros  : {tabla_reg}")
    print(f"  Registro_Inicial : {c_ini}")
    print(f"  Registro_Final   : {c_fin}")
    print(f"  ID Registros     : {c_id_reg}")
    print(f"  Tolerancia       : {tolerancia} m")

    # Cargar registros con su punto
    reg_pts = []
    for row in con_reg.execute(
        f'SELECT "{c_id_reg}", "{gc_reg}" FROM "{tabla_reg}"'
    ).fetchall():
        rid = _normalize(row[0])
        if not rid or row[1] is None: continue
        pt = _point_from_blob(row[1])
        if pt is not None: reg_pts.append((rid, pt))
    print(f"  Registros cargados: {len(reg_pts)}")

    # Cargar colectores
    filas = con_col.execute(
        f'SELECT fid, "{gc_col}", "{c_ini}", "{c_fin}" FROM "{tabla_col}"'
    ).fetchall()

    triggers = con_col.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_col,)
    ).fetchall()
    for name, _ in triggers: con_col.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    asignados_ini = 0
    asignados_fin = 0
    for fid, blob, ini_actual, fin_actual in filas:
        if blob is None: continue
        pt_ini, pt_fin = _endpoints_from_blob(blob)
        if pt_ini is None: continue

        ini_str = _normalize(ini_actual)
        fin_str = _normalize(fin_actual)

        if not ini_str:
            rid = _nearest(pt_ini, reg_pts, tolerancia)
            if rid:
                con_col.execute(
                    f'UPDATE "{tabla_col}" SET "{c_ini}"=? WHERE fid=?', (rid, fid)
                )
                asignados_ini += 1

        if not fin_str:
            rid = _nearest(pt_fin, reg_pts, tolerancia)
            if rid:
                con_col.execute(
                    f'UPDATE "{tabla_col}" SET "{c_fin}"=? WHERE fid=?', (rid, fid)
                )
                asignados_fin += 1

    for _, sql in triggers:
        if sql: con_col.execute(sql)
    con_col.commit()
    if con_reg is not con_col: con_reg.close()
    con_col.close()
    print(f"OK. Registro_Inicial asignados: {asignados_ini}, Registro_Final asignados: {asignados_fin}.")


def main():
    p = argparse.ArgumentParser(description="Asignar Registros a Colectores standalone")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--gpkg-reg", required=True,
                   help="GeoPackage con Registros")
    p.add_argument("--layer-col",        default=None)
    p.add_argument("--layer-reg",        default=None)
    p.add_argument("--campo-reg-ini",    default=CAMPO_REG_INI_DEFAULT)
    p.add_argument("--campo-reg-fin",    default=CAMPO_REG_FIN_DEFAULT)
    p.add_argument("--campo-id-reg",     default=CAMPO_ID_REG_DEFAULT)
    p.add_argument("--tolerancia",       default=TOLERANCIA_DEFAULT, type=float,
                   help="Tolerancia geometrica en metros (default 0.5)")
    a = p.parse_args()
    run(a.gpkg_col, a.gpkg_reg, a.layer_col, a.layer_reg,
        a.campo_reg_ini, a.campo_reg_fin, a.campo_id_reg, a.tolerancia)

if __name__ == "__main__":
    main()
