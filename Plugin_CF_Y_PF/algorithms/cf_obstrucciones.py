from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterString,
    QgsProcessingOutputNumber,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_CF_OBSTRUCCIONES = "CF_Obstrucciones"
CAMPO_OBSTRUCCIONES    = "Obstrucciones"

# Baja (0)  → 1 | Media (1) → 3 | Alta (>=2) → 6

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES          = "COLECTORES"
PARAM_CAMPO_SALIDA  = "CAMPO_CF_OBSTRUCCIONES"
PARAM_CAMPO_OBS     = "CAMPO_OBSTRUCCIONES"
OUTPUT_ACTUALIZADAS = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_field_index(fields, field_name):
    lower_map = {fields.at(i).name().lower(): i for i in range(fields.count())}
    return lower_map.get(str(field_name).strip().lower(), -1)


def _to_int_or_none(value):
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clasificar_obstrucciones(obs):
    if obs == 0:
        return 1
    if obs == 1:
        return 3
    return 6  # >= 2


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfObstrucciones(QgsProcessingAlgorithm):
    """Clasifica colectores por obstrucciones/ano y escribe CF_Obstrucciones."""

    def name(self):
        return "cf_obstrucciones"

    def displayName(self):
        return "CF Obstrucciones"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector segun la cantidad de obstrucciones por ano "
            "(con y sin desbordes) y escribe el resultado en CF_Obstrucciones.\n\n"
            "Clasificacion:\n"
            "  0 obstrucciones (Baja)  → 1\n"
            "  1 obstruccion   (Media) → 3\n"
            "  >=2 obstrucciones (Alta)  → 6\n\n"
            "Si el campo de obstrucciones esta vacio o es nulo, se asigna clase 0."
        )

    def createInstance(self):
        return CfObstrucciones()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_SALIDA,
                "Nombre campo salida (CF Obstrucciones)",
                defaultValue=CAMPO_CF_OBSTRUCCIONES,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_OBS,
                "Nombre campo obstrucciones (entrada)",
                defaultValue=CAMPO_OBSTRUCCIONES,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                OUTPUT_ACTUALIZADAS,
                "Cantidad de colectores actualizados",
            )
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        capa = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        campo_salida = (
            self.parameterAsString(parameters, PARAM_CAMPO_SALIDA, context).strip()
            or CAMPO_CF_OBSTRUCCIONES
        )
        campo_obs = (
            self.parameterAsString(parameters, PARAM_CAMPO_OBS, context).strip()
            or CAMPO_OBSTRUCCIONES
        )

        fields  = capa.fields()
        idx_obs = _find_field_index(fields, campo_obs)
        if idx_obs == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_obs}' en Colectores."
            )

        feedback.pushInfo(f"Campo obstrucciones detectado : {fields.at(idx_obs).name()}")
        feedback.pushInfo(f"Campo salida                  : {campo_salida}")

        # Crear el campo de salida si no existe
        idx_cf = fields.lookupField(campo_salida)
        if idx_cf == -1:
            ok = capa.dataProvider().addAttributes(
                [QgsField(campo_salida, QVariant.Int, len=10, prec=0)]
            )
            if not ok:
                raise QgsProcessingException(
                    f"No se pudo crear el campo '{campo_salida}' en Colectores."
                )
            capa.updateFields()
            idx_cf = capa.fields().lookupField(campo_salida)
            if idx_cf == -1:
                raise QgsProcessingException(
                    f"El campo '{campo_salida}' no quedo disponible tras crearlo."
                )

        inicio_edicion = False
        if not capa.isEditable():
            if not capa.startEditing():
                raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
            inicio_edicion = True

        features = list(capa.getFeatures())
        total    = len(features)
        if total == 0:
            if inicio_edicion:
                capa.commitChanges()
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas     = 0
        ids_actualizados = []
        idx_id_col       = _find_field_index(capa.fields(), "ID")
        try:
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break

                obs         = _to_int_or_none(feature[idx_obs])
                nueva_clase = (
                    _clasificar_obstrucciones(obs)
                    if obs is not None else 0
                )

                valor_actual = feature[idx_cf]
                if valor_actual is None or valor_actual != nueva_clase:
                    ok = capa.changeAttributeValue(feature.id(), idx_cf, nueva_clase)
                    if not ok:
                        raise QgsProcessingException(
                            f"No se pudo actualizar '{campo_salida}' en FID {feature.id()}."
                        )
                    actualizadas += 1
                    col_id = str(feature[idx_id_col]).strip() if idx_id_col != -1 else str(feature.id())
                    ids_actualizados.append(col_id)

                feedback.setProgress(100.0 * i / total)

            if inicio_edicion:
                if not capa.commitChanges():
                    errores = "; ".join(capa.commitErrors())
                    capa.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )

        except Exception:
            if inicio_edicion and capa.isEditable():
                capa.rollBack()
            raise

        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas}
