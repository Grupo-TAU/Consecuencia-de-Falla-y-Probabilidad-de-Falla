"""
CF Diametro - standalone sin QGIS.
Clasifica colectores por diametro usando rangos configurables.

Uso:
    python scripts\\run_cf_diametro.py --gpkg <ruta>
    python scripts\\run_cf_diametro.py --gpkg <ruta> --rango "200=1; 300=2; 400=3; 500=4; 800=5"
"""
import argparse, re, sqlite3, sys, os

CAMPO_CF_DIAMETRO     = "CF_Diametro"
CAMPO_DIAMETRO        = "DIAMETRO"
RANGO_DEFAULT         = "200=1; 300=2; 400=3; 500=4; 800=5"


def _detectar_capa(con, layer_name):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas:
        print("ERROR: No hay capas de features."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no existe. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1:
        return capas[0]
    print(f"Varias capas: {capas}. Usa --layer."); sys.exit(1)


def _columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _campo(cols, nombre):
    for c in cols:
        if c.lower() == nombre.lower():
            return c
    return None


def _to_mm(value):
    if value is None: return None
    if isinstance(value, (int, float)): return float(value)
    text = str(value).strip()
    m = re.search(r"[-+]?\d[\d.,]*", text)
    if not m: return None
    t = m.group(0)
    if "." in t and "," in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        l, r = t.split(",", 1)
        t = l + r if len(r) == 3 else l + "." + r
    try: return float(t)
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
    return sorted(limites, key=lambda x: x[0]) or _parse_rango(RANGO_DEFAULT)


def _clasificar(diam, limites):
    if diam is None: return 0
    for lim, cls in limites:
        if diam < lim: return cls
    return limites[-1][1] + 1


def run(gpkg_path, layer_name=None, campo_diam=CAMPO_DIAMETRO,
        campo_salida=CAMPO_CF_DIAMETRO, rango_str=RANGO_DEFAULT):
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path):
        print(f"ERROR: No existe '{gpkg_path}'"); sys.exit(1)
    limites = _parse_rango(rango_str)
    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")
    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")
    cols = _columnas(con, tabla)
    c_diam = _campo(cols, campo_diam)
    if not c_diam:
        print(f"ERROR: Campo '{campo_diam}' no encontrado. Disponibles: {cols}"); con.close(); sys.exit(1)
    print(f"  Campo diametro : {c_diam}")
    print(f"  Campo salida   : {campo_salida}")
    print(f"  Rangos         : {limites}")
    if not _campo(cols, campo_salida):
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_salida}" INTEGER')
    filas = con.execute(f'SELECT fid, "{c_diam}", "{campo_salida}" FROM "{tabla}"').fetchall()
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for name, _ in triggers: con.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    actualizadas = 0
    for fid, diam_val, cf_actual in filas:
        nueva = _clasificar(_to_mm(diam_val), limites)
        if cf_actual != nueva:
            con.execute(f'UPDATE "{tabla}" SET "{campo_salida}"=? WHERE fid=?', (nueva, fid))
            actualizadas += 1
    for _, sql in triggers:
        if sql: con.execute(sql)
    con.commit(); con.close()
    print(f"OK. '{campo_salida}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="CF Diametro standalone")
    p.add_argument("--gpkg", required=True)
    p.add_argument("--layer", default=None)
    p.add_argument("--campo-diam", default=CAMPO_DIAMETRO)
    p.add_argument("--campo-salida", default=CAMPO_CF_DIAMETRO)
    p.add_argument("--rango", default=RANGO_DEFAULT,
                   help=f"Ej: '200=1; 300=2; 400=3; 500=4; 800=5' (default)")
    a = p.parse_args()
    run(a.gpkg, a.layer, a.campo_diam, a.campo_salida, a.rango)

if __name__ == "__main__":
    main()
