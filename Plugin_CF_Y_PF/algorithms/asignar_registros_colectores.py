from qgis.core import (
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
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
    s = str(value).strip()
    return "" if s.upper() == "NULL" else s


def _add_field_to_layer(layer, field_name, variant_type, feedback, field_len=20, field_prec=0):
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


def _endpoints(geom):
    vertices = list(geom.vertices())
    if not vertices:
        return None, None
    return (
        QgsPointXY(vertices[0].x(),  vertices[0].y()),
        QgsPointXY(vertices[-1].x(), vertices[-1].y()),
    )


# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_REG_INI_DEFAULT   = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT   = "Registro_Final"
CAMPO_ID_REG_DEFAULT    = "ID"
TOLERANCIA_GEOM_DEFAULT = 0.5

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES            = "COLECTORES"
REGISTROS             = "REGISTROS"
PARAM_TOLERANCIA_GEOM = "TOLERANCIA_GEOM"
PARAM_CAMPO_REG_INI   = "CAMPO_REG_INI"
PARAM_CAMPO_REG_FIN   = "CAMPO_REG_FIN"
PARAM_CAMPO_ID_REG    = "CAMPO_ID_REG"
OUTPUT_ASIGNADOS      = "ASIGNADOS"


class AsignarRegistrosColectores(QgsProcessingAlgorithm):
    """Asigna Registro_Inicial y Registro_Final en Colectores por proximidad geometrica."""

    def name(self):
        return "asignar_registros_colectores"

    def displayName(self):
        return "Asignar Registro Inicial y Final en Colectores"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Asigna un Registro Inicial y Registro Final a los Colectores cuando estan vacios, buscando el Registro mas cercano a cada extremo del colector\n"
            "Actualiza la cota de zampeado de los Registros \n"
            "Actualiza la longitud de los Colectores, Cota Zampeado y Pendiente\n"
        )

    def createInstance(self):
        return AsignarRegistrosColectores()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores"))
        self.addParameter(QgsProcessingParameterFeatureSource(REGISTROS, "Capa Registros"))
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_TOLERANCIA_GEOM,
                "Tolerancia geometrica para asignar Registro_Inicial/Final (metros)",
                defaultValue=str(TOLERANCIA_GEOM_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REG_INI,
                "Campo Registro Inicial (Colectores)",
                defaultValue=CAMPO_REG_INI_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REG_FIN,
                "Campo Registro Final (Colectores)",
                defaultValue=CAMPO_REG_FIN_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_ID_REG,
                "Campo ID (Registros)",
                defaultValue=CAMPO_ID_REG_DEFAULT,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ASIGNADOS, "Cantidad de extremos asignados")
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

        def _param(key, default):
            v = self.parameterAsString(parameters, key, context).strip()
            return v or default

        campo_reg_ini = _param(PARAM_CAMPO_REG_INI, CAMPO_REG_INI_DEFAULT)
        campo_reg_fin = _param(PARAM_CAMPO_REG_FIN, CAMPO_REG_FIN_DEFAULT)
        campo_id_reg  = _param(PARAM_CAMPO_ID_REG,  CAMPO_ID_REG_DEFAULT)

        feedback.pushInfo(f"Tolerancia geometrica : {tolerancia} m")
        feedback.pushInfo(f"Campo Registro_Inicial: {campo_reg_ini}")
        feedback.pushInfo(f"Campo Registro_Final  : {campo_reg_fin}")
        feedback.pushInfo(f"Campo ID Registros    : {campo_id_reg}")

        colectores_fields = colectores_layer.fields()
        registros_fields  = registros_source.fields()

        idx_id_reg = _find_field_index(registros_fields, (campo_id_reg,))
        if idx_id_reg == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_id_reg}' en Registros."
            )

        idx_reg_ini = _find_field_index(colectores_fields, (campo_reg_ini,))
        if idx_reg_ini == -1:
            idx_reg_ini, colectores_fields = _add_field_to_layer(
                colectores_layer, campo_reg_ini, QVariant.String, feedback,
                field_len=100, field_prec=0,
            )

        idx_reg_fin = _find_field_index(colectores_fields, (campo_reg_fin, "Registro_FInal"))
        if idx_reg_fin == -1:
            idx_reg_fin, colectores_fields = _add_field_to_layer(
                colectores_layer, campo_reg_fin, QVariant.String, feedback,
                field_len=100, field_prec=0,
            )

        inicio_edicion = False
        if not colectores_layer.isEditable():
            if not colectores_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        try:
            reg_index = QgsSpatialIndex()
            geom_reg  = {}
            id_reg    = {}

            for reg_feat in registros_source.getFeatures():
                if not reg_feat.hasGeometry():
                    continue
                g = reg_feat.geometry()
                if g is None or g.isEmpty():
                    continue
                reg_index.addFeature(reg_feat)
                geom_reg[reg_feat.id()] = g
                id_reg[reg_feat.id()]   = _normalize_node(reg_feat[idx_id_reg])

            feedback.pushInfo(f"Registros indexados: {len(geom_reg)}")

            colectores_list = list(colectores_layer.getFeatures())
            total           = len(colectores_list)
            asignados_ini   = 0
            asignados_fin   = 0

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

                if not reg_ini_actual:
                    for fid in reg_index.nearestNeighbor(pt_ini, 1):
                        g_reg = geom_reg.get(fid)
                        if g_reg is None:
                            continue
                        dist = QgsGeometry.fromPointXY(pt_ini).distance(g_reg)
                        if dist <= tolerancia:
                            colectores_layer.changeAttributeValue(
                                feature.id(), idx_reg_ini, id_reg[fid]
                            )
                            asignados_ini += 1
                        break

                if not reg_fin_actual:
                    for fid in reg_index.nearestNeighbor(pt_fin, 1):
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

                feedback.setProgress(100.0 * i / max(total, 1))

            feedback.pushInfo(f"Registro_Inicial asignados: {asignados_ini}")
            feedback.pushInfo(f"Registro_Final asignados  : {asignados_fin}")

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

        return {OUTPUT_ASIGNADOS: asignados_ini + asignados_fin}
