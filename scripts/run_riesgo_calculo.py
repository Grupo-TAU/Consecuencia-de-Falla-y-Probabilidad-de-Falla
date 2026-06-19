"""
Riesgo - standalone sin QGIS.
Calcula Riesgo = Criticidad x PF. NULL o 0 se tratan como 1.

Uso:
    python scripts\\run_riesgo_calculo.py --gpkg <ruta>
"""
import argparse, sqlite3, sys, os

CAMPO_RIESGO     = "Riesgo"
CAMPO_CRITICIDAD = "criticidad"
CAMPO_PF         = "PF"


def _detectar_capa(con, layer_name):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print("ERROR: Sin capas."); sys.exit(1)
    if layer_name:
        if layer_name not in capas: print(f"ERROR: '{layer_name}' no existe. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1: return capas[0]
    print(f"Varias capas: {capas}. Usa --layer."); sys.exit(1)


def _columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _campo(cols, *nombres):
    lower = {c.lower(): c for c in cols}
    for n in nombres:
        if n.lower() in lower: return lower[n.lower()]
    return None


def _float(v):
    if v is None: return None
    try: return float(v)
    except (TypeError, ValueError): return None


def _calcular(criticidad, pf):
    cf = _float(criticidad)
    pf_val = _float(pf)
    if cf is None and pf_val is None: return None
    cf = cf if (cf and cf != 0) else 1.0
    pf_val = pf_val if (pf_val and pf_val != 0) else 1.0
    return round(cf * pf_val, 2)


def run(gpkg_path, layer_name=None, campo_criticidad=CAMPO_CRITICIDAD,
        campo_pf=CAMPO_PF, campo_riesgo=CAMPO_RIESGO):
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path): print(f"ERROR: No existe '{gpkg_path}'"); sys.exit(1)
    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")
    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")
    cols = _columnas(con, tabla)
    c_ct = _campo(cols, campo_criticidad, "Criticidad", "CT")
    c_pf = _campo(cols, campo_pf, "pf")
    if not c_ct: print(f"ERROR: Campo criticidad no encontrado. Disponibles: {cols}"); con.close(); sys.exit(1)
    if not c_pf: print(f"ERROR: Campo PF no encontrado. Disponibles: {cols}"); con.close(); sys.exit(1)
    print(f"  Campo criticidad : {c_ct}")
    print(f"  Campo PF         : {c_pf}")
    print(f"  Campo salida     : {campo_riesgo}")
    if not _campo(cols, campo_riesgo):
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_riesgo}" REAL')
    filas = con.execute(
        f'SELECT fid, "{c_ct}", "{c_pf}", "{campo_riesgo}" FROM "{tabla}"'
    ).fetchall()
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for name, _ in triggers: con.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    actualizadas = 0
    for fid, ct_val, pf_val, r_actual in filas:
        nuevo = _calcular(ct_val, pf_val)
        if r_actual != nuevo:
            con.execute(f'UPDATE "{tabla}" SET "{campo_riesgo}"=? WHERE fid=?', (nuevo, fid))
            actualizadas += 1
    for _, sql in triggers:
        if sql: con.execute(sql)
    con.commit(); con.close()
    print(f"OK. '{campo_riesgo}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="Riesgo standalone")
    p.add_argument("--gpkg", required=True)
    p.add_argument("--layer", default=None)
    p.add_argument("--campo-criticidad", default=CAMPO_CRITICIDAD)
    p.add_argument("--campo-pf", default=CAMPO_PF)
    p.add_argument("--campo-riesgo", default=CAMPO_RIESGO)
    a = p.parse_args()
    run(a.gpkg, a.layer, a.campo_criticidad, a.campo_pf, a.campo_riesgo)

if __name__ == "__main__":
    main()
