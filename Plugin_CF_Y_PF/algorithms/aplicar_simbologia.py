from qgis.core import (
    QgsRuleBasedRenderer,
    QgsLineSymbol,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterString,
    QgsProcessingOutputNumber,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
)
from qgis.PyQt.QtGui import QColor, QFont

# Importar core_bridge deja cf_pf_core importable (resuelve el core vendorizado).
from .. import core_bridge  # noqa: F401

from cf_pf_core import gpkg_io
from cf_pf_core.calculos import criticidad

# Prefijo que identifica las reglas gestionadas por este algoritmo.
# Las reglas del usuario que NO tengan este prefijo nunca se tocan.
_PREFIJO = "[AUTO] "

# (expresion, color, etiqueta_sin_prefijo)
RANGOS = [
    ('"Criticidad" >= 0 AND "Criticidad" <= 1', QColor("#2CA02C"), "<= 1 - Verde"),
    ('"Criticidad" >  1 AND "Criticidad" <= 2', QColor("#98DF8A"), "<= 2 - Verde claro"),
    ('"Criticidad" >  2 AND "Criticidad" <= 3', QColor("#FFFF00"), "<= 3 - Amarillo"),
    ('"Criticidad" >  3 AND "Criticidad" <= 4', QColor("#FFBB78"), "<= 4 - Naranjo claro"),
    ('"Criticidad" >  4 AND "Criticidad" <= 5', QColor("#FF7F0E"), "<= 5 - Naranjo"),
    ('"Criticidad" >  5 AND "Criticidad" <= 6', QColor("#D62728"), "<= 6 - Rojo"),
]

RESULTADOS = "RESULTADOS"
CAMPO      = "CAMPO"
OUTPUT_OK  = "SIMBOLOGIA_OK"



def _construir_expresion(campo, expr_base):
    """Reemplaza 'Criticidad' por el campo elegido por el usuario."""
    return expr_base.replace('"Criticidad"', f'"{campo}"')


class AplicarSimbologia(QgsProcessingAlgorithm):
    """
    Aplica simbologia basada en reglas (1-6) a la capa de resultados.
    Las reglas automaticas se actualizan en cada ejecucion;
    las reglas agregadas manualmente por el usuario se preservan.
    """

    def name(self):
        return "aplicar_simbologia"

    def displayName(self):
        return "Aplicar Simbologia (1-6)"

    def group(self):
        return "Consecuencia de Falla"

    def groupId(self):
        return "consecuencia_de_falla"

    def shortHelpString(self):
        return (
            f"Aplica simbologia por Criticidad del tramo a la capa de resultados "
            f"(<strong>{gpkg_io.LAYER_SALIDA_DEFAULT}</strong>), la que generan los "
            "algoritmos de calculo.\n\n"
            "Las reglas que agregues manualmente en QGIS se conservan: solo se "
            "regeneran las que llevan el prefijo [AUTO].\n\n"
            "Rangos:\n\n"
            "<=1 = Verde\n\n"
            "<=2 = Verde claro\n\n"
            "<=3 = Amarillo\n\n"
            "<=4 = Naranjo claro\n\n"
            "<=5 = Naranjo\n\n"
            "<=6 = Rojo"
        )

    def createInstance(self):
        return AplicarSimbologia()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                RESULTADOS,
                f"Capa de resultados ({gpkg_io.LAYER_SALIDA_DEFAULT})",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                CAMPO,
                "Campo a simbolizar",
                defaultValue=criticidad.CAMPO_SALIDA_DEFAULT,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_OK, "1 si la simbologia se aplico correctamente")
        )

    def processAlgorithm(self, parameters, context, feedback):
        capa = self.parameterAsVectorLayer(parameters, RESULTADOS, context)
        if capa is None:
            raise QgsProcessingException("No se pudo leer la capa de resultados.")

        campo = self.parameterAsString(parameters, CAMPO, context)
        if not campo:
            raise QgsProcessingException("Debe especificar el campo de clasificacion.")
        if capa.fields().lookupField(campo) == -1:
            disponibles = ", ".join(f.name() for f in capa.fields())
            raise QgsProcessingException(
                f"El campo '{campo}' no existe en '{capa.name()}'. "
                f"Campos disponibles: {disponibles}.\n"
                f"Recorda que los resultados se calculan en la capa "
                f"{gpkg_io.LAYER_SALIDA_DEFAULT}, no en Colectores: corre primero el "
                "algoritmo de Criticidad (o el Flujo Completo)."
            )

        ancho = "1.4"

        # ── Clonar reglas manuales del usuario ANTES de tocar el renderer ────
        renderer_actual = capa.renderer()
        if isinstance(renderer_actual, QgsRuleBasedRenderer):
            # .clone() crea copias independientes; no dependen del renderer viejo
            reglas_usuario = [
                hijo.clone()
                for hijo in renderer_actual.rootRule().children()
                if not hijo.label().startswith(_PREFIJO)
            ]
            feedback.pushInfo(
                f"Renderer basado en reglas existente: se preservan "
                f"{len(reglas_usuario)} regla(s) del usuario."
            )
        else:
            reglas_usuario = []
            feedback.pushInfo("Se crea un nuevo renderer basado en reglas.")

        # ── Construir raiz nueva (nunca reutilizar la del renderer viejo) ─────
        regla_raiz = QgsRuleBasedRenderer.Rule(None)

        # Primero las reglas AUTO
        for expr_base, color, etiqueta in RANGOS:
            expr    = _construir_expresion(campo, expr_base)
            simbolo = QgsLineSymbol.createSimple({"color": color.name(), "width": ancho})
            regla   = QgsRuleBasedRenderer.Rule(simbolo)
            regla.setFilterExpression(expr)
            regla.setLabel(_PREFIJO + etiqueta)
            regla_raiz.appendChild(regla)

        # Despues las reglas manuales del usuario (ya clonadas)
        for regla in reglas_usuario:
            regla_raiz.appendChild(regla)

        capa.setRenderer(QgsRuleBasedRenderer(regla_raiz))

        # ── Etiquetas de mapa ──────────────────────────────────────────────────
        pal           = QgsPalLayerSettings()
        pal.fieldName = campo
        pal.enabled   = True
        fmt           = QgsTextFormat()
        fmt.setFont(QFont("Arial", 8))
        fmt.setSize(8)
        fmt.setColor(QColor("black"))
        pal.setFormat(fmt)
        pal.placement = QgsPalLayerSettings.Line

        capa.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        capa.setLabelsEnabled(True)
        capa.triggerRepaint()

        feedback.pushInfo(f"Simbologia basada en reglas aplicada al campo '{campo}'.")
        feedback.pushInfo(f"Ancho de linea: {ancho}")
        feedback.pushInfo("Etiquetas de mapa activadas.")

        return {OUTPUT_OK: 1}
