"""
CF Profundidad - standalone sin QGIS.
Clasifica colectores por profundidad maxima de sus registros adyacentes.

Usa dos tablas dentro del mismo o diferente .gpkg:
  - Colectores: Registro_Inicial, Registro_Final → CF_Profundidad
  - Registros:  ID, PROFUNDIDAD [, Profundidad_Inspeccionada]

Uso:
    python scripts\\run_cf_profundidad.py --gpkg-col <ruta> --gpkg-reg <ruta>
    python scripts\\run_cf_profundidad.py --gpkg-col <ruta> --gpkg-reg <ruta> \\
        --layer-col vsstramoarteaga_prueba --layer-reg vsregistros
"""
import argparse, sqlite3, sys, os

CAMPO_CF_PROFUNDIDAD            = "CF_Profundidad"
CAMPO_REGISTRO_INICIAL          = "Registro_Inicial"
CAMPO_REGISTRO_FINAL            = "Registro_Final"
CAMPO_ID_REGISTRO               = "ID"
CAMPO_PROFUNDIDAD               = "PROFUNDIDAD"
CAMPO_PROFUNDIDAD_INSPECCIONADA = "Profundidad_Inspeccionada"
RANGO_DEFAULT = "2=1; 3=2; 4=3; 5=4; 7=5"


def _detectar_capa(con, layer_name, etiqueta="capa"):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print(f"ERROR: Sin capas en {etiqueta}."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no existe en {etiqueta}. Disponibles: {capas}"); sys.exit(1)
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


def _parse_rango(texto):
    limites = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par: continue
        v, _, c = par.partition("=")
        try:
            lim = float(v.strip().replace(",", "."))
            cls = int(c.strip())
            if lim > 0: limites.append((lim, cls))
        except ValueError: continue
    return sorted(limites, key=lambda x: x[0]) if limites else []


def _clasificar(prof, limites):
    if prof is None: return None
    for lim, cls in limites:
        if prof < lim: return cls
    return limites[-1][1] + 1 if limites else None


def run(gpkg_col, gpkg_reg=None,
        layer_col=None, layer_reg=None,
        campo_cf=CAMPO_CF_PROFUNDIDAD,
        campo_reg_ini=CAMPO_REGISTRO_INICIAL,
        campo_reg_fin=CAMPO_REGISTRO_FINAL,
        campo_id_reg=CAMPO_ID_REGISTRO,
        campo_prof=CAMPO_PROFUNDIDAD,
        campo_prof_inspec=CAMPO_PROFUNDIDAD_INSPECCIONADA,
        rango_str=RANGO_DEFAULT):

    gpkg_col = os.path.normpath(gpkg_col)
    if not os.path.isfile(gpkg_col): print(f"ERROR: No existe '{gpkg_col}'"); sys.exit(1)
    if gpkg_reg is None: gpkg_reg = gpkg_col
    else: gpkg_reg = os.path.normpath(gpkg_reg)
    if not os.path.isfile(gpkg_reg): print(f"ERROR: No existe '{gpkg_reg}'"); sys.exit(1)

    limites = _parse_rango(rango_str)

    con_col = sqlite3.connect(gpkg_col)
    con_col.execute("PRAGMA journal_mode=WAL")
    tabla_col = _detectar_capa(con_col, layer_col, "colectores")

    con_reg = sqlite3.connect(gpkg_reg) if gpkg_reg != gpkg_col else con_col
    if gpkg_reg != gpkg_col:
        con_reg.execute("PRAGMA journal_mode=WAL")
    tabla_reg = _detectar_capa(con_reg, layer_reg, "registros")

    cols_col = _columnas(con_col, tabla_col)
    cols_reg = _columnas(con_reg, tabla_reg)

    c_reg_ini = _campo(cols_col, campo_reg_ini)
    c_reg_fin = _campo(cols_col, campo_reg_fin)
    c_id_reg  = _campo(cols_reg, campo_id_reg, "ID", "Id")
    c_prof    = _campo(cols_reg, campo_prof)
    c_prof_i  = _campo(cols_reg, campo_prof_inspec)

    for nombre, val in [("Registro_Inicial", c_reg_ini), ("Registro_Final", c_reg_fin),
                        ("ID registros", c_id_reg), ("PROFUNDIDAD", c_prof)]:
        if not val:
            print(f"ERROR: Campo '{nombre}' no encontrado."); con_col.close(); sys.exit(1)

    print(f"Capa colectores : {tabla_col}")
    print(f"Capa registros  : {tabla_reg}")
    print(f"  Registro_Inicial  : {c_reg_ini}")
    print(f"  Registro_Final    : {c_reg_fin}")
    print(f"  ID registros      : {c_id_reg}")
    print(f"  Profundidad       : {c_prof}")
    print(f"  Prof. inspecc.    : {c_prof_i or '(no encontrado)'}")
    print(f"  Campo salida      : {campo_cf}")
    print(f"  Rangos            : {limites}")

    # Construir mapa id_reg -> prof_max
    reg_rows = con_reg.execute(
        f'SELECT "{c_id_reg}", "{c_prof}"'
        + (f', "{c_prof_i}"' if c_prof_i else '')
        + f' FROM "{tabla_reg}"'
    ).fetchall()

    mapa_prof = {}
    for row in reg_rows:
        rid = str(row[0]).strip() if row[0] is not None else ""
        if not rid: continue
        prof = _to_float(row[1])
        if c_prof_i:
            prof_i = _to_float(row[2])
            if prof_i is not None:
                prof = max(prof, prof_i) if prof is not None else prof_i
        if prof is not None:
            mapa_prof[rid] = prof
    print(f"  Registros con profundidad: {len(mapa_prof)}")

    if not _campo(cols_col, campo_cf):
        con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{campo_cf}" INTEGER')
        cols_col.append(campo_cf)

    filas = con_col.execute(
        f'SELECT fid, "{c_reg_ini}", "{c_reg_fin}", "{campo_cf}" FROM "{tabla_col}"'
    ).fetchall()

    triggers = con_col.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_col,)
    ).fetchall()
    for name, _ in triggers: con_col.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for fid, ini_id, fin_id, cf_actual in filas:
        ini_str = str(ini_id).strip() if ini_id is not None else ""
        fin_str = str(fin_id).strip() if fin_id is not None else ""
        p_ini   = mapa_prof.get(ini_str)
        p_fin   = mapa_prof.get(fin_str)
        if p_ini is not None and p_fin is not None:
            prof_max = max(p_ini, p_fin)
        elif p_ini is not None:
            prof_max = p_ini
        elif p_fin is not None:
            prof_max = p_fin
        else:
            prof_max = None
        nueva = _clasificar(prof_max, limites)
        if cf_actual != nueva:
            con_col.execute(
                f'UPDATE "{tabla_col}" SET "{campo_cf}"=? WHERE fid=?', (nueva, fid)
            )
            actualizadas += 1

    for _, sql in triggers:
        if sql: con_col.execute(sql)
    con_col.commit()
    if con_reg is not con_col: con_reg.close()
    con_col.close()
    print(f"OK. '{campo_cf}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="CF Profundidad standalone")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--gpkg-reg", default=None,
                   help="GeoPackage con Registros (default: mismo que --gpkg)")
    p.add_argument("--layer-col", default=None)
    p.add_argument("--layer-reg", default=None)
    p.add_argument("--campo-cf",          default=CAMPO_CF_PROFUNDIDAD)
    p.add_argument("--campo-reg-ini",     default=CAMPO_REGISTRO_INICIAL)
    p.add_argument("--campo-reg-fin",     default=CAMPO_REGISTRO_FINAL)
    p.add_argument("--campo-id-reg",      default=CAMPO_ID_REGISTRO)
    p.add_argument("--campo-prof",        default=CAMPO_PROFUNDIDAD)
    p.add_argument("--campo-prof-inspec", default=CAMPO_PROFUNDIDAD_INSPECCIONADA)
    p.add_argument("--rango",             default=RANGO_DEFAULT,
                   help="Ej: '2=1; 3=2; 4=3; 5=4; 7=5'")
    a = p.parse_args()
    run(a.gpkg_col, a.gpkg_reg, a.layer_col, a.layer_reg,
        a.campo_cf, a.campo_reg_ini, a.campo_reg_fin,
        a.campo_id_reg, a.campo_prof, a.campo_prof_inspec, a.rango)

if __name__ == "__main__":
    main()
