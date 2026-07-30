"""AsignarRegistrosColectores — delega en cf_pf_core.preparacion (paso 'asignar_registros')."""
from ._base_preparacion import PreparacionAlgorithm


class AsignarRegistrosColectores(PreparacionAlgorithm):
    KEY = "asignar_registros"
    REGISTROS_OPCIONAL = False
