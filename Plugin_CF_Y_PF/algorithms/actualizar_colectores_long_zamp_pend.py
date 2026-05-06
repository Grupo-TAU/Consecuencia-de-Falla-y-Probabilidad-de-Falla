from qgis.core import (
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProcessingOutputNumber,
    QgsSpatialIndex,
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


def _endpoints(geom):
    """Devuelve (QgsPointXY inicio, QgsPointXY fin) del primer y ultimo vertice de la linea."""
    vertices = list(geom.vertices())
    if not vertices:
        return None, None
    return (
        QgsPointXY(vertices[0].x(),  vertices[0].y()),
        QgsPointXY(vertices[-1].x(), vertices[-1].y()),
    )


# ── Constantes de parametros ───────────────────────────────────────────────────
COLECTORES              = "COLECTORES"
REGISTROS               = "REGISTROS"
PARAM_TOLERANCIA_GEOM   = "TOLERANCIA_GEOM"
TOLERANCIA_GEOM_DEFAULT = 0.5          # metros
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
            "1) Completa Registro_Inicial / Registro_Final cuando estan en NULL, "
            "buscando el Registro (punto) mas cercano al extremo del colector "
            "dentro de la tolerancia indicada.\n\n"
            "2) Actualiza Longitud (desde la geometria).\n\n"
            "3) Completa Registro_Inicial_Cota_Zampeado y Registro_Final_Cota_Zampeado "
            "a partir de la capa Registros (solo si estan en NULL).\n\n"
            "4) Recalcula la Pendiente."
        )

    def createInstance(self):
        return ActualizarColectoresLongZampPend()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(REGISTROS, "Capa Registros")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_TOLERANCIA_GEOM,
                "Tolerancia geometrica para asignar Registro_Inicial/Final (metros)",
                defaultValue=str(TOLERANCIA_GEOM_DEFAULT),
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
        if registros_source is None:
            raise QgsProcessingException("No se pudo leer la capa Registros.")

        try:
            tolerancia = float(
                self.parameterAsString(parameters, PARAM_TOLERANCIA_GEOM, context)
                .strip().replace(",", ".")
            )
        except (ValueError, AttributeError):
            tolerancia = TOLERANCIA_GEOM_DEFAULT

        colectores_fields = colectores_layer.fields()
        registros_fields  = registros_source.fields()

        # Si Longitud no existe, la crea automaticamente como campo Double.
        idx_longitud = _find_field_index(colectores_fields, ("Longitud", "LONGITUD", "longitud"))
        if idx_longitud == -1:
            if not colectores_layer.dataProvider().addAttributes(
                [QgsField("Longitud", QVariant.Double, len=20, prec=2)]
            ):
                raise QgsProcessingException("No se pudo crear el campo Longitud en Colectores.")
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

        idx_id_reg          = _find_field_index(registros_fields, ("ID",))
        idx_cota_reg        = _find_field_index(registros_fields, ("Cota_Zampeado_Calculada",))
        idx_prof_inspec_reg = _find_field_index(
            registros_fields,
            ("Profundidad_Inspeccionada", "PROFUNDIDAD_INSPECCIONADA", "profundidad_inspeccionada"),
        )
        idx_prof_salto_col  = _find_field_index(
            colectores_fields,
            ("Prof_Salto", "PROF_SALTO", "Profundidad_Salto", "profundidad_salto", "prof_salto"),
        )
        if idx_prof_salto_col == -1:
            feedback.pushInfo(
                "Campo Prof_Salto no encontrado en Colectores — no se aplicara ajuste de salto."
            )

        required = {
            "Registro_Inicial":               idx_reg_ini,
            "Registro_Final":                 idx_reg_fin,
            "Registro_Inicial_Cota_Zampeado": idx_cota_ini,
            "Registro_Final_Cota_Zampeado":   idx_cota_fin,
            "Longitud":                       idx_longitud,
            "Pendiente/Slope":                idx_pendiente,
            "ID (Registros)":                 idx_id_reg,
        }
        missing = [name for name, idx in required.items() if idx == -1]
        if missing:
            raise QgsProcessingException(
                "Faltan columnas requeridas: " + ", ".join(missing)
            )

        # ── Inicio de edicion unico para todo el algoritmo ─────────────────────
        inicio_edicion = False
        if not colectores_layer.isEditable():
            if not colectores_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        try:
            # ── PASO 0: Completar Registro_Inicial / Registro_Final por geometria ──
            feedback.pushInfo(
                f"Paso 0: buscando registros por geometria (tolerancia={tolerancia} m)..."
            )

            # Indice espacial sobre registros
            reg_index      = QgsSpatialIndex()
            geom_reg       = {}   # fid → QgsGeometry (punto)
            id_reg         = {}   # fid → valor ID (string)
            mapa_cota      = {}   # id_string → Cota_Zampeado_Calculada
            mapa_prof_inspec = {}  # id_string → Profundidad_Inspeccionada

            for reg_feat in registros_source.getFeatures():
                if not reg_feat.hasGeometry():
                    continue
                g = reg_feat.geometry()
                if g is None or g.isEmpty():
                    continue
                reg_index.addFeature(reg_feat)
                geom_reg[reg_feat.id()] = g
                reg_id_val = _normalize_node(reg_feat[idx_id_reg])
                id_reg[reg_feat.id()] = reg_id_val
                if not reg_id_val:
                    continue
                cota = _to_float_or_none(reg_feat[idx_cota_reg])
                if cota is not None and reg_id_val not in mapa_cota:
                    mapa_cota[reg_id_val] = cota
                if idx_prof_inspec_reg != -1:
                    prof_inspec = _to_float_or_none(reg_feat[idx_prof_inspec_reg])
                    if prof_inspec is not None and reg_id_val not in mapa_prof_inspec:
                        mapa_prof_inspec[reg_id_val] = prof_inspec

            colectores_list = list(colectores_layer.getFeatures())
            total           = len(colectores_list)
            if total == 0:
                if inicio_edicion:
                    colectores_layer.commitChanges()
                return {OUTPUT_ACTUALIZADAS: 0}

            asignados_ini = 0
            asignados_fin = 0

            for i, feature in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue

                pt_ini, pt_fin = _endpoints(geom)
                if pt_ini is None:
                    continue

                reg_ini_actual = _normalize_node(feature[idx_reg_ini])
                reg_fin_actual = _normalize_node(feature[idx_reg_fin])

                # Registro_Inicial nulo → buscar el registro mas cercano al primer vertice
                if not reg_ini_actual:
                    candidatos = reg_index.nearestNeighbor(pt_ini, 1)
                    for fid in candidatos:
                        g_reg = geom_reg.get(fid)
                        if g_reg is None:
                            continue
                        dist = QgsGeometry.fromPointXY(pt_ini).distance(g_reg)
                        if dist <= tolerancia:
                            colectores_layer.changeAttributeValue(
                                feature.id(), idx_reg_ini, id_reg[fid]
                            )
                            asignados_ini += 1
                        break   # nearestNeighbor ya devuelve el mas cercano

                # Registro_Final nulo → buscar el registro mas cercano al ultimo vertice
                if not reg_fin_actual:
                    candidatos = reg_index.nearestNeighbor(pt_fin, 1)
                    for fid in candidatos:
                        g_reg = geom_reg.get(fid)
                        if g_reg is None:
                            continue
                        dist = QgsGeometry.fromPointXY(pt_fin).distance(g_reg)
                        if dist <= tolerancia:
                            colectores_layer.changeAttributeValue(
                                feature.id(), idx_reg_fin, id_reg[fid]
                            )
                            asignados_fin += 1
                        break

                feedback.setProgress(15.0 * i / total)

            feedback.pushInfo(
                f"  Registro_Inicial asignados: {asignados_ini} | "
                f"Registro_Final asignados: {asignados_fin}"
            )

            # Recarga la lista para que el paso siguiente vea los valores recien escritos
            colectores_list = list(colectores_layer.getFeatures())

            # ── PASO 1-3: Longitud, Cotas y Pendiente ─────────────────────────────
            feedback.pushInfo("Paso 1-3: actualizando Longitud, Cotas y Pendiente...")
            actualizadas = 0

            for i, feature in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                reg_ini    = _normalize_node(feature[idx_reg_ini])
                reg_fin    = _normalize_node(feature[idx_reg_fin])
                hubo_cambios = False

                geom = feature.geometry()
                if geom is not None and not geom.isEmpty():
                    longitud_calc   = round(float(geom.length()), 2)
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

                # Ajuste por Prof_Salto del colector sobre Registro_Final_Cota_Zampeado
                if idx_prof_salto_col != -1:
                    prof_salto     = _to_float_or_none(feature[idx_prof_salto_col])
                    prof_inspec_fin = mapa_prof_inspec.get(reg_fin)
                    if (
                        prof_salto is not None
                        and prof_inspec_fin is not None
                        and not _is_null(feature[idx_cota_fin])
                    ):
                        feature[idx_cota_fin] = round(
                            _to_float_or_none(feature[idx_cota_fin])
                            + (prof_inspec_fin - prof_salto), 2
                        )
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
                    pendiente_calc   = round(
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

                feedback.setProgress(15.0 + 85.0 * i / total)

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
