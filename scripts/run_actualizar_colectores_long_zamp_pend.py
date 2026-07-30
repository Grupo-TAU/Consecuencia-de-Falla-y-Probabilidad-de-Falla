"""
Completar Cotas y Pendiente en Colectores — CLI sobre cf_pf_core.

La logica vive en cf_pf_core.preparacion.colectores_cota_pendiente; este archivo
es solo la interfaz de linea de comandos.

OJO: a diferencia de la version anterior de este script, la Longitud YA NO se
sobreescribe con la longitud de la geometria. El valor de la intendencia se
respeta; la longitud geometrica solo se usa en memoria, para calcular la
pendiente de los colectores que no la tengan cargada.

Uso:
    python scripts\\run_actualizar_colectores_long_zamp_pend.py --gpkg-col <ruta>
    python scripts\\run_actualizar_colectores_long_zamp_pend.py \\
        --gpkg-col <ruta> --gpkg-reg <ruta>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cf_pf_core.preparacion import PreparacionError, colectores_cota_pendiente as ccp  # noqa: E402
from scripts._cli import log_consola  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Completar Cotas y Pendiente en Colectores")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--gpkg-reg", default=None,
                   help="GeoPackage con Registros para copiar cotas (opcional)")
    p.add_argument("--layer-col", default=None)
    p.add_argument("--layer-reg", default=None)
    p.add_argument("--campo-longitud", default=ccp.CAMPO_LONGITUD_DEFAULT,
                   help="Columna de longitud (solo se lee, nunca se escribe)")
    p.add_argument("--campo-reg-ini", default=ccp.CAMPO_REG_INI_DEFAULT)
    p.add_argument("--campo-reg-fin", default=ccp.CAMPO_REG_FIN_DEFAULT)
    p.add_argument("--campo-cota-ini", default=ccp.CAMPO_COTA_INI_DEFAULT)
    p.add_argument("--campo-cota-fin", default=ccp.CAMPO_COTA_FIN_DEFAULT)
    p.add_argument("--campo-pendiente", default=ccp.CAMPO_PENDIENTE_DEFAULT)
    p.add_argument("--campo-prof-salto", default=ccp.CAMPO_PROF_SALTO_DEFAULT,
                   help="Vacio para desactivar el ajuste por salto")
    p.add_argument("--campo-id-reg", default=ccp.CAMPO_ID_REG_DEFAULT)
    p.add_argument("--campo-cota-zamp", default=ccp.CAMPO_COTA_ZAMP_DEFAULT)
    p.add_argument("--campo-prof-inspec", default=ccp.CAMPO_PROF_INSPEC_DEFAULT)
    a = p.parse_args()

    try:
        ccp.ejecutar(
            a.gpkg_col, a.gpkg_reg, a.layer_col, a.layer_reg,
            campo_longitud=a.campo_longitud, campo_reg_ini=a.campo_reg_ini,
            campo_reg_fin=a.campo_reg_fin, campo_cota_ini=a.campo_cota_ini,
            campo_cota_fin=a.campo_cota_fin, campo_pendiente=a.campo_pendiente,
            campo_prof_salto=a.campo_prof_salto, campo_id_reg=a.campo_id_reg,
            campo_cota_zamp=a.campo_cota_zamp, campo_prof_inspec=a.campo_prof_inspec,
            log=log_consola)
    except PreparacionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
