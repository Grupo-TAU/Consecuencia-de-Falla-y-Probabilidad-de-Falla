from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsRendererCategory,
    QgsSpatialIndex,
    QgsSymbol,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_CLASIFICACION_DEFAULT    = "CF_Prox_SitiosInteres"
CAMPO_BUFFER_DISTANCIA_DEFAULT = "distancia_m"
CAMPO_BUFFER_CLASE_DEFAULT     = "clase_cf"

RANGOS_BUFFER_DEFAULT = [
    (50.0,  6),
    (100.0, 5),
    (200.0, 4),
    (400.0, 3),
    (800.0, 2),
]
PALETA_VERDES = {
    50.0:  "#d97706",
    100.0: "#f59e0b",
    200.0: "#fbbf24",
    400.0: "#fdae6b",
    800.0: "#fee6ce",
}

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES                = "COLECTORES"
SITIOS_INTERES            = "SITIOS_INTERES"
BUFFERS_VISIBLES          = "BUFFERS_VISIBLES"
PARAM_CAMPO_CLASIFICACION = "CAMPO_CLASIFICACION"
PARAM_RANGOS_BUFFER       = "RANGOS_BUFFER"
OUTPUT_ACTUALIZADAS       = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_rangos_buffer(text, defaults):
    if text is None or not str(text).strip():
        return defaults
    rangos = []
    for pair in str(text).split(";"):
        pair = pair.strip()
        if "=" in pair:
            dist_str, clase_str = pair.split("=", 1)
            try:
                rangos.append((float(dist_str.strip()), int(clase_str.strip())))
            except ValueError:
                continue
    return rangos if rangos else defaults


# ── Post-proceso de simbologia ────────────────────────────────────────────────

class _PostProcesoBuffersVerdes(QgsProcessingLayerPostProcessorInterface):
    _instancia      = None
    _campo_distancia = CAMPO_BUFFER_DISTANCIA_DEFAULT

    def __init__(self, campo_distancia=None):
        super().__init__()
        if campo_distancia:
            self._campo_distancia = campo_distancia

    def postProcessLayer(self, layer, context, feedback):
        if layer is None:
            return
        categorias = []
        for distancia, _ in sorted(RANGOS_BUFFER_DEFAULT, key=lambda item: item[0]):
            simbolo = QgsSymbol.defaultSymbol(layer.geometryType())
            if simbolo is None:
                continue
            simbolo.setColor(QColor(PALETA_VERDES.get(distancia, "#66c2a4")))
            categorias.append(
                QgsRendererCategory(distancia, simbolo, f"{int(distancia)} m")
            )
        if categorias:
            layer.setRenderer(QgsCategorizedSymbolRenderer(self._campo_distancia, categorias))
            layer.triggerRepaint()

    @staticmethod
    def create(campo_distancia=None):
        _PostProcesoBuffersVerdes._instancia = _PostProcesoBuffersVerdes(campo_distancia)
        return _PostProcesoBuffersVerdes._instancia


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfProxSitiosInteres(QgsProcessingAlgorithm):
    """Clasifica colectores por cercania a sitios de interés con buffers crecientes."""

    def name(self):
        return "CF_Prox_SitiosInteres"

    def displayName(self):
        return "CF Prox Sitios de Interés"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector según su proximidad a los sitios de interés. "
            "Utiliza polígonos de sitios de interés y crea buffers crecientes alrededor de cada polígono, "
            "asignando una clase al colector según el buffer más cercano que lo intersecta.\n\n"
            "El resultado se guarda en el campo configurado y además se genera una capa auxiliar con los buffers."
        )

    def createInstance(self):
        return CfProxSitiosInteres()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Colectores")
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(SITIOS_INTERES, "Sitios de interés (polígonos)")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_CLASIFICACION,
                "Nombre campo salida (CF proximidad sitio de interés)",
                defaultValue=CAMPO_CLASIFICACION_DEFAULT,
            )
        )
       
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_RANGOS_BUFFER,
                "Rango Buffers (Distancia=clase; separados por punto y coma).",
                defaultValue="; ".join(f"{int(d)}={c}" for d, c in RANGOS_BUFFER_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                BUFFERS_VISIBLES,
                "Buffers visibles (nuevas intersecciones globales)",
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        campo_clasificacion = (
            self.parameterAsString(parameters, PARAM_CAMPO_CLASIFICACION, context).strip()
            or CAMPO_CLASIFICACION_DEFAULT
        )
        campo_buffer_distancia = CAMPO_BUFFER_DISTANCIA_DEFAULT
        campo_buffer_clase = CAMPO_BUFFER_CLASE_DEFAULT
        rangos_str = self.parameterAsString(parameters, PARAM_RANGOS_BUFFER, context)
        rangos_buffer = _parse_rangos_buffer(rangos_str, RANGOS_BUFFER_DEFAULT)

        feedback.pushInfo(f"Campo clasificacion configurado: {campo_clasificacion}")
        feedback.pushInfo(
            f"Rangos buffer configurados: {', '.join(f'{int(d)}:{c}' for d, c in rangos_buffer)}"
        )

        capa_lineas = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        capa_sitios  = self.parameterAsVectorLayer(parameters, SITIOS_INTERES, context)

        if capa_lineas is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")
        if capa_sitios is None:
            raise QgsProcessingException("No se pudo leer la capa Sitios de interés.")

        if QgsWkbTypes.geometryType(capa_sitios.wkbType()) != QgsWkbTypes.PolygonGeometry:
            raise QgsProcessingException(
                "La capa Sitios de Interés debe ser de polígonos."
            )

        campos_buffers = QgsFields()
        campos_buffers.append(QgsField(campo_buffer_distancia, QVariant.Double, len=12, prec=2))
        campos_buffers.append(QgsField(campo_buffer_clase, QVariant.Int))

        sink_buffers, sink_buffers_id = self.parameterAsSink(
            parameters,
            BUFFERS_VISIBLES,
            context,
            campos_buffers,
            QgsWkbTypes.Polygon,
            capa_lineas.crs(),
        )
        if sink_buffers is None:
            raise QgsProcessingException("No se pudo crear la capa de salida de buffers visibles.")

        if context.willLoadLayerOnCompletion(sink_buffers_id):
            context.layerToLoadOnCompletionDetails(sink_buffers_id).setPostProcessor(
                _PostProcesoBuffersVerdes.create(campo_buffer_distancia)
            )

        idx_clasificacion = capa_lineas.fields().lookupField(campo_clasificacion)
        if idx_clasificacion == -1:
            if not capa_lineas.dataProvider().addAttributes(
                [QgsField(campo_clasificacion, QVariant.Int)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo {campo_clasificacion} en Colectores."
                )
            capa_lineas.updateFields()
            idx_clasificacion = capa_lineas.fields().lookupField(campo_clasificacion)

        inicio_edicion = False
        if not capa_lineas.isEditable():
            if not capa_lineas.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        features_lineas = list(capa_lineas.getFeatures())
        total           = len(features_lineas)
        if total == 0:
            if inicio_edicion:
                if not capa_lineas.commitChanges():
                    errores = "; ".join(capa_lineas.commitErrors())
                    capa_lineas.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )
            return {OUTPUT_ACTUALIZADAS: 0, BUFFERS_VISIBLES: sink_buffers_id}

        index_lineas = QgsSpatialIndex()
        geom_lineas  = {}
        for linea in features_lineas:
            if not linea.hasGeometry():
                continue
            geom_linea = linea.geometry()
            if geom_linea is None or geom_linea.isEmpty():
                continue
            linea_idx = QgsFeature(linea)
            linea_idx.setGeometry(geom_linea)
            index_lineas.addFeature(linea_idx)
            geom_lineas[linea.id()] = geom_linea

        crs_lineas  = capa_lineas.crs()
        crs_sitios  = capa_sitios.sourceCrs()
        requiere_transformacion = (
            crs_lineas.isValid() and crs_sitios.isValid() and crs_lineas != crs_sitios
        )
        transformador = None
        if requiere_transformacion:
            transformador = QgsCoordinateTransform(
                crs_sitios, crs_lineas, QgsProject.instance()
            )
            feedback.pushInfo(
                "Transformando Sitios de interés al CRS de Colectores para calcular buffers."
            )

        geometries_sitios = []
        for sitio in capa_sitios.getFeatures():
            if not sitio.hasGeometry():
                continue
            geom_sitio = sitio.geometry()
            if geom_sitio is None or geom_sitio.isEmpty():
                continue
            if requiere_transformacion:
                try:
                    geom_sitio.transform(transformador)
                except Exception as exc:
                    raise QgsProcessingException(
                        f"No se pudo transformar geometria de Sitios de interés "
                        f"(FID {sitio.id()}): {exc}"
                    ) from exc
            geometries_sitios.append(geom_sitio)

        feedback.pushInfo(f"Geometrías de sitios válidas cargadas: {len(geometries_sitios)}")

        clasificacion_por_fid        = {}
        rangos_ordenados             = sorted(rangos_buffer, key=lambda item: item[0])
        intersectados_globales       = set()
        total_lineas_intersectables  = len(geom_lineas)
        total_ops = max(len(rangos_ordenados) * max(len(geometries_sitios), 1), 1)
        ops       = 0
        cancelado = False

        actualizadas     = 0
        _fn_lin          = {capa_lineas.fields().at(i).name().lower(): i for i in range(capa_lineas.fields().count())}
        idx_id_col       = _fn_lin.get("id", -1)
        ids_actualizados = []
        try:
            # Generar TODOS los buffers de TODAS las distancias para cada polígono
            # sin importar si ya hay colectores intersectados
            for geom_sitio in geometries_sitios:
                if feedback.isCanceled():
                    cancelado = True
                    break

                for distancia, clase in rangos_ordenados:
                    if feedback.isCanceled():
                        cancelado = True
                        break

                    buffer_geom = geom_sitio.buffer(distancia, 8)
                    
                    # Agregar el buffer al sink (siempre, sin condiciones)
                    feat_buffer = QgsFeature(campos_buffers)
                    feat_buffer.setGeometry(buffer_geom)
                    feat_buffer.setAttributes([float(distancia), int(clase)])
                    sink_buffers.addFeature(feat_buffer, QgsFeatureSink.FastInsert)
                    
                    # Procesar intersecciones para clasificar colectores
                    candidatos_linea = index_lineas.intersects(buffer_geom.boundingBox())
                    for fid_linea in candidatos_linea:
                        if fid_linea in intersectados_globales:
                            continue
                        geom_linea = geom_lineas.get(fid_linea)
                        if geom_linea is not None and buffer_geom.intersects(geom_linea):
                            intersectados_globales.add(fid_linea)
                            clasificacion_por_fid[fid_linea] = clase

                    ops += 1
                    feedback.setProgress(70.0 * ops / total_ops)

                if cancelado:
                    break

            feedback.pushInfo(f"Buffers escritos al sink: {len(intersectados_globales)} colectores intersectados")

            for i, linea in enumerate(features_lineas, start=1):
                if feedback.isCanceled():
                    break
                clasificacion = clasificacion_por_fid.get(linea.id(), 1)
                if linea[idx_clasificacion] != clasificacion:
                    if not capa_lineas.changeAttributeValue(
                        linea.id(), idx_clasificacion, clasificacion
                    ):
                        raise QgsProcessingException(
                            f"No se pudo actualizar {campo_clasificacion} en FID {linea.id()}."
                        )
                    actualizadas += 1
                    col_id = str(linea[idx_id_col]).strip() if idx_id_col != -1 else str(linea.id())
                    ids_actualizados.append(col_id)
                feedback.setProgress(70.0 + (30.0 * i / total))

            if inicio_edicion:
                if not capa_lineas.commitChanges():
                    errores = "; ".join(capa_lineas.commitErrors())
                    capa_lineas.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )

        except Exception:
            if inicio_edicion and capa_lineas.isEditable():
                capa_lineas.rollBack()
            raise

        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas, BUFFERS_VISIBLES: sink_buffers_id}
