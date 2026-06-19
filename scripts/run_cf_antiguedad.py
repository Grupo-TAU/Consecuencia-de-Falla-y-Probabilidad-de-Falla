"""
Script standalone para ejecutar CF Antiguedad.
No requiere QGIS ni librerias externas: usa sqlite3 (incluido en Python).

Uso:
    python scripts\\run_cf_antiguedad.py --gpkg <ruta_al_gpkg>
    python scripts\\run_cf_antiguedad.py --gpkg <ruta_al_gpkg> --layer <nombre_capa>

Ejemplo (Arteaga):
    python scripts\\run_cf_antiguedad.py --gpkg "G:\\Unidades compartidas\\GRUPO TAU\\INTENDENCIA DE MONTEVIDEO\\12-ARTEAGA\\02-EN PROCESO\\Prueba Arteaga\\vsstramoarteaga_prueba.gpkg"

Clasificacion por defecto (configurable con --limites y --clases):
    0-10 anos   ->  1
    11-20 anos  ->  2
    21-30 anos  ->  3
    31-50 anos  ->  4
    > 50 anos   ->  6
    Sin dato    ->  0
"""

import argparse
import re
import sqlite3
import sys
import os

CAMPO_CF_ANTIGUEDAD = "CF_Antiguedad"
CAMPO_EDAD          = "Antiguedad"
LIMITES_DEFAULT     = [10, 20, 30, 50]
CLASES_DEFAULT      = [1, 2, 3, 4, 6]


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_enteros(texto, defaults):
    if not texto or not str(texto).strip():
        return list(defaults)
    numeros = re.findall(r"\d+", str(texto))
    if not numeros:
        return list(defaults)
    return [int(n) for n in numeros]


def _clasificar(edad, limites, clases):
    for limite, clase in zip(limites, clases):
        if edad <= limite:
            return clase
    return clases[-1]


def _detectar_capa(con, layer_name):
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
    for col in columnas:
        if col.lower() == nombre.lower():
            return col
    return None


def run(gpkg_path, layer_name=None, campo_edad=CAMPO_EDAD, campo_salida=CAMPO_CF_ANTIGUEDAD,
        limites=None, clases=None):
    if limites is None:
        limites = LIMITES_DEFAULT
    if clases is None:
        clases = CLASES_DEFAULT

    if len(clases) != len(limites) + 1:
        print(f"ERROR: La cantidad de clases ({len(clases)}) debe ser exactamente "
              f"uno mas que la cantidad de limites ({len(limites)}).")
        sys.exit(1)

    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path):
        print(f"ERROR: No se encontro el archivo '{gpkg_path}'")
        sys.exit(1)

    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")

    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")

    columnas = _columnas(con, tabla)

    campo_edad_real = _buscar_campo(columnas, campo_edad)
    if campo_edad_real is None:
        print(f"ERROR: No se encontro el campo '{campo_edad}'.")
        print(f"Campos disponibles: {columnas}")
        con.close()
        sys.exit(1)

    print(f"  Campo antiguedad : {campo_edad_real}")
    print(f"  Campo salida     : {campo_salida}")
    print(f"  Limites (anos)   : {limites}")
    print(f"  Clases           : {clases}")

    # Crear columna de salida si no existe
    if _buscar_campo(columnas, campo_salida) is None:
        con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_salida}" INTEGER')
        print(f"  Columna '{campo_salida}' creada.")

    # Leer registros
    filas = con.execute(
        f'SELECT fid, "{campo_edad_real}", "{campo_salida}" FROM "{tabla}"'
    ).fetchall()
    total = len(filas)
    print(f"  Features: {total}")

    # Desactivar triggers de validacion de geometria (usan ST_IsEmpty de SpatiaLite)
    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (tabla,),
    ).fetchall()
    for name, _ in triggers:
        con.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for fid, edad_val, cf_actual in filas:
        edad = _to_float_or_none(edad_val)
        nueva_clase = _clasificar(edad, limites, clases) if edad is not None else 0
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
        description="CF Antiguedad - standalone sin QGIS (usa sqlite3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--gpkg", required=True,
                        help="Ruta al GeoPackage de colectores")
    parser.add_argument("--layer", default=None,
                        help="Nombre de la capa en el GeoPackage (auto si hay una sola)")
    parser.add_argument("--campo-edad", default=CAMPO_EDAD,
                        help=f"Campo de antiguedad en anos (default: {CAMPO_EDAD})")
    parser.add_argument("--campo-salida", default=CAMPO_CF_ANTIGUEDAD,
                        help=f"Campo de salida (default: {CAMPO_CF_ANTIGUEDAD})")
    parser.add_argument("--limites", default=None,
                        help=f"Limites de edad separados por coma (default: {LIMITES_DEFAULT})")
    parser.add_argument("--clases", default=None,
                        help=f"Clases por tramo separadas por coma (default: {CLASES_DEFAULT})")
    args = parser.parse_args()

    limites = _parse_enteros(args.limites, LIMITES_DEFAULT)
    clases  = _parse_enteros(args.clases,  CLASES_DEFAULT)

    run(
        gpkg_path=args.gpkg,
        layer_name=args.layer,
        campo_edad=args.campo_edad,
        campo_salida=args.campo_salida,
        limites=limites,
        clases=clases,
    )


if __name__ == "__main__":
    main()
