from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_RIESGO = "Riesgo"

CAMPO_CF_FINAL_CANDIDATOS = ("CF_Final", "CF final", "cf_final")
CAMPO_PF_CANDIDATOS       = ("PF", "pf")

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
            if all(token in lower_name for token in partial_tokens):
                return i

    return -1


def _to_float_or_none(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _calcular_riesgo(cf_final, pf):
    """Calcula el Riesgo como suma de CF_Final + PF."""
    cf_val = _to_float_or_none(cf_final)
    pf_val = _to_float_or_none(pf)
    if cf_val is None and pf_val is None:
        return None
    if cf_val is None:
        return pf_val
    if pf_val is None:
        return cf_val
    return cf_val + pf_val


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class RiesgoCalculo(QgsProcessingAlgorithm):
    """Calcula el Riesgo como suma de CF_Final + PF."""

    def name(self):
        return "riesgo_calculo"

    def displayName(self):
        return "Riesgo Calculo"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Calcula el campo Riesgo para cada colector como la suma de "
            "CF_Final + PF. Si uno de los dos valores es nulo, se usa el otro. "
            "Si ambos son nulos, el campo queda en NULL."
        )

    def createInstance(self):
        return RiesgoCalculo()

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

        idx_cf_final = _find_field_index(
            fields, CAMPO_CF_FINAL_CANDIDATOS, exclude_names=(CAMPO_RIESGO,)
        )
        if idx_cf_final == -1:
            idx_cf_final = _find_field_index(
                fields, (), partial_tokens=("cf", "final"), exclude_names=(CAMPO_RIESGO,)
            )
        if idx_cf_final == -1:
            raise QgsProcessingException("No se encontro el campo CF_Final en Colectores.")

        idx_pf = _find_field_index(
            fields, CAMPO_PF_CANDIDATOS, exclude_names=(CAMPO_RIESGO,)
        )
        if idx_pf == -1:
            idx_pf = _find_field_index(
                fields, (), partial_tokens=("pf",), exclude_names=(CAMPO_RIESGO,)
            )
        if idx_pf == -1:
            raise QgsProcessingException("No se encontro el campo PF en Colectores.")

        feedback.pushInfo(f"Campo CF_Final detectado: {fields.at(idx_cf_final).name()}")
        feedback.pushInfo(f"Campo PF detectado: {fields.at(idx_pf).name()}")

        idx_riesgo = fields.lookupField(CAMPO_RIESGO)
        if idx_riesgo == -1:
            if not capa_colectores.dataProvider().addAttributes(
                [QgsField(CAMPO_RIESGO, QVariant.Double, len=10, prec=2)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo {CAMPO_RIESGO} en Colectores."
                )
            capa_colectores.updateFields()
            idx_riesgo = capa_colectores.fields().lookupField(CAMPO_RIESGO)
            if idx_riesgo == -1:
                raise QgsProcessingException(f"El campo {CAMPO_RIESGO} no quedo disponible.")

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

                nuevo_riesgo = _calcular_riesgo(feature[idx_cf_final], feature[idx_pf])
                valor_actual = feature[idx_riesgo]

                # Log de debug para las primeras 5 features
                if i <= 5:
                    feedback.pushInfo(
                        f"FID {feature.id()}: CF_Final={feature[idx_cf_final]}, "
                        f"PF={feature[idx_pf]} -> Riesgo={nuevo_riesgo} (actual: {valor_actual})"
                    )

                if valor_actual != nuevo_riesgo or valor_actual is None:
                    if not capa_colectores.changeAttributeValue(
                        feature.id(), idx_riesgo, nuevo_riesgo
                    ):
                        raise QgsProcessingException(
                            f"No se pudo actualizar {CAMPO_RIESGO} en FID {feature.id()}."
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
