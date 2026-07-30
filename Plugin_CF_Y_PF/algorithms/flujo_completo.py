"""Flujo completo — corre todos los pasos de cf_pf_core.flujo de una pasada."""
from qgis.core import QgsProcessingParameterBoolean

from ._base import COLECTORES, PasoCoreAlgorithm
from ..core_bridge import log_de, ruta_y_capa

from cf_pf_core import flujo, gpkg_io, preparacion

PREPARACION = "CORRER_PREPARACION"
REGISTROS = "REGISTROS"


class FlujoCompleto(PasoCoreAlgorithm):
    # KEY = None: la clase base interpreta que abarca todos los pasos de calculo.
    KEY = None

    def name(self):
        return "flujo_completo"

    def displayName(self):
        return "Flujo Completo"

    def shortHelpString(self):
        pasos = "\n".join(f"  - {label}" for _k, label, _r, _f in flujo.PASOS)
        preps = "\n".join(f"  - {label}" for _k, label, _fn, _c in preparacion.PASOS)
        return (
            "<strong>Corre todo el analisis de una sola vez.</strong>\n\n"
            f"Pasos de calculo, en orden:\n{pasos}\n\n"
            "Los pasos que necesiten una capa que no indicaste se omiten y quedan "
            "avisados en el log; el resto igual se calcula.\n\n"
            f"El resultado va a la capa <strong>{gpkg_io.LAYER_SALIDA_DEFAULT}</strong> "
            "de un GeoPackage aparte, que se reescribe entera. La capa de Colectores "
            "no se modifica.\n\n"
            "<strong>Preparacion de datos (opcional, desactivada por defecto):</strong>\n"
            f"{preps}\n"
            "Estos SI escriben las capas reales de Colectores y Registros: completan "
            "los campos vacios que despues usan los calculos. Activalos solo si hace "
            "falta y tenes respaldo."
        )

    def initAlgorithm(self, config=None):
        super().initAlgorithm(config)
        self.addParameter(
            QgsProcessingParameterBoolean(
                PREPARACION,
                "Correr antes la preparacion de datos (ESCRIBE Colectores y Registros)",
                defaultValue=False,
            )
        )

    def _antes_de_leer(self, parameters, context, feedback):
        """Corre la preparacion antes de leer las capas.

        Tiene que ser antes: la preparacion recalcula la Pendiente y las cotas, y
        CF Posicion Relativa se calcula justamente sobre la pendiente. Corriendola
        despues, los CF saldrian con los valores viejos.
        """
        if not self.parameterAsBool(parameters, PREPARACION, context):
            return

        log = log_de(feedback)
        capa_col = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        capa_reg = self.parameterAsVectorLayer(parameters, REGISTROS, context)

        gpkg_col, layer_col = ruta_y_capa(capa_col)
        gpkg_reg, layer_reg = ruta_y_capa(capa_reg) if capa_reg else (None, None)

        feedback.pushInfo("=== Preparacion de datos (escribe las capas reales) ===")
        for key, etiqueta, _fn, _campos in preparacion.PASOS:
            if feedback.isCanceled():
                return
            feedback.pushInfo(f"-- {etiqueta}")
            try:
                preparacion.correr(key, gpkg_col=gpkg_col, gpkg_reg=gpkg_reg,
                                   layer_col=layer_col, layer_reg=layer_reg, log=log)
            except preparacion.PreparacionError as e:
                # Que un paso de preparacion no aplique no deberia frenar el calculo.
                feedback.pushWarning(f"{etiqueta}: se omite - {e}")

        # Las capas quedaron modificadas en disco: QGIS tiene que releerlas.
        for capa in (capa_col, capa_reg):
            if capa is not None:
                capa.reload()
        feedback.pushInfo("=== Fin de la preparacion ===")
