"""CfMaterial — delega el calculo en cf_pf_core (paso 'material')."""
from ._base import PasoCoreAlgorithm


class CfMaterial(PasoCoreAlgorithm):
    KEY = "material"
