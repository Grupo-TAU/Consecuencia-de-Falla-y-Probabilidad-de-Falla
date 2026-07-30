"""
Asignar Registro Inicial y Final en Colectores — CLI sobre cf_pf_core.

La logica vive en cf_pf_core.preparacion.asignar_registros; este archivo es solo
la interfaz de linea de comandos.

Uso:
    python scripts\\run_asignar_registros_colectores.py --gpkg-col <ruta> --gpkg-reg <ruta>
    python scripts\\run_asignar_registros_colectores.py \\
        --gpkg-col <ruta> --gpkg-reg <ruta> --tolerancia 0.5
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cf_pf_core.preparacion import PreparacionError, asignar_registros  # noqa: E402
from scripts._cli import log_consola  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Asignar Registros a Colectores")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--gpkg-reg", required=True, help="GeoPackage con Registros")
    p.add_argument("--layer-col", default=None)
    p.add_argument("--layer-reg", default=None)
    p.add_argument("--campo-reg-ini", default=asignar_registros.CAMPO_REG_INI_DEFAULT)
    p.add_argument("--campo-reg-fin", default=asignar_registros.CAMPO_REG_FIN_DEFAULT)
    p.add_argument("--campo-id-reg", default=asignar_registros.CAMPO_ID_REG_DEFAULT)
    p.add_argument("--tolerancia", type=float, default=asignar_registros.TOLERANCIA_DEFAULT,
                   help="Tolerancia geometrica en metros (default 0.5)")
    a = p.parse_args()

    try:
        asignar_registros.ejecutar(
            a.gpkg_col, a.gpkg_reg, a.layer_col, a.layer_reg,
            campo_reg_ini=a.campo_reg_ini, campo_reg_fin=a.campo_reg_fin,
            campo_id_reg=a.campo_id_reg, tolerancia=a.tolerancia,
            log=log_consola)
    except PreparacionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
