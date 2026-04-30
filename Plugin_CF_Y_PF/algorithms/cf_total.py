from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_CF_FINAL = "CF_Final"

CAMPO_POS_REL_CANDIDATOS     = ("CF_PosicionRelativa",)
CAMPO_DIAMETRO_CANDIDATOS    = ("CF_Diametro",)
CAMPO_PROFUNDIDAD_CANDIDATOS = ("CF_Profundidad",)
CAMPO_PROX_MA_CANDIDATOS     = ("CF_Prox_MedioAmbiental",)
CAMPO_PROX_CI_CANDIDATOS     = ("CF_Prox_ClienteImportante",)
CAMPO_ANTIGUEDAD_CANDIDATOS  = ("CF_Antiguedad",)
CAMPO_MATERIAL_CANDIDATOS    = ("CF_Material",)
CAMPO_OBSTRUC_CANDIDATOS     = ("CF_Obstrucciones",)
CAMPO_ACCESO_CANDIDATOS      = ("CF_Acceso",)  # pendiente de implementar

#                          Economico  Social  Medioambiental  Valorizacion
PESO_ECONOMICO      = 0.30  # X_2 + X_3 + X_9
PESO_SOCIAL         = 0.30  # X_1 + X_5
PESO_MEDIOAMBIENTAL = 0.15  # X_4
PESO_VALORIZACION   = 0.25  # X_6 + X_7 + X_8

POSIBLE_ECONOMICO      = 12.0   # 3 campos × max 6
POSIBLE_SOCIAL         = 12.0   # 2 campos × max 6
POSIBLE_MEDIOAMBIENTAL = 6.0    # 1 campo  × max 6
POSIBLE_VALORIZACION   = 18.0   # 3 campos × max 6

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


def _to_cf_value(value):
    val = _to_float_or_none(value)
    if val is None:
        return 1.0
    return max(1.0, min(6.0, val))


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfTotal(QgsProcessingAlgorithm):
    """Calcula CF_Final por tramo segun la matriz de ponderacion definida."""

    def name(self):
        return "cf_total"

    def displayName(self):
        return "CF Total (CF_Final)"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Calcula el CF_Final de cada colector combinando los factores de consecuencia "
            "segun la matriz de ponderacion:\n\n"
            "  Economico      (30 %): CF_Diametro + CF_Profundidad  [posible: 12]\n"
            "  Social         (30 %): CF_PosicionRelativa + CF_Prox_ClienteImportante  [posible: 12]\n"
            "  Medioambiental (15 %): CF_Prox_MedioAmbiental  [posible: 6]\n"
            "  Valorizacion   (25 %): CF_Antiguedad + CF_Material + CF_Obstrucciones  [posible: 18]\n\n"
            "CF_PONDERADO = (CF_TOTAL / CF_POSIBLE) * CF_FactorDePonderacion\n"
            "CF_Final     = SUMA(CF_PONDERADO) * 6\n\n"
            "El resultado se escribe en el campo CF_Final. Si el campo no existe, se crea automáticamente."
        )

    def createInstance(self):
        return CfTotal()

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

        # ── Busqueda de campos ─────────────────────────────────────────────────
        idx_x1 = _find_field_index(
            fields, CAMPO_POS_REL_CANDIDATOS,
            partial_tokens=("cf", "pos", "rel"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x2 = _find_field_index(
            fields, CAMPO_DIAMETRO_CANDIDATOS,
            partial_tokens=("cf", "diam"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x3 = _find_field_index(
            fields, CAMPO_PROFUNDIDAD_CANDIDATOS,
            partial_tokens=("cf", "prof"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x4 = _find_field_index(
            fields, CAMPO_PROX_MA_CANDIDATOS,
            partial_tokens=("cf", "medio"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x5 = _find_field_index(
            fields, CAMPO_PROX_CI_CANDIDATOS,
            partial_tokens=("cf", "cliente"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x6 = _find_field_index(
            fields, CAMPO_ANTIGUEDAD_CANDIDATOS,
            partial_tokens=("cf", "antig"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x7 = _find_field_index(
            fields, CAMPO_MATERIAL_CANDIDATOS,
            partial_tokens=("cf", "mater"), exclude_names=(CAMPO_CF_FINAL,),
        )
        idx_x8 = _find_field_index(
            fields, CAMPO_OBSTRUC_CANDIDATOS,
            partial_tokens=("cf", "obstr"), exclude_names=(CAMPO_CF_FINAL,),
        )
        # CF_Acceso es opcional (pendiente de implementar)
        idx_x9 = _find_field_index(
            fields, CAMPO_ACCESO_CANDIDATOS,
            partial_tokens=("cf", "acces"), exclude_names=(CAMPO_CF_FINAL,),
        )

        # ── Validacion de campos requeridos ────────────────────────────────────
        required = {
            "CF_PosicionRelativa (X_1)":       idx_x1,
            "CF_Diametro (X_2)":               idx_x2,
            "CF_Profundidad (X_3)":            idx_x3,
            "CF_Prox_MedioAmbiental (X_4)":    idx_x4,
            "CF_Prox_ClienteImportante (X_5)": idx_x5,
            "CF_Antiguedad (X_6)":             idx_x6,
            "CF_Material (X_7)":               idx_x7,
            "CF_Obstrucciones (X_8)":          idx_x8,
        }
        missing = [name for name, idx in required.items() if idx == -1]
        if missing:
            raise QgsProcessingException(
                "Faltan columnas requeridas en Colectores: " + ", ".join(missing)
            )

        feedback.pushInfo(f"Campo X_1 detectado: {fields.at(idx_x1).name()}")
        feedback.pushInfo(f"Campo X_2 detectado: {fields.at(idx_x2).name()}")
        feedback.pushInfo(f"Campo X_3 detectado: {fields.at(idx_x3).name()}")
        feedback.pushInfo(f"Campo X_4 detectado: {fields.at(idx_x4).name()}")
        feedback.pushInfo(f"Campo X_5 detectado: {fields.at(idx_x5).name()}")
        feedback.pushInfo(f"Campo X_6 detectado: {fields.at(idx_x6).name()}")
        feedback.pushInfo(f"Campo X_7 detectado: {fields.at(idx_x7).name()}")
        feedback.pushInfo(f"Campo X_8 detectado: {fields.at(idx_x8).name()}")
        #feedback.pushInfo(f"Campo X_9 detectado: {fields.at(idx_x9).name()}")

        # ── Campo de salida ────────────────────────────────────────────────────
        idx_cf_final = fields.lookupField(CAMPO_CF_FINAL)
        if idx_cf_final == -1:
            if not capa_colectores.dataProvider().addAttributes(
                [QgsField(CAMPO_CF_FINAL, QVariant.Double, len=10, prec=2)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo {CAMPO_CF_FINAL} en Colectores."
                )
            capa_colectores.updateFields()
            idx_cf_final = capa_colectores.fields().lookupField(CAMPO_CF_FINAL)
            if idx_cf_final == -1:
                raise QgsProcessingException(
                    f"El campo {CAMPO_CF_FINAL} no quedo disponible."
                )

        inicio_edicion = False
        if not capa_colectores.isEditable():
            if not capa_colectores.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        colectores_list = list(capa_colectores.getFeatures())
        total           = len(colectores_list)
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
            for i, colector in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                x1 = _to_cf_value(colector[idx_x1])
                x2 = _to_cf_value(colector[idx_x2])
                x3 = _to_cf_value(colector[idx_x3])
                x4 = _to_cf_value(colector[idx_x4])
                x5 = _to_cf_value(colector[idx_x5])
                x6 = _to_cf_value(colector[idx_x6])
                x7 = _to_cf_value(colector[idx_x7])
                x8 = _to_cf_value(colector[idx_x8])
               #x9 = _to_cf_value(colector[idx_x9])

                cf_pond_economico      = ((x2 + x3) / POSIBLE_ECONOMICO)      * PESO_ECONOMICO
                cf_pond_social         = ((x1 + x5)       / POSIBLE_SOCIAL)         * PESO_SOCIAL
                cf_pond_medioambiental = (x4               / POSIBLE_MEDIOAMBIENTAL) * PESO_MEDIOAMBIENTAL
                cf_pond_valorizacion   = ((x6 + x7 + x8)  / POSIBLE_VALORIZACION)   * PESO_VALORIZACION

                cf_final = round(
                    (cf_pond_economico + cf_pond_social + cf_pond_medioambiental + cf_pond_valorizacion) * 6.0,
                    2,
                )

                valor_actual = _to_float_or_none(colector[idx_cf_final])
                if valor_actual is None or abs(valor_actual - cf_final) > 1e-9:
                    if not capa_colectores.changeAttributeValue(
                        colector.id(), idx_cf_final, cf_final
                    ):
                        raise QgsProcessingException(
                            f"No se pudo actualizar {CAMPO_CF_FINAL} en FID {colector.id()}."
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
