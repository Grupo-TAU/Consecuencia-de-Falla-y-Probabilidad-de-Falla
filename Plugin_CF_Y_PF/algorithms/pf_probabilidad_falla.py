from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_PF = "PF"
PACP_CLASIFICACION_CANDIDATOS = (
    "PACP_Clasificacion",
    "PACP_Clasificación",
    "pacp_clasificacion",
    "pacp_clasificación",
)

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES          = "COLECTORES"
OUTPUT_ACTUALIZADAS = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_field_index(fields, candidates, partial_tokens=(), exclude_names=()):
    if isinstance(candidates, str):
        candidates = (candidates,)
    nombres        = [fields.at(i).name() for i in range(fields.count())]
    lower_to_index = {name.lower(): i for i, name in enumerate(nombres)}
    exclude_lower  = {str(name).lower() for name in exclude_names}

    for candidate in candidates:
        candidate_lower = str(candidate).lower()
        if candidate_lower in exclude_lower:
            continue
        idx = lower_to_index.get(candidate_lower)
        if idx is not None:
            return idx

    if partial_tokens:
        for i, name in enumerate(nombres):
            lower_name = name.lower()
            if lower_name in exclude_lower:
                continue
            if any(token in lower_name for token in partial_tokens):
                return i

    return -1


def _calcular_pf(pacp_clasificacion):
    """
    Calcula la Probabilidad de Falla (PF) basada en PACP_Clasificacion.

    Reglas:
    - Sin informacion o vacio         -> PF = 0
    - 2do caracter es letra           -> PF = primer_digito + 1  (ej: 5B -> 6.0)
    - Ambos primeros caracteres digit -> PF = dos_primeros / 10  (ej: 3222 -> 3.2)
      - Si resultado es 0 (0000)      -> PF = 1.0
    - Otros casos                     -> PF = 0
    """
    if pacp_clasificacion is None:
        return 0

    texto = str(pacp_clasificacion).strip()
    if not texto or len(texto) < 2:
        return 0

    char1, char2 = texto[0], texto[1]

    if char1.isdigit() and char2.isalpha():
        return float(int(char1)) + 1.0

    if char1.isdigit() and char2.isdigit():
        valor = int(char1 + char2) / 10.0
        return valor if valor > 0 else 1.0

    return 0


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class PfProbabilidadFalla(QgsProcessingAlgorithm):
    """Calcula Probabilidad de Falla (PF) basada en PACP_Clasificacion."""

    def name(self):
        return "pf_probabilidad_falla"

    def displayName(self):
        return "PF Probabilidad de Falla"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Calcula la Probabilidad de Falla (PF) para cada colector a partir "
            "del campo PACP_Clasificacion y escribe el resultado en el campo PF.\n\n"
            "Reglas de calculo:\n"
            "  - Sin datos / vacio: PF = 0\n"
            "  - 2do caracter letra (ej: 5B): PF = primer digito + 1\n"
            "  - Ambos primeros digitos (ej: 3222): PF = primeros dos digitos / 10\n"
            "  - Clasificacion 0000 (sin defectos): PF = 1"
        )

    def createInstance(self):
        return PfProbabilidadFalla()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        capa_colectores = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa_colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        fields = capa_colectores.fields()

        idx_pacp = _find_field_index(
            fields, PACP_CLASIFICACION_CANDIDATOS, exclude_names=(CAMPO_PF,)
        )
        if idx_pacp == -1:
            idx_pacp = _find_field_index(
                fields, (), partial_tokens=("pacp",), exclude_names=(CAMPO_PF,)
            )
        if idx_pacp == -1:
            raise QgsProcessingException(
                "No se encontro un campo de clasificacion PACP en Colectores "
                "(ej: PACP_Clasificacion)."
            )

        feedback.pushInfo(f"Campo PACP detectado: {fields.at(idx_pacp).name()}")

        idx_pf = fields.lookupField(CAMPO_PF)
        if idx_pf == -1:
            if not capa_colectores.dataProvider().addAttributes(
                [QgsField(CAMPO_PF, QVariant.Double, len=10, prec=2)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo {CAMPO_PF} en Colectores."
                )
            capa_colectores.updateFields()
            idx_pf = capa_colectores.fields().lookupField(CAMPO_PF)
            if idx_pf == -1:
                raise QgsProcessingException(f"El campo {CAMPO_PF} no quedo disponible.")

        inicio_edicion = False
        if not capa_colectores.isEditable():
            if not capa_colectores.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        features = list(capa_colectores.getFeatures())
        total    = len(features)
        if total == 0:
            if inicio_edicion:
                if not capa_colectores.commitChanges():
                    errores = "; ".join(capa_colectores.commitErrors())
                    capa_colectores.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas = 0

        try:
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break

                nueva_pf = _calcular_pf(feature[idx_pacp])
                if feature[idx_pf] != nueva_pf:
                    if not capa_colectores.changeAttributeValue(
                        feature.id(), idx_pf, nueva_pf
                    ):
                        raise QgsProcessingException(
                            f"No se pudo actualizar {CAMPO_PF} en FID {feature.id()}."
                        )
                    actualizadas += 1

                feedback.setProgress(100.0 * i / total)

            if inicio_edicion:
                if not capa_colectores.commitChanges():
                    errores = "; ".join(capa_colectores.commitErrors())
                    capa_colectores.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )

        except Exception:
            if inicio_edicion and capa_colectores.isEditable():
                capa_colectores.rollBack()
            raise

        return {OUTPUT_ACTUALIZADAS: actualizadas}
