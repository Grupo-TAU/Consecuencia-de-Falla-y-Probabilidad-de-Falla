from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
)
from qgis.PyQt.QtCore import QVariant


def _find_field_index(fields, candidates):
    lower_to_index = {fields.at(i).name().lower(): i for i in range(fields.count())}
    for candidate in candidates:
        idx = lower_to_index.get(candidate.lower())
        if idx is not None:
            return idx
    return -1


def _to_float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_null(value):
    return value is None


# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_COTA_ZAMP_DEFAULT   = "Cota_Zampeado_Calculada"
CAMPO_COTA_TAPA_DEFAULT   = "Cota_Tapa_Inspeccionada"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"

# ── Nombres de parametros ─────────────────────────────────────────────────────
REGISTROS             = "REGISTROS"
PARAM_CAMPO_COTA_ZAMP = "CAMPO_COTA_ZAMP"
PARAM_CAMPO_COTA_TAPA = "CAMPO_COTA_TAPA"
PARAM_CAMPO_PROF_INSPEC = "CAMPO_PROF_INSPEC"
OUTPUT_ACTUALIZADOS   = "ACTUALIZADOS"


class ActualizarRegistrosCotaZampeado(QgsProcessingAlgorithm):
    """Calcula Cota_Zampeado_Calculada en Registros donde sea NULL."""

    def name(self):
        return "actualizar_registros_cota_zampeado"

    def displayName(self):
        return "Actualizar Registros - Cota Zampeado"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Calcula Cota_Zampeado_Calculada en Registros donde sea NULL.\n\n"
            "Si Prof_Salto tiene valor:\n"
            "  Cota_Zampeado_Calculada = Cota_Tapa_Inspeccionada - Prof_Salto\n\n"
            "Si no:\n"
            "  Cota_Zampeado_Calculada = Cota_Tapa_Inspeccionada - Profundidad_Inspeccionada\n\n"
            "Solo se actualizan registros donde Cota_Zampeado_Calculada este en NULL."
        )

    def createInstance(self):
        return ActualizarRegistrosCotaZampeado()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(REGISTROS, "Capa Registros")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_ZAMP,
                "Nombre campo salida (Cota Zampeado Calculada)",
                defaultValue=CAMPO_COTA_ZAMP_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_TAPA,
                "Nombre campo Cota Tapa Inspeccionada",
                defaultValue=CAMPO_COTA_TAPA_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PROF_INSPEC,
                "Nombre campo Profundidad Inspeccionada",
                defaultValue=CAMPO_PROF_INSPEC_DEFAULT,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADOS, "Cantidad de registros actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        registros_layer = self.parameterAsVectorLayer(parameters, REGISTROS, context)

        if registros_layer is None:
            raise QgsProcessingException("No se pudo leer la capa Registros.")

        campo_cota_zamp = (
            self.parameterAsString(parameters, PARAM_CAMPO_COTA_ZAMP, context).strip()
            or CAMPO_COTA_ZAMP_DEFAULT
        )
        campo_cota_tapa = (
            self.parameterAsString(parameters, PARAM_CAMPO_COTA_TAPA, context).strip()
            or CAMPO_COTA_TAPA_DEFAULT
        )
        campo_prof_inspec = (
            self.parameterAsString(parameters, PARAM_CAMPO_PROF_INSPEC, context).strip()
            or CAMPO_PROF_INSPEC_DEFAULT
        )
        feedback.pushInfo(f"Campo salida              : {campo_cota_zamp}")
        feedback.pushInfo(f"Cota Tapa Inspeccionada   : {campo_cota_tapa}")
        feedback.pushInfo(f"Profundidad Inspeccionada : {campo_prof_inspec}")

        fields = registros_layer.fields()

        # Crea Cota_Zampeado_Calculada si no existe
        idx_cota_zamp = _find_field_index(fields, (campo_cota_zamp,))
        if idx_cota_zamp == -1:
            if not registros_layer.dataProvider().addAttributes(
                [QgsField(campo_cota_zamp, QVariant.Double, len=20, prec=2)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo '{campo_cota_zamp}' en Registros."
                )
            registros_layer.updateFields()
            fields        = registros_layer.fields()
            idx_cota_zamp = _find_field_index(fields, (campo_cota_zamp,))
            feedback.pushInfo(f"Se creo el campo '{campo_cota_zamp}' en Registros.")

        idx_cota_tapa   = _find_field_index(fields, (campo_cota_tapa,))
        idx_prof_inspec = _find_field_index(fields, (campo_prof_inspec,))

        for nombre, idx in [
            (campo_cota_tapa,   idx_cota_tapa),
            (campo_prof_inspec, idx_prof_inspec),
        ]:
            if idx == -1:
                raise QgsProcessingException(
                    f"No se encontro el campo '{nombre}' en Registros."
                )

        inicio_edicion = False
        if not registros_layer.isEditable():
            if not registros_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Registros."
                )
            inicio_edicion = True

        idx_id_reg     = _find_field_index(fields, ("ID", "id"))
        registros_list = list(registros_layer.getFeatures())
        total          = len(registros_list)
        actualizados   = 0
        ids_actualizados = []

        try:
            for i, reg in enumerate(registros_list, start=1):
                if feedback.isCanceled():
                    break

                if not _is_null(reg[idx_cota_zamp]):
                    continue   # Ya tiene valor, no sobreescribir

                cota_tapa   = _to_float_or_none(reg[idx_cota_tapa])
                prof_inspec = _to_float_or_none(reg[idx_prof_inspec])

                cota_calc = None
                if cota_tapa is not None and prof_inspec is not None:
                    cota_calc = round(cota_tapa - prof_inspec, 2)

                if cota_calc is not None:
                    if not registros_layer.changeAttributeValue(
                        reg.id(), idx_cota_zamp, cota_calc
                    ):
                        raise QgsProcessingException(
                            f"No se pudo escribir '{campo_cota_zamp}' en FID {reg.id()}."
                        )
                    actualizados += 1
                    reg_id = str(reg[idx_id_reg]).strip() if idx_id_reg != -1 else str(reg.id())
                    ids_actualizados.append(reg_id)

                feedback.setProgress(100.0 * i / max(total, 1))

            if inicio_edicion:
                if not registros_layer.commitChanges():
                    errores = "; ".join(registros_layer.commitErrors())
                    registros_layer.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Registros: " + errores
                    )

        except Exception:
            if inicio_edicion and registros_layer.isEditable():
                registros_layer.rollBack()
            raise

        feedback.pushInfo(f"Registros actualizados: {actualizados}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADOS: actualizados}
