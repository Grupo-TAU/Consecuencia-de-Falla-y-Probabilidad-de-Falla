"""
PF Probabilidad de Falla - standalone sin QGIS.
Calcula PF desde PACP_Clasificacion.

Reglas:
    Vacio/NULL          -> 0
    2do char es letra   -> primer_digito + 1  (ej: "5B" -> 6.0)
    2do char es digito  -> primeros dos digitos / 10  (ej: "3222" -> 3.2)
    "0000"              -> 1.0

Uso:
    python scripts\\run_pf_probabilidad_falla.py --gpkg <ruta>
"""
import argparse, sqlite3, sys, os

CAMPO_PF   = "PF"
CAMPO_PACP = "Clasificación_PACP"


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


def _campo(cols, nombre):
    for c in cols:
        if c.lower() == nombre.lower(): return c
    return None


def _campo_pacp(cols):
    for c in cols:
        if "pacp" in c.lower() and "clasif" in c.lower(): return c
    for c in cols:
        if "pacp" in c.lower(): return c
    return None


def _calcular_pf(valor):
    if valor is None: return 0
    texto = str(valor).strip()
    if not texto or len(texto) < 2: return 0
    c1, c2 = texto[0], texto[1]
    if c1.isdigit() and c2.isalpha():
        return float(int(c1)) + 1.0
    if c1.isdigit() and c2.isdigit():
        v = int(c1 + c2) / 10.0
        return v if v > 0 else 1.0
    return 0


def run(gpkg_path, layer_name=None, campo_pacp=None, campo_pf=CAMPO_PF):
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path): print(f"ERROR: No existe '{gpkg_path}'"); sys.exit(1)
    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")
    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")
    cols = _columnas(con, tabla)
    c_pacp = _campo(cols, campo_pacp) if campo_pacp else _campo_pacp(cols)
    if not c_pacp:
        print(f"ERROR: No se encontro campo PACP_Clasificacion. Disponibles: {cols}"); con.close(); sys.exit(1)
    print(f"  Campo PACP   : {c_pacp}")
    print(f"  Campo salida : {campo_pf}")
    if not _campo(cols, campo_pf):
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_pf}" REAL')
    filas = con.execute(f'SELECT fid, "{c_pacp}", "{campo_pf}" FROM "{tabla}"').fetchall()
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for name, _ in triggers: con.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    actualizadas = 0
    for fid, pacp_val, pf_actual in filas:
        nueva = _calcular_pf(pacp_val)
        if pf_actual != nueva:
            con.execute(f'UPDATE "{tabla}" SET "{campo_pf}"=? WHERE fid=?', (nueva, fid))
            actualizadas += 1
    for _, sql in triggers:
        if sql: con.execute(sql)
    con.commit(); con.close()
    print(f"OK. '{campo_pf}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="PF Probabilidad de Falla standalone")
    p.add_argument("--gpkg", required=True)
    p.add_argument("--layer", default=None)
    p.add_argument("--campo-pacp", default=None,
                   help="Nombre del campo PACP_Clasificacion (autodetecta si no se especifica)")
    p.add_argument("--campo-pf", default=CAMPO_PF)
    a = p.parse_args()
    run(a.gpkg, a.layer, a.campo_pacp, a.campo_pf)

if __name__ == "__main__":
    main()
