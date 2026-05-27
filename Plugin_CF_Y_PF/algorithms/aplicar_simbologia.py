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

# Prefijo que identifica las reglas gestionadas por este algoritmo.
# Las reglas del usuario que NO tengan este prefijo nunca se tocan.
_PREFIJO = "[AUTO] "

# (expresion, color, etiqueta_sin_prefijo)
RANGOS = [
    ('"CF_Final" >= 0 AND "CF_Final" <= 1', QColor("#2CA02C"), "<= 1 - Verde"),
    ('"CF_Final" >  1 AND "CF_Final" <= 2', QColor("#98DF8A"), "<= 2 - Verde claro"),
    ('"CF_Final" >  2 AND "CF_Final" <= 3', QColor("#FFFF00"), "<= 3 - Amarillo"),
    ('"CF_Final" >  3 AND "CF_Final" <= 4', QColor("#FFBB78"), "<= 4 - Naranjo claro"),
    ('"CF_Final" >  4 AND "CF_Final" <= 5', QColor("#FF7F0E"), "<= 5 - Naranjo"),
    ('"CF_Final" >  5 AND "CF_Final" <= 6', QColor("#D62728"), "<= 6 - Rojo"),
]

COLECTORES = "COLECTORES"
CAMPO      = "CAMPO"
OUTPUT_OK  = "SIMBOLOGIA_OK"



def _construir_expresion(campo, expr_base):
    """Reemplaza 'CF_Final' por el campo elegido por el usuario."""
    return expr_base.replace('"CF_Final"', f'"{campo}"')


class AplicarSimbologia(QgsProcessingAlgorithm):
    """
    Aplica simbologia basada en reglas (1-6) a la capa Colectores.
    Las reglas automaticas se actualizan en cada ejecucion;
    las reglas agregadas manualmente por el usuario se preservan.
    """

    def name(self):
        return "aplicar_simbologia"

    def displayName(self):
        return "Aplicar Simbologia (1-6)"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Aplica a la capa Colectores una simbologia basada en los resultados de la Consecuencia de Falla Final.\n\n"
            "Las reglas que el usuario agregue manualmente en QGIS \n\n"
            "Rangos \n\n"
            "<=1=Verde \n\n"
            "<=2=Verde claro \n\n"
            "<=3=Amarillo \n\n" 
            "<=4=Naranjo claro \n\n"
            "<=5=Naranjo\n\n"
            "<=6=Rojo"
        )

    def createInstance(self):
        return AplicarSimbologia()

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterString(
                CAMPO,
                "Campo de clasificacion (valores 1-6)",
                defaultValue="CF_Final",
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_OK, "1 si la simbologia se aplico correctamente")
        )

    def processAlgorithm(self, parameters, context, feedback):
        capa = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        campo = self.parameterAsString(parameters, CAMPO, context)
        if not campo:
            raise QgsProcessingException("Debe especificar el campo de clasificacion.")
        if capa.fields().lookupField(campo) == -1:
            raise QgsProcessingException(
                f"El campo '{campo}' no existe en la capa Colectores."
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
