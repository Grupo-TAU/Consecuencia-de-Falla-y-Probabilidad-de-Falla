"""
CF Acceso para Mantenimiento — CLI sobre cf_pf_core.

El calculo vive en cf_pf_core (paso 'acceso'); este archivo solo lo invoca desde
la linea de comandos. El resultado se escribe en la capa DatosConsecuenciaDeFalla:
la capa de Colectores nunca se modifica.

Las opciones disponibles se derivan del core. Para verlas:
    python scripts\run_cf_acceso_mantenimiento.py --help
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts._cli import main_paso  # noqa: E402

if __name__ == "__main__":
    main_paso("acceso")
