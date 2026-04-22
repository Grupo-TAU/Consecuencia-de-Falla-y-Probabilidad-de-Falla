from qgis.processing import alg
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsProject,
    QgsProcessingException,
    QgsSpatialIndex,
)
from qgis.PyQt.QtCore import QVariant

# Nombre del campo donde guardamos la clasificacion final.
CAMPO_CLASIFICACION = "CF_Prox_ClienteImportante"
# Umbrales de distancia (en unidades del CRS) y clase asignada.
# Se evalua de menor a mayor distancia para conservar la clase mas alta posible.
RANGOS_BUFFER = [
    (300.0, 6),
    (1500.0, 5),
    (3000.0, 4),
    (4500.0, 3),
    (6100.0, 2),
]


@alg(name="CF_Prox_ClienteImportante",
     label="CF Prox Cliente Importantes",
     group="personalizados",
     group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Colectores")
@alg.input(type=alg.SOURCE, name="CLIENTES_IMPORTANTES", label="Clientes importantes")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_prox_clienteimportante(instance, parameters, context, feedback, inputs):
    """Clasifica colectores por cercania a clientes importantes con buffers crecientes."""

    # Leemos la capa editable de colectores y la fuente de clientes importantes.
    capa_lineas = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
    capa_puntos = instance.parameterAsSource(parameters, "CLIENTES_IMPORTANTES", context)

    # Validamos que ambas entradas se hayan cargado correctamente.
    if capa_lineas is None:
        raise QgsProcessingException("No se pudo leer la capa Colectores.")
    if capa_puntos is None:
        raise QgsProcessingException("No se pudo leer la capa Clientes importantes.")

    # Buscamos el campo de salida; si no existe, lo creamos como entero.
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

    # Iniciamos edicion solo si la capa no estaba en modo edicion.
    inicio_edicion = False
    if not capa_lineas.isEditable():
        if not capa_lineas.startEditing():
            raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
        inicio_edicion = True

    # Construimos indice espacial de puntos para acelerar la busqueda de candidatos.
    # Si las capas vienen en CRS distintos, transformamos puntos al CRS de colectores.
    index_puntos = QgsSpatialIndex()
    geom_puntos = {}
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

        # El indice debe construirse con geometria en el mismo CRS de los buffers.
        punto_indexado = QgsFeature(punto)
        punto_indexado.setGeometry(geom_punto)
        index_puntos.addFeature(punto_indexado)
        geom_puntos[punto.id()] = geom_punto

    # Cargamos lineas para conocer total y dar progreso estable.
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
        return {"ACTUALIZADAS": 0}

    # Contador de entidades cuyo valor final cambia.
    actualizadas = 0

    try:
        for i, linea in enumerate(features_lineas, start=1):
            if feedback.isCanceled():
                break

            # Clase por defecto si no contiene ningun punto hasta 6100.
            clasificacion = 1
            geom_linea = linea.geometry()

            if geom_linea is not None and not geom_linea.isEmpty():
                # Fuerza el orden por distancia ascendente, aunque la lista se edite en otro orden.
                for distancia, clase in sorted(RANGOS_BUFFER, key=lambda item: item[0]):
                    # Generamos buffer del colector y filtramos puntos por bounding box.
                    buffer_geom = geom_linea.buffer(distancia, 8)
                    candidatos = index_puntos.intersects(buffer_geom.boundingBox())

                    # Verificamos condicion geometrica final sobre candidatos.
                    contiene = False
                    for fid_punto in candidatos:
                        geom_punto = geom_puntos.get(fid_punto)
                        # intersects incluye tambien puntos justo sobre el borde del buffer.
                        if geom_punto is not None and buffer_geom.intersects(geom_punto):
                            contiene = True
                            break

                    # Al primer umbral que cumple, asignamos clase y dejamos de buscar.
                    if contiene:
                        clasificacion = clase
                        break

            # Escribimos solo si el valor cambia para minimizar ediciones.
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

            feedback.setProgress(100.0 * i / total)

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

    return {"ACTUALIZADAS": actualizadas}