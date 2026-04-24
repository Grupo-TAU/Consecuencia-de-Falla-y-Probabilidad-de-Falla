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
import re

# Nombre del campo donde guardamos la clasificacion final.
CAMPO_CLASIFICACION_DEFAULT = "CF_Prox_ClienteImportante"
CAMPO_BUFFER_DISTANCIA_DEFAULT = "distancia_m"
CAMPO_BUFFER_CLASE_DEFAULT = "clase_cf"
# Umbrales de distancia (en unidades del CRS) y clase asignada.
# Se evalua de menor a mayor distancia para conservar la clase mas alta posible.
RANGOS_BUFFER_DEFAULT = [
    (300.0, 6),
    (1500.0, 5),
    (3000.0, 4),
    (4500.0, 3),
    (6100.0, 2),
]
PALETA_VERDES = {
    300.0: "#005a32",
    1500.0: "#238b45",
    3000.0: "#41ab5d",
    4500.0: "#74c476",
    6100.0: "#c7e9c0",
}

# Parametros configurables
PARAM_CAMPO_CLASIFICACION = "CAMPO_CLASIFICACION"
PARAM_CAMPO_BUFFER_DISTANCIA = "CAMPO_BUFFER_DISTANCIA"
PARAM_CAMPO_BUFFER_CLASE = "CAMPO_BUFFER_CLASE"
PARAM_RANGOS_BUFFER = "RANGOS_BUFFER"

def _parse_rangos_buffer(text, defaults):
    """Convierte el texto de rangos a una lista de tuplas (distancia, clase)."""
    if text is None or not str(text).strip():
        return defaults

    rangos = []
    pairs = str(text).split(',')
    for pair in pairs:
        pair = pair.strip()
        if ':' in pair:
            dist_str, clase_str = pair.split(':', 1)
            try:
                dist = float(dist_str.strip())
                clase = int(clase_str.strip())
                rangos.append((dist, clase))
            except ValueError:
                continue
    if not rangos:
        return defaults
    return rangos


class _PostProcesoBuffersVerdes(QgsProcessingLayerPostProcessorInterface):
    """Aplica simbologia categorizada por distancia con una secuencia de verdes."""

    _instancia = None
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

            color_hex = PALETA_VERDES.get(distancia, "#66c2a4")
            simbolo.setColor(QColor(color_hex))
            categorias.append(
                QgsRendererCategory(distancia, simbolo, f"{int(distancia)} m")
            )

        if categorias:
            renderer = QgsCategorizedSymbolRenderer(self._campo_distancia, categorias)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    @staticmethod
    def create(campo_distancia=None):
        _PostProcesoBuffersVerdes._instancia = _PostProcesoBuffersVerdes(campo_distancia)
        return _PostProcesoBuffersVerdes._instancia


@alg(name="CF_Prox_ClienteImportante",
     label="CF Prox Cliente Importantes",
     group="personalizados",
     group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Colectores")
@alg.input(type=alg.SOURCE, name="CLIENTES_IMPORTANTES", label="Clientes importantes")
@alg.input(
    type=alg.STRING,
    name=PARAM_CAMPO_CLASIFICACION,
    label="Nombre campo salida (CF proximidad cliente importante)",
    default=CAMPO_CLASIFICACION_DEFAULT,
)
@alg.input(
    type=alg.STRING,
    name=PARAM_CAMPO_BUFFER_DISTANCIA,
    label="Nombre campo distancia en buffers",
    default=CAMPO_BUFFER_DISTANCIA_DEFAULT,
)
@alg.input(
    type=alg.STRING,
    name=PARAM_CAMPO_BUFFER_CLASE,
    label="Nombre campo clase en buffers",
    default=CAMPO_BUFFER_CLASE_DEFAULT,
)
@alg.input(
    type=alg.STRING,
    name=PARAM_RANGOS_BUFFER,
    label="Rangos buffer (distancia:clase, separados por coma)",
    default=", ".join(f"{int(d)}:{c}" for d, c in RANGOS_BUFFER_DEFAULT),
)
@alg.input(type=alg.VECTOR_LAYER_DEST, name="BUFFERS_VISIBLES", label="Buffers visibles (nuevas intersecciones globales)")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_prox_clienteimportante(instance, parameters, context, feedback, inputs):
    """Clasifica colectores por cercania a clientes importantes con buffers crecientes."""

    # Obtener parametros configurables
    campo_clasificacion = instance.parameterAsString(parameters, PARAM_CAMPO_CLASIFICACION, context)
    campo_clasificacion = campo_clasificacion.strip() if campo_clasificacion else CAMPO_CLASIFICACION_DEFAULT

    campo_buffer_distancia = instance.parameterAsString(parameters, PARAM_CAMPO_BUFFER_DISTANCIA, context)
    campo_buffer_distancia = campo_buffer_distancia.strip() if campo_buffer_distancia else CAMPO_BUFFER_DISTANCIA_DEFAULT

    campo_buffer_clase = instance.parameterAsString(parameters, PARAM_CAMPO_BUFFER_CLASE, context)
    campo_buffer_clase = campo_buffer_clase.strip() if campo_buffer_clase else CAMPO_BUFFER_CLASE_DEFAULT

    rangos_str = instance.parameterAsString(parameters, PARAM_RANGOS_BUFFER, context)
    rangos_buffer = _parse_rangos_buffer(rangos_str, RANGOS_BUFFER_DEFAULT)

    feedback.pushInfo(f"Campo clasificacion configurado: {campo_clasificacion}")
    feedback.pushInfo(f"Campo buffer distancia: {campo_buffer_distancia}")
    feedback.pushInfo(f"Campo buffer clase: {campo_buffer_clase}")
    feedback.pushInfo(f"Rangos buffer configurados: {', '.join(f'{int(d)}:{c}' for d, c in rangos_buffer)}")

    # Leemos la capa editable de colectores y la fuente de clientes importantes.
    capa_lineas = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
    capa_puntos = instance.parameterAsSource(parameters, "CLIENTES_IMPORTANTES", context)

    # Validamos que ambas entradas se hayan cargado correctamente.
    if capa_lineas is None:
        raise QgsProcessingException("No se pudo leer la capa Colectores.")
    if capa_puntos is None:
        raise QgsProcessingException("No se pudo leer la capa Clientes importantes.")

    # Capa de salida para visualizar solo buffers que agregan intersecciones globales.
    campos_buffers = QgsFields()
    campos_buffers.append(QgsField(campo_buffer_distancia, QVariant.Double, len=12, prec=2))
    campos_buffers.append(QgsField(campo_buffer_clase, QVariant.Int))
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
        detalles_carga.setPostProcessor(_PostProcesoBuffersVerdes.create(campo_buffer_distancia))

    # Buscamos el campo de salida; si no existe, lo creamos como entero.
    idx_clasificacion = capa_lineas.fields().lookupField(campo_clasificacion)
    if idx_clasificacion == -1:
        ok_campo = capa_lineas.dataProvider().addAttributes(
            [QgsField(campo_clasificacion, QVariant.Int)]
        )
        if not ok_campo:
            raise QgsProcessingException(
                f"No se pudo crear el campo {campo_clasificacion} en Colectores."
            )
        capa_lineas.updateFields()
        idx_clasificacion = capa_lineas.fields().lookupField(campo_clasificacion)

    # Iniciamos edicion solo si la capa no estaba en modo edicion.
    inicio_edicion = False
    if not capa_lineas.isEditable():
        if not capa_lineas.startEditing():
            raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
        inicio_edicion = True

    # Cargamos colectores para conocer total y construir indice espacial de lineas.
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

    # Indice espacial y geometria cache de colectores para interseccion rapida.
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

    # Si las capas vienen en CRS distintos, transformamos puntos al CRS de colectores.
    crs_lineas = capa_lineas.crs()
    crs_puntos = capa_puntos.sourceCrs()
    requiere_transformacion = (
        crs_lineas.isValid()
        and crs_puntos.isValid()
        and crs_lineas != crs_puntos
    )

    transformador = None
    if requiere_transformacion:
        transformador = QgsCoordinateTransform(
            crs_puntos,
            crs_lineas,
            QgsProject.instance(),
        )
        feedback.pushInfo(
            "Transformando Clientes importantes al CRS de Colectores para calcular buffers."
        )

    # Guarda la primera clase asignada por distancia global (300, luego 1500, etc.).
    clasificacion_por_fid = {}

    rangos_ordenados = sorted(rangos_buffer, key=lambda item: item[0])

    # Prepara geometria de clientes importantes (en CRS de colectores) para reutilizarla.
    puntos_geom = []
    for punto in capa_puntos.getFeatures():
        if not punto.hasGeometry():
            continue

        geom_punto = punto.geometry()
        if requiere_transformacion:
            try:
                geom_punto.transform(transformador)
            except Exception as exc:
                raise QgsProcessingException(
                    f"No se pudo transformar geometria de Clientes importantes (FID {punto.id()}): {exc}"
                ) from exc

        puntos_geom.append(geom_punto)

    # Intersecciones globales: si un colector ya intersecto en una ronda anterior, no vuelve a contarse.
    intersectados_globales = set()
    total_lineas_intersectables = len(geom_lineas)

    total_ops = max(len(rangos_ordenados) * max(len(puntos_geom), 1), 1)
    ops = 0
    cancelado = False

    # 1) buffers de 300 para todos los puntos, 2) buffers de 1500 para todos, etc.
    for distancia, clase in rangos_ordenados:
        if len(intersectados_globales) >= total_lineas_intersectables:
            feedback.pushInfo(
                "Se detuvo la busqueda de buffers: todos los colectores con geometria ya fueron intersectados."
            )
            break

        for geom_punto in puntos_geom:
            if feedback.isCanceled():
                cancelado = True
                break

            buffer_geom = geom_punto.buffer(distancia, 8)
            candidatos_linea = index_lineas.intersects(buffer_geom.boundingBox())

            nuevos_globales = set()
            for fid_linea in candidatos_linea:
                if fid_linea in intersectados_globales:
                    continue

                geom_linea = geom_lineas.get(fid_linea)
                if geom_linea is not None and buffer_geom.intersects(geom_linea):
                    nuevos_globales.add(fid_linea)

            # Solo muestra buffers que aportan nuevos colectores no intersectados antes por nadie.
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

    # Contador de entidades cuyo valor final cambia.
    actualizadas = 0

    try:
        for i, linea in enumerate(features_lineas, start=1):
            if feedback.isCanceled():
                break

            # Si no intersecta ningun buffer de clientes, queda en clase 1.
            clasificacion = clasificacion_por_fid.get(linea.id(), 1)

            # Escribimos solo si el valor cambia para minimizar ediciones.
            valor_actual = linea[idx_clasificacion]
            if valor_actual != clasificacion:
                ok_update = capa_lineas.changeAttributeValue(
                    linea.id(), idx_clasificacion, clasificacion
                )
                if not ok_update:
                    raise QgsProcessingException(
                        f"No se pudo actualizar {campo_clasificacion} en FID {linea.id()}."
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