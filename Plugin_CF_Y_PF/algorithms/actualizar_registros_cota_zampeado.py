"""ActualizarRegistrosCotaZampeado — delega en cf_pf_core.preparacion (paso 'cota_zampeado')."""
from ._base_preparacion import PreparacionAlgorithm


class ActualizarRegistrosCotaZampeado(PreparacionAlgorithm):
    KEY = "cota_zampeado"
    REGISTROS_OPCIONAL = True
