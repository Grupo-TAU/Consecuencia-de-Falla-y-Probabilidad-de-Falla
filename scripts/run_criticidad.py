"""
Criticidad del Tramo - standalone sin QGIS.
Combina los 10 campos CF en un puntaje ponderado entre 1 y 6.

Formula:
    Economico      (30%): CF_Diametro + CF_Profundidad + CF_AccesoMantenimiento + CF_Ubicacion
    Social         (30%): CF_PosicionRelativa + CF_Prox_SitiosInteres + CF_Ubicacion
    Medioambiental (15%): CF_Prox_MedioAmbiental
    Valorizacion   (25%): CF_Antiguedad + CF_Material + CF_Obstrucciones
    Criticidad = SUMA(ponderados) * 6

Uso:
    python scripts\\run_criticidad.py --gpkg <ruta>
"""
import argparse, sqlite3, sys, os

CAMPO_CRITICIDAD = "criticidad"

CAMPOS_REQUERIDOS = {
    "X1_pos_rel":  ("CF_PosicionRelativa",),
    "X2_diam":     ("CF_Diametro",),
    "X3_prof":     ("CF_Profundidad",),
    "X4_medio_amb":("CF_Prox_MedioAmbiental",),
    "X5_sitios":   ("CF_Prox_SitiosInteres", "CF_Prox_ClienteImportante"),
    "X6_antig":    ("CF_Antiguedad",),
    "X7_mat":      ("CF_Material",),
    "X8_obs":      ("CF_Obstrucciones",),
    "X9_acceso":   ("CF_Acceso_Mantenimiento", "CF_AccesoMantenimiento"),
    "X10_ubic":    ("CF_Ubicacion",),
}

PESO_ECONOMICO      = 0.30
PESO_SOCIAL         = 0.30
PESO_MEDIOAMBIENTAL = 0.15
PESO_VALORIZACION   = 0.25
POSIBLE_ECONOMICO      = 24.0
POSIBLE_SOCIAL         = 18.0
POSIBLE_MEDIOAMBIENTAL = 6.0
POSIBLE_VALORIZACION   = 18.0


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


def _cf(v):
    if v is None: return 1.0
    try: return max(1.0, min(6.0, float(v)))
    except (TypeError, ValueError): return 1.0


def run(gpkg_path, layer_name=None, campo_salida=CAMPO_CRITICIDAD):
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path): print(f"ERROR: No existe '{gpkg_path}'"); sys.exit(1)
    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")
    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")
    cols = _columnas(con, tabla)

    campos = {}
    faltantes = []
    for key, candidatos in CAMPOS_REQUERIDOS.items():
        c = _campo(cols, *candidatos)
        if c: campos[key] = c
        else: faltantes.append(key)

    if faltantes:
        print(f"ERROR: Faltan campos requeridos: {faltantes}")
        print(f"Disponibles: {cols}")
        con.close(); sys.exit(1)

    for key, col in campos.items():
        print(f"  {key} -> {col}")
    print(f"  Campo salida: {campo_salida}")

    if not _campo(cols, campo_salida):
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_salida}" REAL')

    sel = ", ".join(f'"{v}"' for v in campos.values())
    filas = con.execute(
        f'SELECT fid, {sel}, "{campo_salida}" FROM "{tabla}"'
    ).fetchall()

    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for name, _ in triggers: con.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    keys = list(campos.keys())
    for row in filas:
        fid = row[0]
        vals = {keys[i]: row[i + 1] for i in range(len(keys))}
        ct_actual = row[-1]

        x1  = _cf(vals["X1_pos_rel"])
        x2  = _cf(vals["X2_diam"])
        x3  = _cf(vals["X3_prof"])
        x4  = _cf(vals["X4_medio_amb"])
        x5  = _cf(vals["X5_sitios"])
        x6  = _cf(vals["X6_antig"])
        x7  = _cf(vals["X7_mat"])
        x8  = _cf(vals["X8_obs"])
        x9  = _cf(vals["X9_acceso"])
        x10 = _cf(vals["X10_ubic"])

        ec   = ((x2 + x3 + x9 + x10) / POSIBLE_ECONOMICO)      * PESO_ECONOMICO
        soc  = ((x1 + x5 + x10)       / POSIBLE_SOCIAL)         * PESO_SOCIAL
        ma   = (x4                     / POSIBLE_MEDIOAMBIENTAL) * PESO_MEDIOAMBIENTAL
        val  = ((x6 + x7 + x8)        / POSIBLE_VALORIZACION)   * PESO_VALORIZACION
        crit = round((ec + soc + ma + val) * 6.0, 2)

        if ct_actual is None or abs(float(ct_actual) - crit) > 1e-9 if ct_actual is not None else True:
            con.execute(
                f'UPDATE "{tabla}" SET "{campo_salida}"=? WHERE fid=?', (crit, fid)
            )
            actualizadas += 1

    for _, sql in triggers:
        if sql: con.execute(sql)
    con.commit(); con.close()
    print(f"OK. '{campo_salida}' actualizado en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="Criticidad standalone")
    p.add_argument("--gpkg", required=True)
    p.add_argument("--layer", default=None)
    p.add_argument("--campo-salida", default=CAMPO_CRITICIDAD)
    a = p.parse_args()
    run(a.gpkg, a.layer, a.campo_salida)

if __name__ == "__main__":
    main()
