"""ActualizarColectoresLongZampPend — delega en cf_pf_core.preparacion (paso 'colectores_cota_pendiente')."""
from ._base_preparacion import PreparacionAlgorithm


class ActualizarColectoresLongZampPend(PreparacionAlgorithm):
    KEY = "colectores_cota_pendiente"
    REGISTROS_OPCIONAL = True
