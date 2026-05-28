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
    if value is None:
        return True
    return str(value).strip().upper() == "NULL"


def _normalize_str(value):
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.upper() == "NULL" else s


def _add_field_to_layer(layer, field_name, variant_type, feedback, field_len=20, field_prec=6):
    if not layer.dataProvider().addAttributes(
        [QgsField(field_name, variant_type, len=field_len, prec=field_prec)]
    ):
        raise QgsProcessingException(f"No se pudo crear el campo '{field_name}'.")
    layer.updateFields()
    fields = layer.fields()
    idx = _find_field_index(fields, (field_name,))
    if idx == -1:
        raise QgsProcessingException(f"El campo '{field_name}' no quedo disponible.")
    feedback.pushInfo(f"Se creo el campo '{field_name}'.")
    return idx, fields


# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_COTA_ZAMP_DEFAULT    = "Cota_Zampeado_Calculada"
CAMPO_COTA_TAPA_DEFAULT    = "Cota_Tapa_Inspeccionada"
CAMPO_PROF_INSPEC_DEFAULT  = "Profundidad_Inspeccionada"
CAMPO_ID_REG_DEFAULT       = "ID"
CAMPO_ZARRIBA_DEFAULT      = "ZARRIBA"
CAMPO_REG_INI_COL_DEFAULT  = "Registro_Inicial"

# ── Nombres de parametros ─────────────────────────────────────────────────────
REGISTROS               = "REGISTROS"
COLECTORES              = "COLECTORES"
PARAM_CAMPO_COTA_ZAMP   = "CAMPO_COTA_ZAMP"
PARAM_CAMPO_COTA_TAPA   = "CAMPO_COTA_TAPA"
PARAM_CAMPO_PROF_INSPEC = "CAMPO_PROF_INSPEC"
PARAM_CAMPO_ID_REG      = "CAMPO_ID_REG"
PARAM_CAMPO_ZARRIBA     = "CAMPO_ZARRIBA"
PARAM_CAMPO_REG_INI_COL = "CAMPO_REG_INI_COL"
OUTPUT_ACTUALIZADOS     = "ACTUALIZADOS"


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
            "Calcula la cota de Zampeado de los Registros (si es vacia) a traves de dos posibles mecánicas.\n\n"
            "<strong> Mecánica 1 (si existe campo Profundidad Inspeccionada):</strong>\n"
            "  Cota Zampeado = Cota de Tapa Inspeccionada - Profundidad Inspeccionada\n\n"
            "<strong> Mecanica 2 (si se provee capa Colectores):</strong>\n"
            "  Para cada Colector, toma la cota de zampeado del registro inicial y lo asigna al Registro Inicial del colector.\n"
            "  Luego calcula la Profundidad Inspeccionada = Cota de Tapa - Cota Zampeado Calculada.\n\n"
            "  Solo se actualizan registros donde Cota Zampeado Calculada este vacio.\n"
            "  Ambas mecanicas pueden correr juntas pero la Mecanica 1 tiene prioridad."
        )

    def createInstance(self):
        return ActualizarRegistrosCotaZampeado()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(REGISTROS, "Capa Registros")
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                COLECTORES,
                "Capa Colectores (opcional - Mecanica 2)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_ZAMP,
                "Nombre campo salida (Ej: Cota Zampeado Calculada)",
                defaultValue=CAMPO_COTA_ZAMP_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_TAPA,
                "Nombre campo de Cota Tapa Inspeccionada de capa Registros",
                defaultValue=CAMPO_COTA_TAPA_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PROF_INSPEC,
                "Nombre campo de Profundidad Inspeccionada de capa Registros",
                defaultValue=CAMPO_PROF_INSPEC_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_ID_REG,
                "Nombre campo ID de capa Registros (requerido para Mecanica 2)",
                defaultValue=CAMPO_ID_REG_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_ZARRIBA,
                "Nombre campo Cota Zampeado Inicial de capa Colectores (requerido para Mecanica 2)",
                defaultValue=CAMPO_ZARRIBA_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REG_INI_COL,
                "Nombre campo Registro Inicial de capa Colectores (requerido para Mecanica 2)",
                defaultValue=CAMPO_REG_INI_COL_DEFAULT,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADOS, "Cantidad de registros actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        registros_layer  = self.parameterAsVectorLayer(parameters, REGISTROS, context)
        colectores_layer = self.parameterAsVectorLayer(parameters, COLECTORES, context)

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
        campo_id_reg = (
            self.parameterAsString(parameters, PARAM_CAMPO_ID_REG, context).strip()
            or CAMPO_ID_REG_DEFAULT
        )
        campo_zarriba = (
            self.parameterAsString(parameters, PARAM_CAMPO_ZARRIBA, context).strip()
            or CAMPO_ZARRIBA_DEFAULT
        )
        campo_reg_ini_col = (
            self.parameterAsString(parameters, PARAM_CAMPO_REG_INI_COL, context).strip()
            or CAMPO_REG_INI_COL_DEFAULT
        )

        feedback.pushInfo(f"Campo salida (Cota Zampeado)   : {campo_cota_zamp}")
        feedback.pushInfo(f"Cota Tapa Inspeccionada        : {campo_cota_tapa}")
        feedback.pushInfo(f"Profundidad Inspeccionada      : {campo_prof_inspec}")
        feedback.pushInfo(f"ID Registros                   : {campo_id_reg}")
        if colectores_layer is not None:
            feedback.pushInfo(f"ZARRIBA (Colectores)           : {campo_zarriba}")
            feedback.pushInfo(f"Registro_Inicial (Colectores)  : {campo_reg_ini_col}")

        fields = registros_layer.fields()

        # Crea Cota_Zampeado_Calculada si no existe
        idx_cota_zamp = _find_field_index(fields, (campo_cota_zamp,))
        if idx_cota_zamp == -1:
            idx_cota_zamp, fields = _add_field_to_layer(
                registros_layer, campo_cota_zamp, QVariant.Double, feedback,
                field_len=20, field_prec=2
            )

        idx_cota_tapa   = _find_field_index(fields, (campo_cota_tapa,))
        idx_prof_inspec = _find_field_index(fields, (campo_prof_inspec,))
        idx_id_reg      = _find_field_index(fields, (campo_id_reg,))

        if idx_cota_tapa == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_cota_tapa}' en Registros."
            )

        # Mecanica 2: crear Profundidad_Inspeccionada si no existe
        if colectores_layer is not None and idx_prof_inspec == -1:
            idx_prof_inspec, fields = _add_field_to_layer(
                registros_layer, campo_prof_inspec, QVariant.Double, feedback,
                field_len=20, field_prec=2
            )

        can_run_paso1 = idx_prof_inspec != -1
        can_run_paso2 = colectores_layer is not None

        if not can_run_paso1:
            feedback.pushInfo(
                f"Campo '{campo_prof_inspec}' no encontrado en Registros — se omite Mecanica 1."
            )
        if not can_run_paso2:
            feedback.pushInfo("Capa Colectores no proporcionada — se omite Mecanica 2.")

        if not can_run_paso1 and not can_run_paso2:
            raise QgsProcessingException(
                "No hay mecanica disponible: proveer campo Profundidad_Inspeccionada o capa Colectores."
            )

        if can_run_paso2 and idx_id_reg == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_id_reg}' en Registros (requerido para Mecanica 2)."
            )

        inicio_edicion = False
        if not registros_layer.isEditable():
            if not registros_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Registros."
                )
            inicio_edicion = True

        registros_list   = list(registros_layer.getFeatures())
        total            = len(registros_list)
        actualizados     = 0
        ids_actualizados = []
        fids_paso1       = set()

        progress_paso1 = 50.0 if can_run_paso2 else 100.0
        progress_paso2_offset = 50.0 if can_run_paso1 else 0.0
        progress_paso2_scale  = 50.0 if can_run_paso1 else 100.0

        try:
            # ── Mecanica 1: Cota_Tapa - Profundidad ───────────────────────────
            if can_run_paso1:
                feedback.pushInfo("--- Mecanica 1: Cota_Tapa - Profundidad ---")
                for i, reg in enumerate(registros_list, start=1):
                    if feedback.isCanceled():
                        break

                    if not _is_null(reg[idx_cota_zamp]):
                        continue

                    cota_tapa   = _to_float_or_none(reg[idx_cota_tapa])
                    prof_inspec = _to_float_or_none(reg[idx_prof_inspec])

                    if cota_tapa is None or prof_inspec is None:
                        continue

                    cota_calc = round(cota_tapa - prof_inspec, 2)
                    if not registros_layer.changeAttributeValue(
                        reg.id(), idx_cota_zamp, cota_calc
                    ):
                        raise QgsProcessingException(
                            f"No se pudo escribir '{campo_cota_zamp}' en FID {reg.id()}."
                        )
                    actualizados += 1
                    fids_paso1.add(reg.id())
                    reg_id = _normalize_str(reg[idx_id_reg]) if idx_id_reg != -1 else str(reg.id())
                    ids_actualizados.append(reg_id)
                    feedback.setProgress(progress_paso1 * i / max(total, 1))

                feedback.pushInfo(f"Mecanica 1: {len(fids_paso1)} registros actualizados.")

            # ── Mecanica 2: ZARRIBA desde Colectores ──────────────────────────
            if can_run_paso2 and not feedback.isCanceled():
                feedback.pushInfo("--- Mecanica 2: ZARRIBA desde Colectores ---")

                col_fields      = colectores_layer.fields()
                idx_zarriba     = _find_field_index(col_fields, (campo_zarriba,))
                idx_reg_ini_col = _find_field_index(col_fields, (campo_reg_ini_col,))

                for nombre, idx in [
                    (campo_zarriba,     idx_zarriba),
                    (campo_reg_ini_col, idx_reg_ini_col),
                ]:
                    if idx == -1:
                        raise QgsProcessingException(
                            f"No se encontro el campo '{nombre}' en Colectores."
                        )

                # Indice: ID_registro → feature
                id_to_feature = {}
                for reg in registros_list:
                    id_val = _normalize_str(reg[idx_id_reg])
                    if id_val:
                        id_to_feature[id_val] = reg

                colectores_list    = list(colectores_layer.getFeatures())
                actualizados_paso2 = 0

                for i, col in enumerate(colectores_list, start=1):
                    if feedback.isCanceled():
                        break

                    reg_ini_id = _normalize_str(col[idx_reg_ini_col])
                    if not reg_ini_id:
                        continue

                    zarriba_val = _to_float_or_none(col[idx_zarriba])
                    if zarriba_val is None:
                        continue

                    reg_feature = id_to_feature.get(reg_ini_id)
                    if reg_feature is None:
                        continue

                    if reg_feature.id() in fids_paso1:
                        continue

                    if not _is_null(reg_feature[idx_cota_zamp]):
                        continue

                    if not registros_layer.changeAttributeValue(
                        reg_feature.id(), idx_cota_zamp, zarriba_val
                    ):
                        raise QgsProcessingException(
                            f"No se pudo escribir '{campo_cota_zamp}' en FID {reg_feature.id()}."
                        )

                    # Profundidad = Cota_Tapa - Cota_Zampeado
                    cota_tapa_val = _to_float_or_none(reg_feature[idx_cota_tapa])
                    if cota_tapa_val is not None:
                        if cota_tapa_val == 0 or zarriba_val == 0:
                            prof_calc = 0.0
                        else:
                            prof_calc = round(cota_tapa_val - zarriba_val, 2)
                        if not registros_layer.changeAttributeValue(
                            reg_feature.id(), idx_prof_inspec, prof_calc
                        ):
                            raise QgsProcessingException(
                                f"No se pudo escribir '{campo_prof_inspec}' en FID {reg_feature.id()}."
                            )

                    actualizados += 1
                    actualizados_paso2 += 1
                    reg_id = _normalize_str(reg_feature[idx_id_reg])
                    ids_actualizados.append(reg_id)
                    feedback.setProgress(
                        progress_paso2_offset + progress_paso2_scale * i / max(len(colectores_list), 1)
                    )

                feedback.pushInfo(f"Mecanica 2: {actualizados_paso2} registros actualizados.")

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

        feedback.pushInfo(f"Total registros actualizados: {actualizados}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADOS: actualizados}
