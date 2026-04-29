from qgis.core import QgsProcessingProvider

from .algorithms.cf_diametro import CfDiametro
from .algorithms.cf_profundidad import CfProfundidad
from .algorithms.flujo_completo import FlujoCompleto
from .algorithms.cf_posicion_relativa import CfPosicionRelativa
from .algorithms.cf_prox_cliente_importante import CfProxClienteImportante as CfProxCliente
from .algorithms.cf_prox_medio_ambiental import CfProxMedioAmbiental
from .algorithms.cf_total import CfTotal
from .algorithms.pf_probabilidad_falla import PfProbabilidadFalla as Pf
from .algorithms.riesgo_calculo import RiesgoCalculo as Riesgo
from .algorithms.actualizar_colectores_long_zamp_pend import ActualizarColectoresLongZampPend as ActualizarColectores
from .algorithms.aplicar_simbologia import AplicarSimbologia
from .algorithms.cf_antiguedad import CfAntiguedad
from .algorithms.cf_material import CfMaterial


class ColectoresRiesgoProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        self.addAlgorithm(CfDiametro())
        self.addAlgorithm(CfProfundidad())
        self.addAlgorithm(FlujoCompleto())
        self.addAlgorithm(CfPosicionRelativa())
        self.addAlgorithm(CfProxCliente())
        self.addAlgorithm(CfProxMedioAmbiental())
        self.addAlgorithm(CfTotal())
        self.addAlgorithm(Pf())
        self.addAlgorithm(Riesgo())
        self.addAlgorithm(ActualizarColectores())
        self.addAlgorithm(AplicarSimbologia())
        self.addAlgorithm(CfAntiguedad())
        self.addAlgorithm(CfMaterial())

    def id(self):
        return "colectores_riesgo"

    def name(self):
        return "Colectores Riesgo"

    def longName(self):
        return "Colectores Riesgo - Clasificacion y riesgo de red cloacal"
