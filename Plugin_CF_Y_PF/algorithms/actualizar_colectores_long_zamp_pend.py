from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorLayer,
    QgsProcessingOutputNumber,
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
    return str(value).strip()


def _to_float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_null(value):
    return value is None


# ── Constantes de parametros ───────────────────────────────────────────────────
COLECTORES      = "COLECTORES"
REGISTROS       = "REGISTROS"
OUTPUT_ACTUALIZADAS = "ACTUALIZADAS"


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
            "Actualiza el campo Longitud (desde la geometria), completa las cotas "
            "zampeadas inicial y final a partir de la capa Registros, y recalcula "
            "la pendiente de cada colector."
        )

    def createInstance(self):
        return ActualizarColectoresLongZampPend()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                COLECTORES,
                "Capa Colectores",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                REGISTROS,
                "Capa Registros",
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
        colectores_layer = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        registros_source = self.parameterAsSource(parameters, REGISTROS, context)

        if colectores_layer is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")
        if registros_source is None:
            raise QgsProcessingException("No se pudo leer la capa Registros.")

        colectores_fields = colectores_layer.fields()
        registros_fields  = registros_source.fields()

        # Si Longitud no existe, la crea automaticamente como campo Double.
        idx_longitud = _find_field_index(colectores_fields, ("Longitud", "LONGITUD", "longitud"))
        if idx_longitud == -1:
            ok_longitud = colectores_layer.dataProvider().addAttributes(
                [QgsField("Longitud", QVariant.Double, len=20, prec=2)]
            )
            if not ok_longitud:
                raise QgsProcessingException(
                    "No se pudo crear el campo Longitud en Colectores."
                )
            colectores_layer.updateFields()
            colectores_fields = colectores_layer.fields()
            idx_longitud = _find_field_index(
                colectores_fields, ("Longitud", "LONGITUD", "longitud")
            )
            if idx_longitud == -1:
                raise QgsProcessingException(
                    "El campo Longitud no quedo disponible en Colectores."
                )
            feedback.pushInfo("Se creo el campo Longitud en Colectores.")

        idx_reg_ini   = _find_field_index(colectores_fields, ("Registro_Inicial",))
        idx_reg_fin   = _find_field_index(colectores_fields, ("Registro_Final", "Registro_FInal"))
        idx_cota_ini  = _find_field_index(colectores_fields, ("Registro_Inicial_Cota_Zampeado",))
        idx_cota_fin  = _find_field_index(colectores_fields, ("Registro_Final_Cota_Zampeado",))
        idx_pendiente = _find_field_index(
            colectores_fields,
            ("Pendiente", "pendiente", "PENDIENTE", "Slope", "slope"),
        )

        idx_id_reg   = _find_field_index(registros_fields, ("ID",))
        idx_cota_reg = _find_field_index(registros_fields, ("Cota_Zampeado_Calculada",))

        required = {
            "Registro_Inicial":               idx_reg_ini,
            "Registro_Final":                 idx_reg_fin,
            "Registro_Inicial_Cota_Zampeado": idx_cota_ini,
            "Registro_Final_Cota_Zampeado":   idx_cota_fin,
            "Longitud":                       idx_longitud,
            "Pendiente/Slope":                idx_pendiente,
            "ID (Registros)":                 idx_id_reg,
            "Cota_Zampeado_Calculada":        idx_cota_reg,
        }
        missing = [name for name, idx in required.items() if idx == -1]
        if missing:
            raise QgsProcessingException(
                "Faltan columnas requeridas: " + ", ".join(missing)
            )

        # Mapa ID de registro -> cota. Si hay duplicados, conserva el primero valido.
        mapa_cota      = {}
        registros_list = list(registros_source.getFeatures())
        for i, registro in enumerate(registros_list, start=1):
            if feedback.isCanceled():
                break

            reg_id   = _normalize_node(registro[idx_id_reg])
            reg_cota = _to_float_or_none(registro[idx_cota_reg])

            if reg_id and reg_cota is not None and reg_id not in mapa_cota:
                mapa_cota[reg_id] = reg_cota

            if registros_list:
                feedback.setProgress(25.0 * i / len(registros_list))

        colectores_list = list(colectores_layer.getFeatures())
        total = len(colectores_list)
        if total == 0:
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas = 0

        inicio_edicion = False
        if not colectores_layer.isEditable():
            if not colectores_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        # Actualiza solo filas con valor nulo en cota inicial/final.
        try:
            for i, feature in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                reg_ini    = _normalize_node(feature[idx_reg_ini])
                reg_fin    = _normalize_node(feature[idx_reg_fin])
                hubo_cambios = False

                # Equivalente a round($length, 2) en expresiones de QGIS.
                geom = feature.geometry()
                if geom is not None and not geom.isEmpty():
                    longitud_calc  = round(float(geom.length()), 2)
                    longitud_actual = _to_float_or_none(feature[idx_longitud])
                    if longitud_actual is None or round(longitud_actual, 2) != longitud_calc:
                        feature[idx_longitud] = longitud_calc
                        hubo_cambios = True

                if _is_null(feature[idx_cota_ini]):
                    cota_ini = mapa_cota.get(reg_ini)
                    if cota_ini is not None:
                        feature[idx_cota_ini] = cota_ini
                        hubo_cambios = True

                if _is_null(feature[idx_cota_fin]):
                    cota_fin = mapa_cota.get(reg_fin)
                    if cota_fin is not None:
                        feature[idx_cota_fin] = cota_fin
                        hubo_cambios = True

                cota_ini_val = _to_float_or_none(feature[idx_cota_ini])
                cota_fin_val = _to_float_or_none(feature[idx_cota_fin])
                long_aux_val = _to_float_or_none(feature[idx_longitud])

                if (
                    cota_ini_val is not None
                    and cota_fin_val is not None
                    and long_aux_val is not None
                    and abs(long_aux_val) > 1e-12
                ):
                    pendiente_calc  = round(
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

                feedback.setProgress(25.0 + (75.0 * i / total))

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
