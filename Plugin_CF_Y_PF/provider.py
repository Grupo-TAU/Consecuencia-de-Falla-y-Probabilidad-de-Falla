"""
Provider de Processing: registra los algoritmos del plugin en QGIS.

Los algoritmos aparecen en la caja de herramientas en dos grupos (el grupo lo
declara cada algoritmo, no este archivo):

  - Preparacion de datos  -> ESCRIBEN las capas reales de Colectores/Registros.
  - Consecuencia de Falla -> calculan y escriben en la capa de resultados; aca
    tambien vive Aplicar Simbologia, que pinta esa capa.

El orden de registro es el mismo que el de cf_pf_core (preparacion.PASOS y
flujo.PASOS), asi que si el core gana un paso nuevo, aca se agrega una linea.
"""
from qgis.core import QgsProcessingProvider

# Preparacion de datos (cf_pf_core.preparacion.PASOS, en orden)
from .algorithms.asignar_registros_colectores import AsignarRegistrosColectores
from .algorithms.actualizar_registros_cota_zampeado import ActualizarRegistrosCotaZampeado
from .algorithms.actualizar_colectores_long_zamp_pend import ActualizarColectoresLongZampPend

# Calculo (cf_pf_core.flujo.PASOS, en orden)
from .algorithms.flujo_completo import FlujoCompleto
from .algorithms.cf_diametro import CfDiametro
from .algorithms.cf_posicion_relativa import CfPosicionRelativa
from .algorithms.cf_profundidad import CfProfundidad
from .algorithms.cf_prox_sitios_interes import CfProxSitiosInteres
from .algorithms.cf_prox_cursos_agua import CfProxCursosAgua
from .algorithms.cf_antiguedad import CfAntiguedad
from .algorithms.cf_material import CfMaterial
from .algorithms.cf_acceso_mantenimiento import CfAccesoMantenimiento
from .algorithms.cf_ubicacion import CfUbicacion
from .algorithms.cf_obstrucciones import CfObstrucciones
from .algorithms.pf_probabilidad_falla import PfProbabilidadFalla
from .algorithms.criticidad import Criticidad
from .algorithms.riesgo_calculo import RiesgoCalculo

# Simbologia de la capa de resultados
from .algorithms.aplicar_simbologia import AplicarSimbologia


ALGORITMOS = [
    # Preparacion de datos
    AsignarRegistrosColectores,
    ActualizarRegistrosCotaZampeado,
    ActualizarColectoresLongZampPend,
    # Calculo
    FlujoCompleto,
    CfDiametro,
    CfPosicionRelativa,
    CfProfundidad,
    CfProxSitiosInteres,
    CfProxCursosAgua,
    CfAntiguedad,
    CfMaterial,
    CfAccesoMantenimiento,
    CfUbicacion,
    CfObstrucciones,
    PfProbabilidadFalla,
    Criticidad,
    RiesgoCalculo,
    # Simbologia
    AplicarSimbologia,
]


class ColectoresRiesgoProvider(QgsProcessingProvider):

    def loadAlgorithms(self):
        for algoritmo in ALGORITMOS:
            self.addAlgorithm(algoritmo())

    def id(self):
        return "colectores_riesgo"

    def name(self):
        return "Consecuencia de Falla y Probabilidad de Falla"

    def longName(self):
        return ("Consecuencia de Falla y Probabilidad de Falla - Clasificacion y "
                "riesgo de red de colectores")
