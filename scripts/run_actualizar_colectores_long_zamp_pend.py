"""
Actualizar Colectores Longitud, Cota Zampeado y Pendiente - standalone sin QGIS.

Pasos:
  1. Calcula Longitud desde la geometria (WKB parsing).
  2. Copia Cota_Zampeado de Registros a colectores (solo si estan vacios).
  3. Recalcula Pendiente = ((cota_ini - cota_fin) / longitud) * 100.

Prerequisito: ejecutar primero actualizar_registros_cota_zampeado.

Uso:
    python scripts\\run_actualizar_colectores_long_zamp_pend.py --gpkg-col <ruta>
    python scripts\\run_actualizar_colectores_long_zamp_pend.py \\
        --gpkg-col <ruta> --gpkg-reg <ruta>
"""
import argparse, sqlite3, struct, math, sys, os

# Campos Colectores
CAMPO_LONGITUD_DEFAULT   = "Longitud"
CAMPO_REG_INI_DEFAULT    = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT    = "Registro_Final"
CAMPO_COTA_INI_DEFAULT   = "Registro_Inicial_Cota_Zampeado"
CAMPO_COTA_FIN_DEFAULT   = "Registro_Final_Cota_Zampeado"
CAMPO_PENDIENTE_DEFAULT  = "Pendiente"
# Campos Registros
CAMPO_ID_REG_DEFAULT      = "ID"
CAMPO_COTA_ZAMP_DEFAULT   = "Cota_Zampeado_Calculada"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"


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


def _to_float(v):
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    try: return float(str(v).strip().replace(",", "."))
    except ValueError: return None


def _is_null(v):
    if v is None: return True
    return str(v).strip().upper() in ("", "NULL")


# ── WKB parsing ───────────────────────────────────────────────────────────────

def _wkb_offset(blob):
    """Bytes del header GeoPackage antes del WKB standard."""
    if blob is None or len(blob) < 8: return -1
    if bytes(blob[:2]) != b'GP': return -1
    flags = blob[3]
    env_type = (flags & 0x0E) >> 1
    env_sizes = [0, 32, 48, 48, 64]
    env_size = env_sizes[env_type] if env_type <= 4 else 0
    return 8 + env_size


def _points_from_blob(blob):
    """Lista de (x, y) de una geometría LineString en GeoPackage blob."""
    offset = _wkb_offset(blob)
    if offset < 0: return []
    wkb = bytes(blob[offset:])
    if len(wkb) < 9: return []
    bo = wkb[0]
    endian = '<' if bo == 1 else '>'
    geom_type = struct.unpack_from(endian + 'I', wkb, 1)[0]
    if geom_type != 2: return []
    num_pts = struct.unpack_from(endian + 'I', wkb, 5)[0]
    if len(wkb) < 9 + num_pts * 16: return []
    pts = []
    for i in range(num_pts):
        x, y = struct.unpack_from(endian + 'dd', wkb, 9 + i * 16)
        pts.append((x, y))
    return pts


def _line_length(points):
    if len(points) < 2: return 0.0
    total = 0.0
    for i in range(1, len(points)):
        dx = points[i][0] - points[i-1][0]
        dy = points[i][1] - points[i-1][1]
        total += math.sqrt(dx*dx + dy*dy)
    return total


# ── Main ──────────────────────────────────────────────────────────────────────

def run(gpkg_col, gpkg_reg=None,
        layer_col=None, layer_reg=None,
        campo_longitud=CAMPO_LONGITUD_DEFAULT,
        campo_reg_ini=CAMPO_REG_INI_DEFAULT,
        campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
        campo_cota_ini=CAMPO_COTA_INI_DEFAULT,
        campo_cota_fin=CAMPO_COTA_FIN_DEFAULT,
        campo_pendiente=CAMPO_PENDIENTE_DEFAULT,
        campo_id_reg=CAMPO_ID_REG_DEFAULT,
        campo_cota_zamp=CAMPO_COTA_ZAMP_DEFAULT):

    gpkg_col = os.path.normpath(gpkg_col)
    if not os.path.isfile(gpkg_col): print(f"ERROR: No existe '{gpkg_col}'"); sys.exit(1)

    con_col = sqlite3.connect(gpkg_col)
    con_col.execute("PRAGMA journal_mode=WAL")
    tabla_col = _detectar_capa(con_col, layer_col, "colectores")
    cols_col  = _columnas(con_col, tabla_col)

    # Nombre de columna de geometria
    geom_col_name = "geom"
    gc_rows = con_col.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (tabla_col,)
    ).fetchall()
    if gc_rows: geom_col_name = gc_rows[0][0]

    c_long = _campo(cols_col, campo_longitud)
    c_ini  = _campo(cols_col, campo_reg_ini)
    c_fin  = _campo(cols_col, campo_reg_fin)
    c_ci   = _campo(cols_col, campo_cota_ini)
    c_cf   = _campo(cols_col, campo_cota_fin)
    c_pend = _campo(cols_col, campo_pendiente, "Slope", "slope")

    can_copy_cotas = gpkg_reg is not None

    # Auto-crear campos faltantes
    for fname in (campo_longitud, campo_pendiente):
        if not _campo(cols_col, fname):
            con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{fname}" REAL')
            cols_col.append(fname)
    if can_copy_cotas:
        for fname in (campo_cota_ini, campo_cota_fin):
            if not _campo(cols_col, fname):
                con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{fname}" REAL')
                cols_col.append(fname)
    # Re-detectar indices
    c_long = _campo(cols_col, campo_longitud)
    c_ci   = _campo(cols_col, campo_cota_ini)
    c_cf   = _campo(cols_col, campo_cota_fin)
    c_pend = _campo(cols_col, campo_pendiente, "Slope", "slope")

    print(f"Capa colectores : {tabla_col}")
    print(f"  Longitud     : {c_long}")
    print(f"  Cota Ini     : {c_ci or '(no aplica)'}")
    print(f"  Cota Fin     : {c_cf or '(no aplica)'}")
    print(f"  Pendiente    : {c_pend}")
    print(f"  Geometria    : {geom_col_name}")

    # Mapa registros → cota
    mapa_cota = {}
    if can_copy_cotas:
        gpkg_reg = os.path.normpath(gpkg_reg)
        if not os.path.isfile(gpkg_reg):
            print(f"ERROR: No existe '{gpkg_reg}'"); con_col.close(); sys.exit(1)
        con_reg = sqlite3.connect(gpkg_reg)
        tabla_reg = _detectar_capa(con_reg, layer_reg, "registros")
        cols_reg  = _columnas(con_reg, tabla_reg)
        c_id_reg  = _campo(cols_reg, campo_id_reg, "ID", "Id")
        c_cz_reg  = _campo(cols_reg, campo_cota_zamp)
        if not c_id_reg or not c_cz_reg:
            print(f"ERROR: Campos ID o Cota_Zampeado no encontrados en Registros."); con_reg.close(); con_col.close(); sys.exit(1)
        for row in con_reg.execute(
            f'SELECT "{c_id_reg}", "{c_cz_reg}" FROM "{tabla_reg}"'
        ).fetchall():
            rid = str(row[0]).strip() if row[0] is not None else ""
            cz  = _to_float(row[1])
            if rid and cz is not None: mapa_cota[rid] = cz
        con_reg.close()
        print(f"  Registros con cota: {len(mapa_cota)}")

    # Leer colectores
    extra_campos = [f'"{c_ci}"', f'"{c_cf}"'] if (can_copy_cotas and c_ci and c_cf) else ["NULL", "NULL"]
    ini_col = f'"{c_ini}"' if c_ini else "NULL"
    fin_col = f'"{c_fin}"' if c_fin else "NULL"
    filas = con_col.execute(
        f'SELECT fid, "{geom_col_name}", "{c_long}", {ini_col}, {fin_col}, '
        f'{extra_campos[0]}, {extra_campos[1]}, "{c_pend}" FROM "{tabla_col}"'
    ).fetchall()

    triggers = con_col.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_col,)
    ).fetchall()
    for name, _ in triggers: con_col.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for row in filas:
        fid, blob, long_actual, reg_ini, reg_fin, cota_ini_act, cota_fin_act, pend_actual = row

        hubo_cambios = {}

        # Longitud desde geometria
        pts = _points_from_blob(blob)
        if pts:
            long_calc = round(_line_length(pts), 2)
            la = _to_float(long_actual)
            if la is None or round(la, 2) != long_calc:
                hubo_cambios[c_long] = long_calc

        long_nueva = hubo_cambios.get(c_long, _to_float(long_actual))

        # Copiar cotas desde registros
        if can_copy_cotas and c_ini and c_fin and c_ci and c_cf:
            ri = str(reg_ini).strip() if reg_ini is not None else ""
            rf = str(reg_fin).strip() if reg_fin is not None else ""
            if _is_null(cota_ini_act) or _to_float(cota_ini_act) == 0:
                ci_new = mapa_cota.get(ri)
                if ci_new is not None: hubo_cambios[c_ci] = ci_new
            if _is_null(cota_fin_act) or _to_float(cota_fin_act) == 0:
                cf_new = mapa_cota.get(rf)
                if cf_new is not None: hubo_cambios[c_cf] = cf_new

        # Recalcular pendiente
        ci_val = hubo_cambios.get(c_ci, _to_float(cota_ini_act)) if c_ci else None
        cf_val = hubo_cambios.get(c_cf, _to_float(cota_fin_act)) if c_cf else None
        if (ci_val is not None and cf_val is not None
                and long_nueva is not None and abs(long_nueva) > 1e-12):
            if ci_val == 0 or cf_val == 0:
                pend_calc = 0.0
            else:
                pend_calc = round(((ci_val - cf_val) / long_nueva) * 100.0, 6)
            pa = _to_float(pend_actual)
            if pa is None or round(pa, 6) != pend_calc:
                hubo_cambios[c_pend] = pend_calc

        if hubo_cambios:
            sets = ", ".join(f'"{k}"=?' for k in hubo_cambios)
            vals = list(hubo_cambios.values()) + [fid]
            con_col.execute(f'UPDATE "{tabla_col}" SET {sets} WHERE fid=?', vals)
            actualizadas += 1

    for _, sql in triggers:
        if sql: con_col.execute(sql)
    con_col.commit(); con_col.close()
    print(f"OK. {actualizadas}/{len(filas)} colectores actualizados.")


def main():
    p = argparse.ArgumentParser(description="Actualizar Colectores Longitud/Cota/Pendiente standalone")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--gpkg-reg", default=None,
                   help="GeoPackage con Registros para copiar cotas (opcional)")
    p.add_argument("--layer-col",          default=None)
    p.add_argument("--layer-reg",          default=None)
    p.add_argument("--campo-longitud",     default=CAMPO_LONGITUD_DEFAULT)
    p.add_argument("--campo-reg-ini",      default=CAMPO_REG_INI_DEFAULT)
    p.add_argument("--campo-reg-fin",      default=CAMPO_REG_FIN_DEFAULT)
    p.add_argument("--campo-cota-ini",     default=CAMPO_COTA_INI_DEFAULT)
    p.add_argument("--campo-cota-fin",     default=CAMPO_COTA_FIN_DEFAULT)
    p.add_argument("--campo-pendiente",    default=CAMPO_PENDIENTE_DEFAULT)
    p.add_argument("--campo-id-reg",       default=CAMPO_ID_REG_DEFAULT)
    p.add_argument("--campo-cota-zamp",    default=CAMPO_COTA_ZAMP_DEFAULT)
    a = p.parse_args()
    run(a.gpkg_col, a.gpkg_reg, a.layer_col, a.layer_reg,
        a.campo_longitud, a.campo_reg_ini, a.campo_reg_fin,
        a.campo_cota_ini, a.campo_cota_fin, a.campo_pendiente,
        a.campo_id_reg, a.campo_cota_zamp)

if __name__ == "__main__":
    main()
