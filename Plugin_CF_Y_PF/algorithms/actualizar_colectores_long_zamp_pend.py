from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSource,
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


def _normalize_node(value):
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.upper() == "NULL" else 


def _to_float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_null(value):
    if value is None:
        return True
    return str(value).strip().upper() == "NULL"


def _add_field_to_layer(layer, field_name, variant_type, feedback, field_len=20, field_prec=6):
    if not layer.dataProvider().addAttributes(
        [QgsField(field_name, variant_type, len=field_len, prec=field_prec)]
    ):
        raise QgsProcessingException(
            f"No se pudo crear el campo '{field_name}' en Colectores."
        )
    layer.updateFields()
    fields = layer.fields()
    idx = _find_field_index(fields, (field_name,))
    if idx == -1:
        raise QgsProcessingException(
            f"El campo '{field_name}' no quedo disponible en Colectores."
        )
    feedback.pushInfo(f"Se creo el campo '{field_name}' en Colectores.")
    return idx, fields


# ── Defaults de campos ────────────────────────────────────────────────────────
# Colectores
CAMPO_LONGITUD_DEFAULT   = "Longitud"
CAMPO_REG_INI_DEFAULT    = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT    = "Registro_Final"
CAMPO_COTA_INI_DEFAULT   = "Registro_Inicial_Cota_Zampeado"
CAMPO_COTA_FIN_DEFAULT   = "Registro_Final_Cota_Zampeado"
CAMPO_PENDIENTE_DEFAULT  = "Pendiente"
CAMPO_PROF_SALTO_DEFAULT = "Prof_Salto"
# Registros
CAMPO_ID_REG_DEFAULT      = "ID"
CAMPO_COTA_ZAMP_DEFAULT   = "Cota_Zampeado_Calculada"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES              = "COLECTORES"
REGISTROS               = "REGISTROS"
PARAM_CAMPO_LONGITUD    = "CAMPO_LONGITUD"
PARAM_CAMPO_REG_INI     = "CAMPO_REG_INI"
PARAM_CAMPO_REG_FIN     = "CAMPO_REG_FIN"
PARAM_CAMPO_COTA_INI    = "CAMPO_COTA_INI"
PARAM_CAMPO_COTA_FIN    = "CAMPO_COTA_FIN"
PARAM_CAMPO_PENDIENTE   = "CAMPO_PENDIENTE"
PARAM_CAMPO_PROF_SALTO  = "CAMPO_PROF_SALTO"
PARAM_CAMPO_ID_REG      = "CAMPO_ID_REG"
PARAM_CAMPO_COTA_ZAMP   = "CAMPO_COTA_ZAMP"
PARAM_CAMPO_PROF_INSPEC = "CAMPO_PROF_INSPEC"
OUTPUT_ACTUALIZADAS     = "ACTUALIZADAS"


class ActualizarColectoresLongZampPend(QgsProcessingAlgorithm):
    """Actualiza Longitud, completa cotas zampeadas y recalcula pendiente en Colectores."""

    def name(self):
        return "actualizar_colectores_long_zamp_pend"

    def displayName(self):
        return "Actualizar Colectores Longitud, Cota Zampeado y Pendiente"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "<strong>Ejecuciones previas requeridas:</strong>\n"
            "  1. Asignacion de Registro Inicial y Registro Final en Colectores\n"
            "  2. Actualizar Cota Zampeado en Registros\n\n"
            "<strong>Este algoritmo:</strong>\n"
            "  - Actualiza (o crea en caso de no existir) la Longitud de los colectores desde la geometria.\n"
            "  - Copia la Cota de Zampeado de cada Registro hacia los asignados en colectores como Finales o Iniciales (solo si estan vacios).\n"
            "  - Recalcula la Pendiente \n"
            "  - Si la cota es vacia o no hay registro asignado, se omite el copiado y se usa lo el valor hayado en el campo.\n"
            "  - Si alguno de los valores de las cotas es 0, la Pendiente es 0.\n"
        )

    def createInstance(self):
        return ActualizarColectoresLongZampPend()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(REGISTROS, "Capa Registros", optional=True)
        )
        # ── Campos Colectores ──────────────────────────────────────────────────
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_LONGITUD, "Nombre del Campo Longitud de capa Colectores",
                defaultValue=CAMPO_LONGITUD_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REG_INI, "Nombre del Campo Registro Inicial de capa Colectores",
                defaultValue=CAMPO_REG_INI_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REG_FIN, "Nombre del Campo Registro Final de capa Colectores",
                defaultValue=CAMPO_REG_FIN_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_INI,
                "Nombre del Campo Cota Inicial de capa Colectores",
                defaultValue=CAMPO_COTA_INI_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_FIN,
                "Nombre del Campo Cota Final de capa Colectores",
                defaultValue=CAMPO_COTA_FIN_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PENDIENTE, "Nombre del Campo Pendiente de capa Colectores",
                defaultValue=CAMPO_PENDIENTE_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PROF_SALTO,
                "Nombre del Campo Profundidad Salto de capa Colectores",
                defaultValue=CAMPO_PROF_SALTO_DEFAULT,
                optional=True,
            )
        )
        # ── Campos Registros ───────────────────────────────────────────────────
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_ID_REG, "Nombre del Campo ID de capa Registros",
                defaultValue=CAMPO_ID_REG_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_COTA_ZAMP, "Nombre del Campo Cota Zampeado Calculada de capa Registros",
                defaultValue=CAMPO_COTA_ZAMP_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PROF_INSPEC, "Nombre del Campo Profundidad Inspeccionada de capa Registros",
                defaultValue=CAMPO_PROF_INSPEC_DEFAULT,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        colectores_layer = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        registros_source = self.parameterAsSource(parameters, REGISTROS, context)

        if colectores_layer is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        def _param(key, default):
            v = self.parameterAsString(parameters, key, context).strip()
            return v or default

        campo_longitud    = _param(PARAM_CAMPO_LONGITUD,  CAMPO_LONGITUD_DEFAULT)
        campo_reg_ini     = _param(PARAM_CAMPO_REG_INI,   CAMPO_REG_INI_DEFAULT)
        campo_reg_fin     = _param(PARAM_CAMPO_REG_FIN,   CAMPO_REG_FIN_DEFAULT)
        campo_pendiente   = _param(PARAM_CAMPO_PENDIENTE, CAMPO_PENDIENTE_DEFAULT)
        campo_prof_salto  = (self.parameterAsString(parameters, PARAM_CAMPO_PROF_SALTO, context) or "").strip()
        campo_id_reg      = _param(PARAM_CAMPO_ID_REG,    CAMPO_ID_REG_DEFAULT)
        campo_cota_zamp   = _param(PARAM_CAMPO_COTA_ZAMP, CAMPO_COTA_ZAMP_DEFAULT)
        campo_prof_inspec = _param(PARAM_CAMPO_PROF_INSPEC, CAMPO_PROF_INSPEC_DEFAULT)
        campo_cota_ini = _param(PARAM_CAMPO_COTA_INI, CAMPO_COTA_INI_DEFAULT)
        campo_cota_fin = _param(PARAM_CAMPO_COTA_FIN, CAMPO_COTA_FIN_DEFAULT)

        # can_copy_cotas: requiere capa Registros (los campos siempre estan presentes)
        can_copy_cotas = registros_source is not None
        if not can_copy_cotas:
            feedback.pushInfo("Capa Registros no proporcionada — se omite copiado de cotas.")

        colectores_fields = colectores_layer.fields()

        # ── Campos Colectores: auto-crear si no existen ────────────────────────
        idx_longitud = _find_field_index(colectores_fields, (campo_longitud,))
        if idx_longitud == -1:
            idx_longitud, colectores_fields = _add_field_to_layer(
                colectores_layer, campo_longitud, QVariant.Double, feedback,
                field_len=20, field_prec=2,
            )

        idx_pendiente = _find_field_index(colectores_fields, (campo_pendiente, "Slope", "slope"))
        if idx_pendiente == -1:
            idx_pendiente, colectores_fields = _add_field_to_layer(
                colectores_layer, campo_pendiente, QVariant.Double, feedback,
                field_len=20, field_prec=6,
            )

        # Cota ini/fin: buscar siempre (para leer en pendiente); crear solo si se va a copiar
        idx_cota_ini = _find_field_index(colectores_fields, (campo_cota_ini,)) if campo_cota_ini else -1
        idx_cota_fin = _find_field_index(colectores_fields, (campo_cota_fin,)) if campo_cota_fin else -1

        if can_copy_cotas:
            if idx_cota_ini == -1:
                idx_cota_ini, colectores_fields = _add_field_to_layer(
                    colectores_layer, campo_cota_ini, QVariant.Double, feedback,
                    field_len=20, field_prec=6,
                )
            if idx_cota_fin == -1:
                idx_cota_fin, colectores_fields = _add_field_to_layer(
                    colectores_layer, campo_cota_fin, QVariant.Double, feedback,
                    field_len=20, field_prec=6,
                )

        # Reg ini/fin: requeridos solo si se va a copiar cotas
        idx_reg_ini = _find_field_index(colectores_fields, (campo_reg_ini,))
        idx_reg_fin = _find_field_index(colectores_fields, (campo_reg_fin, "Registro_FInal"))
        if can_copy_cotas:
            for nombre, idx in [(campo_reg_ini, idx_reg_ini), (campo_reg_fin, idx_reg_fin)]:
                if idx == -1:
                    raise QgsProcessingException(
                        f"No se encontro el campo '{nombre}' en Colectores. "
                        "Ejecute primero 'Asignar Registro Inicial y Final en Colectores'."
                    )

        idx_id_col         = _find_field_index(colectores_fields, ("ID", "id"))
        idx_prof_salto_col = (
            _find_field_index(colectores_fields, (campo_prof_salto,))
            if campo_prof_salto else -1
        )
        if idx_prof_salto_col == -1 and campo_prof_salto:
            feedback.pushInfo(
                f"Campo '{campo_prof_salto}' no encontrado en Colectores — no se aplicara ajuste de salto."
            )

        # ── Construir mapas de lookup desde Registros (solo si aplica) ─────────
        mapa_cota        = {}
        mapa_prof_inspec = {}

        if can_copy_cotas:
            registros_fields  = registros_source.fields()
            idx_id_reg          = _find_field_index(registros_fields, (campo_id_reg,))
            idx_cota_reg        = _find_field_index(registros_fields, (campo_cota_zamp,))
            idx_prof_inspec_reg = _find_field_index(registros_fields, (campo_prof_inspec,))

            for nombre, idx in [(campo_id_reg, idx_id_reg), (campo_cota_zamp, idx_cota_reg)]:
                if idx == -1:
                    raise QgsProcessingException(
                        f"No se encontro el campo '{nombre}' en Registros."
                    )

            for reg_feat in registros_source.getFeatures():
                reg_id_val = _normalize_node(reg_feat[idx_id_reg])
                if not reg_id_val:
                    continue
                cota = _to_float_or_none(reg_feat[idx_cota_reg])
                if cota is not None and reg_id_val not in mapa_cota:
                    mapa_cota[reg_id_val] = cota
                if idx_prof_inspec_reg != -1:
                    prof = _to_float_or_none(reg_feat[idx_prof_inspec_reg])
                    if prof is not None and reg_id_val not in mapa_prof_inspec:
                        mapa_prof_inspec[reg_id_val] = prof

            feedback.pushInfo(f"Registros con cota zampeado disponible: {len(mapa_cota)}")

        # ── Inicio de edicion ──────────────────────────────────────────────────
        inicio_edicion = False
        if not colectores_layer.isEditable():
            if not colectores_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        try:
            colectores_list  = list(colectores_layer.getFeatures())
            total            = len(colectores_list)
            actualizadas     = 0
            ids_actualizados = []

            for i, feature in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                hubo_cambios = False

                geom = feature.geometry()
                if geom is not None and not geom.isEmpty():
                    longitud_calc   = round(float(geom.length()), 2)
                    longitud_actual = _to_float_or_none(feature[idx_longitud])
                    if longitud_actual is None or round(longitud_actual, 2) != longitud_calc:
                        feature[idx_longitud] = longitud_calc
                        hubo_cambios = True

                if can_copy_cotas:
                    reg_ini = _normalize_node(feature[idx_reg_ini])
                    reg_fin = _normalize_node(feature[idx_reg_fin])

                    if idx_cota_ini != -1 and (
                        _is_null(feature[idx_cota_ini])
                        or _to_float_or_none(feature[idx_cota_ini]) == 0
                    ):
                        cota_ini = mapa_cota.get(reg_ini)
                        if cota_ini is not None:
                            feature[idx_cota_ini] = cota_ini
                            hubo_cambios = True

                    cota_fin_recien_copiada = False
                    if idx_cota_fin != -1 and (
                        _is_null(feature[idx_cota_fin])
                        or _to_float_or_none(feature[idx_cota_fin]) == 0
                    ):
                        cota_fin = mapa_cota.get(reg_fin)
                        if cota_fin is not None:
                            feature[idx_cota_fin] = cota_fin
                            hubo_cambios = True
                            cota_fin_recien_copiada = True

                    if cota_fin_recien_copiada and idx_prof_salto_col != -1:
                        prof_salto      = _to_float_or_none(feature[idx_prof_salto_col])
                        prof_inspec_fin = mapa_prof_inspec.get(reg_fin)
                        if prof_salto is not None and prof_inspec_fin is not None:
                            feature[idx_cota_fin] = round(
                                _to_float_or_none(feature[idx_cota_fin])
                                + (prof_inspec_fin - prof_salto), 2
                            )
                            hubo_cambios = True

                # Pendiente: usar los valores que haya en los campos (copiados o preexistentes)
                cota_ini_val = _to_float_or_none(feature[idx_cota_ini]) if idx_cota_ini != -1 else None
                cota_fin_val = _to_float_or_none(feature[idx_cota_fin]) if idx_cota_fin != -1 else None
                long_aux_val = _to_float_or_none(feature[idx_longitud])

                if (
                    cota_ini_val is not None
                    and cota_fin_val is not None
                    and long_aux_val is not None
                    and abs(long_aux_val) > 1e-12
                ):
                    if cota_ini_val == 0 or cota_fin_val == 0:
                        pendiente_calc = 0.0
                    else:
                        pendiente_calc = round(
                            ((cota_ini_val - cota_fin_val) / long_aux_val) * 100.0, 2
                        )
                    pendiente_actual = _to_float_or_none(feature[idx_pendiente])
                    if pendiente_actual is None or round(pendiente_actual, 2) != pendiente_calc:
                        feature[idx_pendiente] = pendiente_calc
                        hubo_cambios = True

                if hubo_cambios:
                    if not colectores_layer.updateFeature(feature):
                        raise QgsProcessingException(
                            f"No se pudo actualizar la entidad con FID {feature.id()} en Colectores."
                        )
                    actualizadas += 1
                    col_id = str(feature[idx_id_col]).strip() if idx_id_col != -1 else str(feature.id())
                    ids_actualizados.append(col_id)

                feedback.setProgress(100.0 * i / max(total, 1))

            feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
            if ids_actualizados:
                if len(ids_actualizados) <= 50:
                    feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
                else:
                    feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")

            if inicio_edicion:
                if not colectores_layer.commitChanges():
                    errores = "; ".join(colectores_layer.commitErrors())
                    colectores_layer.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )

        except Exception:
            if inicio_edicion and colectores_layer.isEditable():
                colectores_layer.rollBack()
            raise

        return {OUTPUT_ACTUALIZADAS: actualizadas}
