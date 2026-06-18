"""
Script standalone para ejecutar CF Obstrucciones.
No requiere QGIS ni librerias externas: usa sqlite3 (incluido en Python).

Uso:
    python scripts\\run_cf_obstrucciones.py --gpkg <ruta_al_gpkg>
    python scripts\\run_cf_obstrucciones.py --gpkg <ruta_al_gpkg> --layer <nombre_capa>

Ejemplo (Arteaga):
    python scripts\\run_cf_obstrucciones.py ^
        --gpkg "G:\\Unidades compartidas\\GRUPO TAU\\INTENDENCIA DE MONTEVIDEO\\12-ARTEAGA\\02-EN PROCESO\\Prueba Arteaga\\vsstramoarteaga_prueba.gpkg"

Clasificacion:
    0 obstrucciones  ->  1 (Baja)
    1 obstruccion    ->  3 (Media)
    >= 2             ->  6 (Alta)
    Sin dato         ->  1 (Baja)
"""

import argparse
import sqlite3
import sys
import os

CAMPO_CF_OBSTRUCCIONES = "CF_Obstrucciones"
CAMPO_OBSTRUCCIONES    = "Obstrucciones"


def _clasificar(valor):
    if valor is None:
        return 1
    try:
        obs = int(float(valor))
    except (TypeError, ValueError):
        return 1
    if obs == 0:
        return 1
    if obs == 1:
        return 3
    return 6


def _detectar_capa(con, layer_name):
    """Retorna el nombre de la tabla de features a usar."""
    filas = con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type = 'features'"
    ).fetchall()
    capas = [f[0] for f in filas]

    if not capas:
        print("ERROR: El GeoPackage no contiene capas de features.")
        sys.exit(1)

    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: La capa '{layer_name}' no existe.")
            print(f"Capas disponibles: {capas}")
            sys.exit(1)
        return layer_name

    if len(capas) == 1:
        return capas[0]

    print(f"El GeoPackage tiene varias capas: {capas}")
    print("Especifica una con --layer <nombre_capa>")
    sys.exit(1)


def _columnas(con, tabla):
    return [row[1] for row in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _buscar_campo(columnas, nombre):
    """Busqueda case-insensitive."""
    for col in columnas:
        if col.lower() == nombre.lower():
            return col
    return None


def run(gpkg_path, layer_name=None, campo_obs=CAMPO_OBSTRUCCIONES, campo_salida=CAMPO_CF_OBSTRUCCIONES):
    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path):
        print(f"ERROR: No se encontro el archivo '{gpkg_path}'")
        sys.exit(1)

    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")

    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")

    columnas = _columnas(con, tabla)

    campo_obs_real = _buscar_campo(columnas, campo_obs)
    if campo_obs_real is None:
        print(f"ERROR: No se encontro el campo '{campo_obs}'.")
        print(f"Campos disponibles: {columnas}")
        con.close()
        sys.exit(1)

    print(f"  Campo obstrucciones : {campo_obs_real}")
    print(f"  Campo salida        : {campo_salida}")

    # Crear columna de salida si no existe
    if _buscar_campo(columnas, campo_salida) is None:
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_salida}" INTEGER')
        print(f"  Columna '{campo_salida}' creada.")

    # Leer todos los registros
    filas = con.execute(
        f'SELECT fid, "{campo_obs_real}", "{campo_salida}" FROM "{tabla}"'
    ).fetchall()
    total = len(filas)
    print(f"  Features: {total}")

    # Los GeoPackages tienen triggers de validacion de geometria que usan
    # funciones de SpatiaLite (ST_IsEmpty) no disponibles en sqlite3 puro.
    # Se desactivan antes del UPDATE y se recrean al terminar.
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (tabla,),
    ).fetchall()
    for name, _ in triggers:
        con.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for fid, obs_val, cf_actual in filas:
        nueva_clase = _clasificar(obs_val)
        if cf_actual != nueva_clase:
            con.execute(
                f'UPDATE "{tabla}" SET "{campo_salida}" = ? WHERE fid = ?',
                (nueva_clase, fid),
            )
            actualizadas += 1

    # Recrear triggers
    for _, sql in triggers:
        if sql:
            con.execute(sql)

    con.commit()
    con.close()

    print(f"OK. '{campo_salida}' actualizado en {actualizadas}/{total} colectores.")
    return actualizadas


def main():
    parser = argparse.ArgumentParser(
        description="CF Obstrucciones - standalone sin QGIS (usa sqlite3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--gpkg", required=True,
                        help="Ruta al GeoPackage de colectores")
    parser.add_argument("--layer", default=None,
                        help="Nombre de la capa en el GeoPackage (auto si hay una sola)")
    parser.add_argument("--campo-obs", default=CAMPO_OBSTRUCCIONES,
                        help=f"Campo de obstrucciones (default: {CAMPO_OBSTRUCCIONES})")
    parser.add_argument("--campo-salida", default=CAMPO_CF_OBSTRUCCIONES,
                        help=f"Campo de salida (default: {CAMPO_CF_OBSTRUCCIONES})")
    args = parser.parse_args()

    run(
        gpkg_path=args.gpkg,
        layer_name=args.layer,
        campo_obs=args.campo_obs,
        campo_salida=args.campo_salida,
    )


if __name__ == "__main__":
    main()
