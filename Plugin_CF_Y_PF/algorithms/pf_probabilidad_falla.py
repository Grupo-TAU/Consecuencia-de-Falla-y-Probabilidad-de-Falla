"""PfProbabilidadFalla — delega el calculo en cf_pf_core (paso 'pf')."""
from ._base import PasoCoreAlgorithm


class PfProbabilidadFalla(PasoCoreAlgorithm):
    KEY = "pf"
