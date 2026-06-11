from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_RIESGO_DEFAULT   = "Riesgo"
CAMPO_CF_FINAL_DEFAULT = "CF_Final"
CAMPO_PF_DEFAULT       = "PF"

CAMPO_CF_FINAL_CANDIDATOS = ("CF_Final", "CF final", "cf_final")
CAMPO_PF_CANDIDATOS       = ("PF", "pf")

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES           = "COLECTORES"
PARAM_CAMPO_RIESGO   = "CAMPO_RIESGO"
PARAM_CAMPO_CF_FINAL = "CAMPO_CF_FINAL"
PARAM_CAMPO_PF       = "CAMPO_PF"
OUTPUT_ACTUALIZADAS  = "ACTUALIZADAS"


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
    """Calcula el Riesgo como CF_Final x PF. NULL o 0 se tratan como 1."""
    cf_val = _to_float_or_none(cf_final)
    pf_val = _to_float_or_none(pf)
    if cf_val is None and pf_val is None:
        return None
    cf_val = cf_val if (cf_val is not None and cf_val != 0.0) else 1.0
    pf_val = pf_val if (pf_val is not None and pf_val != 0.0) else 1.0
    return round(cf_val * pf_val, 2)


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class RiesgoCalculo(QgsProcessingAlgorithm):
    """Calcula el Riesgo como CF_Final x PF."""

    def name(self):
        return "riesgo_calculo"

    def displayName(self):
        return "Calculo de Riesgo"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Calcula el riesgo de cada colector como la multiplicación entre la Consecuencia de Falla (CF_Final) y la Probabilidad de Falla (PF).\n\n"
            "Si alguno de los dos valores es vacío o es 0, el algoritmo lo interpreta como 1 para evitar que el riesgo se anule.\n\n"
            "Si ambos están vacíos, el resultado del riesgo es vacío.\n\n"
            "El campo Riesgo se crea o actualiza automáticamente en la capa de colectores."
        )

    def createInstance(self):
        return RiesgoCalculo()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_RIESGO,
                "Nombre campo salida (Riesgo)",
                defaultValue=CAMPO_RIESGO_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_CF_FINAL,
                "Nombre de campo de Consecuencia de Falla Final de capa Colectores",
                defaultValue=CAMPO_CF_FINAL_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PF,
                "Nombre de campo de Probabilidad de Falla de capa Colectores",
                defaultValue=CAMPO_PF_DEFAULT,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        capa_colectores = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa_colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        campo_riesgo   = self.parameterAsString(parameters, PARAM_CAMPO_RIESGO,   context).strip() or CAMPO_RIESGO_DEFAULT
        campo_cf_final = self.parameterAsString(parameters, PARAM_CAMPO_CF_FINAL, context).strip() or CAMPO_CF_FINAL_DEFAULT
        campo_pf       = self.parameterAsString(parameters, PARAM_CAMPO_PF,       context).strip() or CAMPO_PF_DEFAULT

        feedback.pushInfo(f"Campo salida (Riesgo): {campo_riesgo}")
        feedback.pushInfo(f"Campo CF Final       : {campo_cf_final}")
        feedback.pushInfo(f"Campo PF             : {campo_pf}")

        fields = capa_colectores.fields()

        idx_cf_final = _find_field_index(
            fields,
            (campo_cf_final,) + CAMPO_CF_FINAL_CANDIDATOS,
            exclude_names=(campo_riesgo,),
        )
        if idx_cf_final == -1:
            idx_cf_final = _find_field_index(
                fields, (), partial_tokens=("cf", "final"), exclude_names=(campo_riesgo,)
            )
        if idx_cf_final == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_cf_final}' en Colectores."
            )

        idx_pf = _find_field_index(
            fields,
            (campo_pf,) + CAMPO_PF_CANDIDATOS,
            exclude_names=(campo_riesgo,),
        )
        if idx_pf == -1:
            idx_pf = _find_field_index(
                fields, (), partial_tokens=("pf",), exclude_names=(campo_riesgo,)
            )
        if idx_pf == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_pf}' en Colectores."
            )

        feedback.pushInfo(f"Campo CF_Final detectado: {fields.at(idx_cf_final).name()}")
        feedback.pushInfo(f"Campo PF detectado      : {fields.at(idx_pf).name()}")

        idx_riesgo = fields.lookupField(campo_riesgo)
        if idx_riesgo == -1:
            if not capa_colectores.dataProvider().addAttributes(
                [QgsField(campo_riesgo, QVariant.Double, len=10, prec=2)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo '{campo_riesgo}' en Colectores."
                )
            capa_colectores.updateFields()
            idx_riesgo = capa_colectores.fields().lookupField(campo_riesgo)
            if idx_riesgo == -1:
                raise QgsProcessingException(f"El campo '{campo_riesgo}' no quedo disponible.")

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

        actualizadas     = 0
        ids_actualizados = []
        idx_id_col       = _find_field_index(fields, ("ID", "id"))

        try:
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break

                nuevo_riesgo = _calcular_riesgo(feature[idx_cf_final], feature[idx_pf])
                valor_actual = feature[idx_riesgo]

                if i <= 5:
                    feedback.pushInfo(
                        f"FID {feature.id()}: {campo_cf_final}={feature[idx_cf_final]}, "
                        f"{campo_pf}={feature[idx_pf]} -> {campo_riesgo}={nuevo_riesgo} (actual: {valor_actual})"
                    )

                if valor_actual != nuevo_riesgo or valor_actual is None:
                    if not capa_colectores.changeAttributeValue(
                        feature.id(), idx_riesgo, nuevo_riesgo
                    ):
                        raise QgsProcessingException(
                            f"No se pudo actualizar '{campo_riesgo}' en FID {feature.id()}."
                        )
                    actualizadas += 1
                    col_id = str(feature[idx_id_col]).strip() if idx_id_col != -1 else str(feature.id())
                    ids_actualizados.append(col_id)

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

        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas}
