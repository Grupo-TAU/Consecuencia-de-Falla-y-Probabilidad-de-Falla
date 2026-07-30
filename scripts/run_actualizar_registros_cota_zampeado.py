"""
Actualizar Cota Zampeado en Registros — CLI sobre cf_pf_core.

La logica vive en cf_pf_core.preparacion.cota_zampeado; este archivo es solo la
interfaz de linea de comandos.

Uso:
    python scripts\\run_actualizar_registros_cota_zampeado.py --gpkg-reg <ruta>
    python scripts\\run_actualizar_registros_cota_zampeado.py \\
        --gpkg-reg <ruta> --gpkg-col <ruta>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cf_pf_core.preparacion import PreparacionError, cota_zampeado  # noqa: E402
from scripts._cli import log_consola  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Actualizar Cota Zampeado en Registros")
    p.add_argument("--gpkg", "--gpkg-reg", dest="gpkg_reg", required=True,
                   help="GeoPackage con Registros")
    p.add_argument("--gpkg-col", default=None,
                   help="GeoPackage con Colectores (requerido para la Mecanica 2)")
    p.add_argument("--layer-reg", default=None)
    p.add_argument("--layer-col", default=None)
    p.add_argument("--campo-cota-zamp", default=cota_zampeado.CAMPO_COTA_ZAMP_DEFAULT)
    p.add_argument("--campo-cota-tapa", default=cota_zampeado.CAMPO_COTA_TAPA_DEFAULT)
    p.add_argument("--campo-prof-inspec", default=cota_zampeado.CAMPO_PROF_INSPEC_DEFAULT)
    p.add_argument("--campo-id-reg", default=cota_zampeado.CAMPO_ID_REG_DEFAULT)
    p.add_argument("--campo-zarriba", default=cota_zampeado.CAMPO_ZARRIBA_DEFAULT)
    p.add_argument("--campo-reg-ini-col", dest="campo_reg_ini",
                   default=cota_zampeado.CAMPO_REG_INI_DEFAULT)
    a = p.parse_args()

    try:
        cota_zampeado.ejecutar(
            a.gpkg_col, a.gpkg_reg, a.layer_col, a.layer_reg,
            campo_cota_zamp=a.campo_cota_zamp, campo_cota_tapa=a.campo_cota_tapa,
            campo_prof_inspec=a.campo_prof_inspec, campo_id_reg=a.campo_id_reg,
            campo_zarriba=a.campo_zarriba, campo_reg_ini=a.campo_reg_ini,
            log=log_consola)
    except PreparacionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
