"""CfPosicionRelativa — delega el calculo en cf_pf_core (paso 'posicion_relativa')."""
from ._base import PasoCoreAlgorithm


class CfPosicionRelativa(PasoCoreAlgorithm):
    KEY = "posicion_relativa"
