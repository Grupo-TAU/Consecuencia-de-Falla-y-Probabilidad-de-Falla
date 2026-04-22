from qgis.processing import alg
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsProcessingLayerPostProcessorInterface,
    QgsProject,
    QgsProcessingException,
    QgsRendererCategory,
    QgsSpatialIndex,
    QgsSymbol,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtCore import QVariant

CAMPO_CLASIFICACION = "CF_Prox_MedioAmbiental"
CAMPO_BUFFER_DISTANCIA = "distancia_m"
CAMPO_BUFFER_CLASE = "clase_cf"

RANGOS_BUFFER = [
    (7.0, 6),
    (15.0, 5),
    (22.0, 4),
    (30.0, 3),
    (45.0, 2),
]

PALETA_VERDES = {
    7.0: "#08306b",
    15.0: "#08519c",
    22.0: "#2171b5",
    30.0: "#6baed6",
    45.0: "#c6dbef",
}


class _PostProcesoBuffersVerdes(QgsProcessingLayerPostProcessorInterface):
    _instancia = None

    def postProcessLayer(self, layer, context, feedback):
        if layer is None:
            return

        categorias = []
        for distancia, _ in sorted(RANGOS_BUFFER, key=lambda item: item[0]):
            simbolo = QgsSymbol.defaultSymbol(layer.geometryType())
            if simbolo is None:
                continue

            simbolo.setColor(QColor(PALETA_VERDES.get(distancia, "#9ecae1")))
            categorias.append(
                QgsRendererCategory(distancia, simbolo, f"{int(distancia)} m")
            )

        if categorias:
            renderer = QgsCategorizedSymbolRenderer(CAMPO_BUFFER_DISTANCIA, categorias)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    @staticmethod
    def create():
        _PostProcesoBuffersVerdes._instancia = _PostProcesoBuffersVerdes()
        return _PostProcesoBuffersVerdes._instancia


@alg(name="CF_Prox_MedioAmbiental",
     label="CF Proximidad MedioAmbiental",
     group="personalizados",
     group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Colectores")
@alg.input(type=alg.SOURCE, name="CURSOS_AGUA", label="cursos de agua")
@alg.input(type=alg.VECTOR_LAYER_DEST, name="BUFFERS_VISIBLES", label="Buffers visibles (nuevas intersecciones globales)")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_prox_medioambiental(instance, parameters, context, feedback, inputs):
    """Clasifica colectores por proximidad a cursos de agua con buffers invertidos y salida visible."""
    capa_lineas = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
    capa_poligonos = instance.parameterAsSource(parameters, "CURSOS_AGUA", context)

    if capa_lineas is None:
        raise QgsProcessingException("No se pudo leer la capa Colectores.")
    if capa_poligonos is None:
        raise QgsProcessingException("No se pudo leer la capa cursos de agua.")

    campos_buffers = QgsFields()
    campos_buffers.append(QgsField(CAMPO_BUFFER_DISTANCIA, QVariant.Double, len=12, prec=2))
    campos_buffers.append(QgsField(CAMPO_BUFFER_CLASE, QVariant.Int))

    sink_buffers, sink_buffers_id = instance.parameterAsSink(
        parameters,
        "BUFFERS_VISIBLES",
        context,
        campos_buffers,
        QgsWkbTypes.Polygon,
        capa_lineas.crs(),
    )
    if sink_buffers is None:
        raise QgsProcessingException("No se pudo crear la capa de salida de buffers visibles.")

    if context.willLoadLayerOnCompletion(sink_buffers_id):
        detalles_carga = context.layerToLoadOnCompletionDetails(sink_buffers_id)
        detalles_carga.setPostProcessor(_PostProcesoBuffersVerdes.create())

    idx_clasificacion = capa_lineas.fields().lookupField(CAMPO_CLASIFICACION)
    if idx_clasificacion == -1:
        ok_campo = capa_lineas.dataProvider().addAttributes(
            [QgsField(CAMPO_CLASIFICACION, QVariant.Int)]
        )
        if not ok_campo:
            raise QgsProcessingException(
                f"No se pudo crear el campo {CAMPO_CLASIFICACION} en Colectores."
            )
        capa_lineas.updateFields()
        idx_clasificacion = capa_lineas.fields().lookupField(CAMPO_CLASIFICACION)

    inicio_edicion = False
    if not capa_lineas.isEditable():
        if not capa_lineas.startEditing():
            raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
        inicio_edicion = True

    features_lineas = list(capa_lineas.getFeatures())
    total = len(features_lineas)
    if total == 0:
        if inicio_edicion:
            if not capa_lineas.commitChanges():
                errores = "; ".join(capa_lineas.commitErrors())
                capa_lineas.rollBack()
                raise QgsProcessingException(
                    "No se pudieron guardar los cambios en Colectores: " + errores
                )
        return {"ACTUALIZADAS": 0, "BUFFERS_VISIBLES": sink_buffers_id}

    index_lineas = QgsSpatialIndex()
    geom_lineas = {}
    for linea in features_lineas:
        if not linea.hasGeometry():
            continue
        geom_linea = linea.geometry()
        if geom_linea is None or geom_linea.isEmpty():
            continue

        linea_indexada = QgsFeature(linea)
        linea_indexada.setGeometry(geom_linea)
        index_lineas.addFeature(linea_indexada)
        geom_lineas[linea.id()] = geom_linea

    crs_lineas = capa_lineas.crs()
    crs_poligonos = capa_poligonos.sourceCrs()
    requiere_transformacion = (
        crs_lineas.isValid()
        and crs_poligonos.isValid()
        and crs_lineas != crs_poligonos
    )

    transformador = None
    if requiere_transformacion:
        transformador = QgsCoordinateTransform(
            crs_poligonos,
            crs_lineas,
            QgsProject.instance(),
        )
        feedback.pushInfo(
            "Transformando cursos de agua al CRS de Colectores para calcular buffers."
        )

    poligonos_geom = []
    for poligono in capa_poligonos.getFeatures():
        if not poligono.hasGeometry():
            continue

        geom_poligono = poligono.geometry()
        if geom_poligono is None or geom_poligono.isEmpty():
            continue

        if requiere_transformacion:
            try:
                geom_poligono.transform(transformador)
            except Exception as exc:
                raise QgsProcessingException(
                    f"No se pudo transformar geometria de cursos de agua (FID {poligono.id()}): {exc}"
                ) from exc

        poligonos_geom.append(geom_poligono)

    clasificacion_por_fid = {}
    rangos_ordenados = sorted(RANGOS_BUFFER, key=lambda item: item[0])

    intersectados_globales = set()
    total_lineas_intersectables = len(geom_lineas)

    total_ops = max(len(rangos_ordenados) * max(len(poligonos_geom), 1), 1)
    ops = 0
    cancelado = False

    actualizadas = 0

    try:
        for distancia, clase in rangos_ordenados:
            if len(intersectados_globales) >= total_lineas_intersectables:
                feedback.pushInfo(
                    "Se detuvo la busqueda de buffers: todos los colectores con geometria ya fueron intersectados."
                )
                break

            for geom_poligono in poligonos_geom:
                if feedback.isCanceled():
                    cancelado = True
                    break

                buffer_geom = geom_poligono.buffer(distancia, 5)
                candidatos_linea = index_lineas.intersects(buffer_geom.boundingBox())

                nuevos_globales = set()
                for fid_linea in candidatos_linea:
                    if fid_linea in intersectados_globales:
                        continue

                    geom_linea = geom_lineas.get(fid_linea)
                    if geom_linea is not None and buffer_geom.intersects(geom_linea):
                        nuevos_globales.add(fid_linea)

                if nuevos_globales:
                    feat_buffer = QgsFeature(campos_buffers)
                    feat_buffer.setGeometry(buffer_geom)
                    feat_buffer.setAttributes([float(distancia), int(clase)])
                    sink_buffers.addFeature(feat_buffer, QgsFeatureSink.FastInsert)

                    for fid_linea in nuevos_globales:
                        intersectados_globales.add(fid_linea)
                        clasificacion_por_fid[fid_linea] = clase

                ops += 1
                feedback.setProgress(70.0 * ops / total_ops)

            if cancelado:
                break

        for i, linea in enumerate(features_lineas, start=1):
            if feedback.isCanceled():
                break

            clasificacion = clasificacion_por_fid.get(linea.id(), 1)

            valor_actual = linea[idx_clasificacion]
            if valor_actual != clasificacion:
                ok_update = capa_lineas.changeAttributeValue(
                    linea.id(), idx_clasificacion, clasificacion
                )
                if not ok_update:
                    raise QgsProcessingException(
                        f"No se pudo actualizar {CAMPO_CLASIFICACION} en FID {linea.id()}."
                    )
                actualizadas += 1

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

    return {"ACTUALIZADAS": actualizadas, "BUFFERS_VISIBLES": sink_buffers_id}