"""
CF Material - standalone sin QGIS.
Clasifica colectores por material usando un mapeo configurable.

Uso:
    python scripts\\run_cf_material.py --gpkg <ruta>
    python scripts\\run_cf_material.py --gpkg <ruta> --mapeo "PVC=3; Hormigon Simple=5"
"""
import argparse, sqlite3, sys, os, unicodedata

CAMPO_CF_MATERIAL = "CF_Material"
CAMPO_MATERIAL    = "Material"
MAPEO_DEFAULT = (
    "PE=1; PVC=3; PEAD=3; Otro Material=3; "
    "Hormigon Armado=4; Hormigon Simple=5; Mamposteria=6"
)


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


def _norm(texto):
    if texto is None: return ""
    s = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip().lower()


def _parse_mapeo(texto):
    mapeo = {}
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par: continue
        clave, _, val = par.partition("=")
        try: mapeo[_norm(clave)] = int(val.strip())
        except ValueError: continue
    return mapeo or _parse_mapeo(MAPEO_DEFAULT)


def run(gpkg_path, layer_name=None, campo_mat=CAMPO_MATERIAL,
        campo_salida=CAMPO_CF_MATERIAL, mapeo_str=MAPEO_DEFAULT):
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path): print(f"ERROR: No existe '{gpkg_path}'"); sys.exit(1)
    mapeo = _parse_mapeo(mapeo_str)
    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")
    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")
    cols = _columnas(con, tabla)
    c_mat = _campo(cols, campo_mat)
    if not c_mat:
        print(f"ERROR: Campo '{campo_mat}' no encontrado. Disponibles: {cols}"); con.close(); sys.exit(1)
    print(f"  Campo material : {c_mat}")
    print(f"  Campo salida   : {campo_salida}")
    print(f"  Mapeo          : {dict(list(mapeo.items())[:5])}{'...' if len(mapeo) > 5 else ''}")
    if not _campo(cols, campo_salida):
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_salida}" INTEGER')
    filas = con.execute(f'SELECT fid, "{c_mat}", "{campo_salida}" FROM "{tabla}"').fetchall()
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for name, _ in triggers: con.execute(f'DROP TRIGGER IF EXISTS "{name}"')
    actualizadas = 0
    no_reconocidos = set()
    for fid, mat_val, cf_actual in filas:
        clave = _norm(mat_val)
        nueva = mapeo.get(clave, 0)
        if nueva == 0 and mat_val and str(mat_val).strip():
            no_reconocidos.add(str(mat_val).strip())
        if cf_actual != nueva:
            con.execute(f'UPDATE "{tabla}" SET "{campo_salida}"=? WHERE fid=?', (nueva, fid))
            actualizadas += 1
    for _, sql in triggers:
        if sql: con.execute(sql)
    con.commit(); con.close()
    if no_reconocidos:
        print(f"AVISO: Materiales no reconocidos (clase 0): {sorted(no_reconocidos)}")
    print(f"OK. '{campo_salida}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="CF Material standalone")
    p.add_argument("--gpkg", required=True)
    p.add_argument("--layer", default=None)
    p.add_argument("--campo-mat", default=CAMPO_MATERIAL)
    p.add_argument("--campo-salida", default=CAMPO_CF_MATERIAL)
    p.add_argument("--mapeo", default=MAPEO_DEFAULT,
                   help="Ej: 'PVC=3; Hormigon Simple=5' (sin acentos, case-insensitive)")
    a = p.parse_args()
    run(a.gpkg, a.layer, a.campo_mat, a.campo_salida, a.mapeo)

if __name__ == "__main__":
    main()
