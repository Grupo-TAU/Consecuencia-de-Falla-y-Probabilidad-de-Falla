"""
Clase base de los algoritmos de preparacion del plugin.

A diferencia de los de calculo, estos SI escriben las capas reales: completan
campos vacios de Colectores y Registros. Por eso no pasan por GeoDataFrames sino
que le dan a cf_pf_core.preparacion la ruta del GeoPackage, que lo edita in-place
conservando fid, tipos e indices.
"""
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)

from ..core_bridge import log_de, ruta_y_capa

from cf_pf_core import preparacion

COLECTORES = "COLECTORES"
REGISTROS = "REGISTROS"


def _es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


class PreparacionAlgorithm(QgsProcessingAlgorithm):
    """Ejecuta un paso de cf_pf_core.preparacion. Las subclases solo definen KEY."""

    KEY = None
    # Algun paso puede correr sin la capa de Registros (con funcionalidad reducida).
    REGISTROS_OPCIONAL = False

    def _paso(self):
        return preparacion.PASOS_POR_KEY[self.KEY]

    def _campos(self):
        return [*preparacion.CAMPOS_COMUNES, *preparacion.CONFIG_CAMPOS[self.KEY]]

    # ── Metadatos ─────────────────────────────────────────────────────────────

    def name(self):
        return self.KEY

    def displayName(self):
        return self._paso()[1]

    def group(self):
        return "Preparacion de datos"

    def groupId(self):
        return "preparacion_de_datos"

    def createInstance(self):
        return type(self)()

    def shortHelpString(self):
        return (
            f"<strong>{self.displayName()}</strong>\n\n"
            "<strong>Atencion:</strong> este paso ESCRIBE sobre la capa real. "
            "Solo completa campos que esten vacios, nunca pisa lo que ya venia "
            "cargado, y se puede volver a correr sin riesgo.\n\n"
            "Orden recomendado: Asignar Registros -> Cota Zampeado -> Cotas y Pendiente."
        )

    # ── Parametros ────────────────────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                REGISTROS, "Capa Registros", optional=self.REGISTROS_OPCIONAL
            )
        )
        for clave_cfg, etiqueta, default in self._campos():
            if _es_numero(default):
                self.addParameter(
                    QgsProcessingParameterNumber(
                        clave_cfg.upper(), etiqueta,
                        QgsProcessingParameterNumber.Double,
                        defaultValue=float(default), optional=True,
                    )
                )
            else:
                self.addParameter(
                    QgsProcessingParameterString(
                        clave_cfg.upper(), etiqueta,
                        defaultValue=str(default), optional=True,
                    )
                )

    # ── Ejecucion ─────────────────────────────────────────────────────────────

    def _config(self, parameters, context):
        cfg = {}
        for clave_cfg, _etiqueta, default in self._campos():
            nombre = clave_cfg.upper()
            if nombre not in parameters:
                continue
            if _es_numero(default):
                cfg[clave_cfg] = self.parameterAsDouble(parameters, nombre, context)
            else:
                # Se pasa tal cual, incluso vacio: en los campos opcionales el
                # vacio significa "no usar esa columna".
                cfg[clave_cfg] = self.parameterAsString(parameters, nombre, context)
        return cfg

    def processAlgorithm(self, parameters, context, feedback):
        capa_col = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        capa_reg = self.parameterAsVectorLayer(parameters, REGISTROS, context)
        if capa_col is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        gpkg_col, layer_col = ruta_y_capa(capa_col)
        gpkg_reg, layer_reg = ruta_y_capa(capa_reg) if capa_reg else (None, None)

        try:
            resumen = preparacion.correr(
                self.KEY, gpkg_col=gpkg_col, gpkg_reg=gpkg_reg,
                layer_col=layer_col, layer_reg=layer_reg,
                config=self._config(parameters, context), log=log_de(feedback),
            )
        except preparacion.PreparacionError as e:
            raise QgsProcessingException(str(e))

        # Las capas cambiaron en disco: sin reload QGIS sigue mostrando lo viejo.
        for capa in (capa_col, capa_reg):
            if capa is not None:
                capa.reload()

        return {k.upper(): v for k, v in resumen.items()}
