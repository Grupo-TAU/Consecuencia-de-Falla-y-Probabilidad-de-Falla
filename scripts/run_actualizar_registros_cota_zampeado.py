"""
Actualizar Registros - Cota Zampeado - standalone sin QGIS.

Dos mecanicas (pueden correr juntas):
  Mecanica 1: Cota_Zampeado = Cota_Tapa - Profundidad_Inspeccionada
  Mecanica 2: Copia ZARRIBA del colector al Registro_Inicial del colector

Solo actualiza registros donde Cota_Zampeado_Calculada este vacio.

Uso:
    python scripts\\run_actualizar_registros_cota_zampeado.py --gpkg-reg <ruta>
    python scripts\\run_actualizar_registros_cota_zampeado.py \\
        --gpkg-reg <ruta> --gpkg-col <ruta>
"""
import argparse, sqlite3, sys, os

CAMPO_COTA_ZAMP_DEFAULT   = "Cota_Zampeado_Calculada"
CAMPO_COTA_TAPA_DEFAULT   = "Cota_Tapa_Inspeccionada"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"
CAMPO_ID_REG_DEFAULT      = "ID"
CAMPO_ZARRIBA_DEFAULT     = "ZARRIBA"
CAMPO_REG_INI_COL_DEFAULT = "Registro_Inicial"


def _detectar_capa(con, layer_name, etiqueta="capa"):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print(f"ERROR: Sin capas en {etiqueta}."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no en {etiqueta}. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1: return capas[0]
    print(f"Varias capas en {etiqueta}: {capas}. Especifica con el argumento correspondiente."); sys.exit(1)


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


def run(gpkg_reg, gpkg_col=None,
        layer_reg=None, layer_col=None,
        campo_cota_zamp=CAMPO_COTA_ZAMP_DEFAULT,
        campo_cota_tapa=CAMPO_COTA_TAPA_DEFAULT,
        campo_prof_inspec=CAMPO_PROF_INSPEC_DEFAULT,
        campo_id_reg=CAMPO_ID_REG_DEFAULT,
        campo_zarriba=CAMPO_ZARRIBA_DEFAULT,
        campo_reg_ini_col=CAMPO_REG_INI_COL_DEFAULT):

    gpkg_reg = os.path.normpath(gpkg_reg)
    if not os.path.isfile(gpkg_reg): print(f"ERROR: No existe '{gpkg_reg}'"); sys.exit(1)

    con_reg = sqlite3.connect(gpkg_reg)
    con_reg.execute("PRAGMA journal_mode=WAL")
    tabla_reg = _detectar_capa(con_reg, layer_reg, "registros")
    cols_reg  = _columnas(con_reg, tabla_reg)

    c_zamp  = _campo(cols_reg, campo_cota_zamp)
    c_tapa  = _campo(cols_reg, campo_cota_tapa)
    c_prof  = _campo(cols_reg, campo_prof_inspec)
    c_id    = _campo(cols_reg, campo_id_reg, "ID", "Id")

    if not c_tapa:
        print(f"ERROR: Campo '{campo_cota_tapa}' no encontrado en Registros."); con_reg.close(); sys.exit(1)

    if not c_zamp:
        con_reg.execute(f'ALTER TABLE "{tabla_reg}" ADD COLUMN "{campo_cota_zamp}" REAL')
        cols_reg.append(campo_cota_zamp)
        c_zamp = campo_cota_zamp
        print(f"  Creado campo '{campo_cota_zamp}'")

    can_paso1 = c_prof is not None
    can_paso2 = gpkg_col is not None

    if not can_paso1:
        print(f"AVISO: '{campo_prof_inspec}' no encontrado — se omite Mecanica 1.")
    if not can_paso2:
        print("AVISO: --gpkg-col no proporcionado — se omite Mecanica 2.")
    if not can_paso1 and not can_paso2:
        print("ERROR: No hay mecanica disponible."); con_reg.close(); sys.exit(1)

    if can_paso2 and not c_id:
        print(f"ERROR: Campo ID '{campo_id_reg}' no encontrado en Registros."); con_reg.close(); sys.exit(1)

    print(f"Capa registros: {tabla_reg}")
    print(f"  Cota Zampeado      : {c_zamp}")
    print(f"  Cota Tapa          : {c_tapa}")
    print(f"  Prof. Inspeccionada: {c_prof or '(no encontrado)'}")
    print(f"  ID Registros       : {c_id or '(no encontrado)'}")

    # Leer registros
    sel = f'fid, "{c_id or c_tapa}", "{c_tapa}", "{c_zamp}"'
    if c_prof: sel += f', "{c_prof}"'
    filas_reg = {
        row[0]: row for row in con_reg.execute(
            f'SELECT {sel} FROM "{tabla_reg}"'
        ).fetchall()
    }

    triggers_reg = con_reg.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_reg,)
    ).fetchall()
    for name, _ in triggers_reg: con_reg.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizados = 0
    fids_paso1   = set()

    # Mecanica 1
    if can_paso1:
        print("--- Mecanica 1: Cota_Tapa - Profundidad ---")
        for fid, row in filas_reg.items():
            val_zamp = row[3]
            if not _is_null(val_zamp): continue
            cota_tapa   = _to_float(row[2])
            prof_inspec = _to_float(row[4]) if c_prof else None
            if cota_tapa is None or prof_inspec is None: continue
            calc = round(cota_tapa - prof_inspec, 2)
            con_reg.execute(
                f'UPDATE "{tabla_reg}" SET "{c_zamp}"=? WHERE fid=?', (calc, fid)
            )
            actualizados += 1
            fids_paso1.add(fid)
        print(f"  Mecanica 1: {len(fids_paso1)} registros actualizados.")

    # Mecanica 2
    if can_paso2:
        gpkg_col = os.path.normpath(gpkg_col)
        if not os.path.isfile(gpkg_col):
            print(f"ERROR: No existe '{gpkg_col}'"); con_reg.close(); sys.exit(1)
        con_col = sqlite3.connect(gpkg_col)
        tabla_col = _detectar_capa(con_col, layer_col, "colectores")
        cols_col  = _columnas(con_col, tabla_col)
        c_zarr    = _campo(cols_col, campo_zarriba)
        c_ri_col  = _campo(cols_col, campo_reg_ini_col)
        print(f"  ZARRIBA            : {c_zarr}")
        print(f"  Registro_Inicial   : {c_ri_col}")
        if not c_zarr:
            print(f"ERROR: Campo '{campo_zarriba}' no encontrado en Colectores.")
            con_col.close(); con_reg.close(); sys.exit(1)
        if not c_ri_col:
            print(f"ERROR: Campo '{campo_reg_ini_col}' no encontrado en Colectores.")
            con_col.close(); con_reg.close(); sys.exit(1)

        # mapa id_registro -> fid_registro
        id_to_fid_reg = {}
        for fid, row in filas_reg.items():
            rid = str(row[1]).strip() if row[1] is not None else ""
            if rid: id_to_fid_reg[rid] = fid

        # Crear Profundidad_Inspeccionada en registros si no existe (para Mecanica 2)
        c_prof_out = _campo(cols_reg, campo_prof_inspec)
        if not c_prof_out:
            con_reg.execute(f'ALTER TABLE "{tabla_reg}" ADD COLUMN "{campo_prof_inspec}" REAL')
            c_prof_out = campo_prof_inspec
            print(f"  Creado campo '{campo_prof_inspec}'")

        colectores = con_col.execute(
            f'SELECT fid, "{c_ri_col}", "{c_zarr}" FROM "{tabla_col}"'
        ).fetchall()
        con_col.close()

        actualizados_paso2 = 0
        print("--- Mecanica 2: ZARRIBA desde Colectores ---")
        for _, reg_ini_id, zarriba_val in colectores:
            reg_ini_str = str(reg_ini_id).strip() if reg_ini_id is not None else ""
            if not reg_ini_str: continue
            zarr = _to_float(zarriba_val)
            if zarr is None: continue
            fid_reg = id_to_fid_reg.get(reg_ini_str)
            if fid_reg is None: continue
            if fid_reg in fids_paso1: continue
            row = filas_reg.get(fid_reg)
            if row is None or not _is_null(row[3]): continue
            con_reg.execute(
                f'UPDATE "{tabla_reg}" SET "{c_zamp}"=? WHERE fid=?', (zarr, fid_reg)
            )
            cota_tapa = _to_float(row[2])
            if cota_tapa is not None:
                if cota_tapa == 0 or zarr == 0:
                    prof_calc = 0.0
                else:
                    prof_calc = round(cota_tapa - zarr, 2)
                con_reg.execute(
                    f'UPDATE "{tabla_reg}" SET "{c_prof_out}"=? WHERE fid=?', (prof_calc, fid_reg)
                )
            actualizados += 1
            actualizados_paso2 += 1
        print(f"  Mecanica 2: {actualizados_paso2} registros actualizados.")

    for _, sql in triggers_reg:
        if sql: con_reg.execute(sql)
    con_reg.commit(); con_reg.close()
    print(f"OK. Total registros actualizados: {actualizados}.")


def main():
    p = argparse.ArgumentParser(description="Actualizar Registros Cota Zampeado standalone")
    p.add_argument("--gpkg", "--gpkg-reg", dest="gpkg_reg", required=True,
                   help="GeoPackage con Registros")
    p.add_argument("--gpkg-col", default=None,
                   help="GeoPackage con Colectores (requerido para Mecanica 2)")
    p.add_argument("--layer-reg",           default=None)
    p.add_argument("--layer-col",           default=None)
    p.add_argument("--campo-cota-zamp",     default=CAMPO_COTA_ZAMP_DEFAULT)
    p.add_argument("--campo-cota-tapa",     default=CAMPO_COTA_TAPA_DEFAULT)
    p.add_argument("--campo-prof-inspec",   default=CAMPO_PROF_INSPEC_DEFAULT)
    p.add_argument("--campo-id-reg",        default=CAMPO_ID_REG_DEFAULT)
    p.add_argument("--campo-zarriba",       default=CAMPO_ZARRIBA_DEFAULT)
    p.add_argument("--campo-reg-ini-col",   default=CAMPO_REG_INI_COL_DEFAULT)
    a = p.parse_args()
    run(a.gpkg_reg, a.gpkg_col, a.layer_reg, a.layer_col,
        a.campo_cota_zamp, a.campo_cota_tapa, a.campo_prof_inspec,
        a.campo_id_reg, a.campo_zarriba, a.campo_reg_ini_col)

if __name__ == "__main__":
    main()
