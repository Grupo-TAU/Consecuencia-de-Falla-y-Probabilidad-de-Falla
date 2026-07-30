"""
Plumbing compartido por los scripts run_*.

Los scripts son cascaras: toda la logica vive en cf_pf_core. Aca esta lo unico
que es propio de la linea de comandos (parseo de argumentos, lectura de capas,
impresion del log).

Las opciones de configuracion de cada calculo NO se listan a mano: se derivan de
cf_pf_core.flujo.CONFIG_CAMPOS. Si el core gana un parametro nuevo, el script lo
expone solo — que es justamente el drift que este refactor viene a matar.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cf_pf_core import flujo, gpkg_io  # noqa: E402

# Alias corto de flag, por compatibilidad con los scripts viejos.
ALIAS_ROL = {
    "registros": ["--gpkg-reg"],
    "construcciones": ["--gpkg-constr"],
    "asentamientos": ["--gpkg-asent"],
    "padrones": ["--gpkg-pad"],
    "peatonales": ["--gpkg-peat"],
}

_PREFIJOS = {"ok": "OK. ", "warn": "AVISO: ", "error": "ERROR: "}


def _tolerar_acentos():
    """Evita que la consola cp1252 de Windows corte la corrida.

    Los nombres de capa, de campo y las etiquetas de los pasos llevan acentos.
    Con errors='replace' se degradan a '?' en vez de lanzar UnicodeEncodeError,
    y cubre todo lo que se imprima: prints, argparse y tracebacks.
    """
    for flujo_salida in (sys.stdout, sys.stderr):
        try:
            flujo_salida.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


_tolerar_acentos()


def log_consola(msg, nivel="info"):
    """Callback de log de los pasos del core, impreso a stdout."""
    print(_PREFIJOS.get(nivel, "") + msg)


def _flag(clave):
    return "--" + clave.replace("_", "-")


def salida_por_defecto(gpkg_col):
    """<carpeta de colectores>/<nombre>_ConsecuenciaDeFalla.gpkg"""
    base = os.path.splitext(os.path.basename(gpkg_col))[0]
    return os.path.join(os.path.dirname(os.path.abspath(gpkg_col)),
                        f"{base}_ConsecuenciaDeFalla.gpkg")


def construir_parser(key):
    _k, label, requiere, _fn = flujo.PASOS_POR_KEY[key]
    p = argparse.ArgumentParser(
        description=f"{label} — calculado por cf_pf_core, escrito en la capa "
                    f"{gpkg_io.LAYER_SALIDA_DEFAULT} (la capa fuente no se toca).")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg", required=True,
                   help="GeoPackage con Colectores (solo se lee)")
    p.add_argument("--layer", "--layer-col", dest="layer", default=None)

    for rol in flujo.roles_usados(key):
        obligatorio = " (requerido)" if rol in requiere else " (opcional)"
        p.add_argument(f"--gpkg-{rol}", *ALIAS_ROL.get(rol, []), dest=f"gpkg_{rol}",
                       default=None, help=f"GeoPackage de la capa {rol}{obligatorio}")
        p.add_argument(f"--layer-{rol}", dest=f"layer_{rol}", default=None)

    p.add_argument("--out", default=None,
                   help="GeoPackage de salida (default: junto a Colectores)")
    p.add_argument("--out-layer", default=gpkg_io.LAYER_SALIDA_DEFAULT)
    p.add_argument("--clave", default=None,
                   help="Columna de join (default: ELEMRED o ID, lo que exista)")

    for ckey, etiqueta, default in flujo.campos_config(key):
        p.add_argument(_flag(ckey), dest=f"cfg_{ckey}", default=None,
                       help=f"{etiqueta} (default: {default})")
    return p


def correr_paso(key, argv=None):
    """Corre un paso de calculo desde la linea de comandos. Devuelve el exit code."""
    if key not in flujo.PASOS_POR_KEY:
        print(f"ERROR: paso desconocido '{key}'")
        return 1

    args = construir_parser(key).parse_args(argv)
    _k, label, requiere, _fn = flujo.PASOS_POR_KEY[key]

    try:
        colectores = gpkg_io.leer_capa(args.gpkg, args.layer)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    registros, aux = None, {}
    for rol in flujo.roles_usados(key):
        ruta = getattr(args, f"gpkg_{rol}")
        if not ruta:
            if rol in requiere:
                print(f"ERROR: {label} necesita la capa '{rol}'. Pasa --gpkg-{rol}.")
                return 1
            continue
        try:
            gdf = gpkg_io.leer_capa(ruta, getattr(args, f"layer_{rol}"))
        except ValueError as e:
            print(f"ERROR: al leer '{rol}': {e}")
            return 1
        if rol == "registros":
            registros = gdf
        else:
            aux[rol] = gdf

    config = {c: v for c, v in
              ((k[4:], getattr(args, k)) for k in vars(args) if k.startswith("cfg_"))
              if v is not None}

    salida = args.out or salida_por_defecto(args.gpkg)
    # Los pasos que combinan CF ya calculados (criticidad, riesgo) necesitan ver
    # lo que dejaron las corridas anteriores.
    base = None
    if gpkg_io.capa_existe(salida, args.out_layer):
        base = gpkg_io.leer_capa(salida, args.out_layer)

    log_consola(f"Colectores: {len(colectores)} filas, CRS {colectores.crs}")
    res = flujo.correr(colectores, registros=registros, aux=aux, config=config,
                       clave=args.clave, solo=[key], log=log_consola, base=base)

    clave = flujo.resolver_clave(colectores, args.clave)
    gpkg_io.escribir_resultados(res, salida, args.out_layer, clave=clave)
    log_consola(f"Escrito en {salida} (capa {args.out_layer}).", "ok")
    return 0


def main_paso(key):
    """Punto de entrada de los scripts run_*."""
    sys.exit(correr_paso(key))
