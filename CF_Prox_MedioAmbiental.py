from qgis.processing import alg
from qgis.core import (
    QgsField,
    QgsProcessingException,
    QgsSpatialIndex,
)
from qgis.PyQt.QtCore import QVariant

# Nombre del campo donde guardamos la clasificacion final de proximidad ambiental.
CAMPO_CLASIFICACION = "CF_Prox_MedioAmbiental"
# Umbrales de distancia (en unidades del CRS de la capa) y clase asignada.
# Se evalua de menor a mayor distancia para quedarse con la clase mas alta posible.
RANGOS_BUFFER = [
    (7.0, 6),
    (15.0, 5),
    (22.0, 4),
    (30.0, 3),
    (45.0, 2),
]


@alg(name="CF_Prox_MedioAmbiental",
     label="CF Proximidad MedioAmbiental",
     group="personalizados",
     group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Colectores")
@alg.input(type=alg.SOURCE, name="CURSOS_AGUA", label="cursos de agua")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_prox_mediambiental(instance, parameters, context, feedback, inputs):
    """Clasifica colectores por proximidad a cursos de agua usando buffers crecientes."""

    # Leemos la capa editable de colectores y la fuente de cursos de agua desde Processing.
    capa_lineas = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
    capa_poligonos = instance.parameterAsSource(parameters, "CURSOS_AGUA", context)

    # Validamos que ambas entradas se hayan cargado correctamente.
    if capa_lineas is None:
        raise QgsProcessingException("No se pudo leer la capa Colectores.")
    if capa_poligonos is None:
        raise QgsProcessingException("No se pudo leer la capa cursos de agua.")

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
        # Refrescamos la estructura de campos para poder usar el nuevo indice.
        capa_lineas.updateFields()
        idx_clasificacion = capa_lineas.fields().lookupField(CAMPO_CLASIFICACION)

    # Iniciamos edicion solo si la capa no estaba ya en modo edicion.
    # Asi evitamos interferir con sesiones de edicion iniciadas por el usuario.
    inicio_edicion = False
    if not capa_lineas.isEditable():
        if not capa_lineas.startEditing():
            raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
        inicio_edicion = True

    # Construimos un indice espacial de poligonos para acelerar busquedas por bounding box.
    # Ademas guardamos geometria por FID para evitar pedirla repetidamente.
    index_poligonos = QgsSpatialIndex()
    geom_poligonos = {}
    for poligono in capa_poligonos.getFeatures():
        # Saltamos entidades sin geometria porque no pueden intersectar buffers.
        if not poligono.hasGeometry():
            continue
        index_poligonos.addFeature(poligono)
        geom_poligonos[poligono.id()] = poligono.geometry()

    # Cargamos lineas en memoria para conocer total y reportar progreso estable.
    features_lineas = list(capa_lineas.getFeatures())
    total = len(features_lineas)
    if total == 0:
        # Si no hay colectores, cerramos la edicion abierta por el algoritmo.
        if inicio_edicion:
            if not capa_lineas.commitChanges():
                errores = "; ".join(capa_lineas.commitErrors())
                capa_lineas.rollBack()
                raise QgsProcessingException(
                    "No se pudieron guardar los cambios en Colectores: " + errores
                )
        return {"ACTUALIZADAS": 0}

    # Contador de entidades cuyo valor final de clase cambia efectivamente.
    actualizadas = 0

    try:
        for i, linea in enumerate(features_lineas, start=1):
            # Permite cancelar el algoritmo desde la UI de Processing.
            if feedback.isCanceled():
                break

            # Clase por defecto cuando no intersecta ningun buffer hasta 45.
            clasificacion = 1
            geom_linea = linea.geometry()

            # Solo procesamos lineas con geometria valida.
            if geom_linea is not None and not geom_linea.isEmpty():
                for distancia, clase in RANGOS_BUFFER:
                    # Generamos buffer alrededor del colector para el umbral actual.
                    buffer_geom = geom_linea.buffer(distancia, 5)
                    # Filtrado rapido por caja envolvente contra el indice espacial.
                    candidatos = index_poligonos.intersects(buffer_geom.boundingBox())

                    # Confirmamos interseccion real geometrica con cada candidato.
                    intersecta = False
                    for fid_poligono in candidatos:
                        geom_poligono = geom_poligonos.get(fid_poligono)
                        if geom_poligono is not None and buffer_geom.intersects(geom_poligono):
                            intersecta = True
                            break

                    # Al primer umbral que intersecta, asignamos clase y dejamos de buscar.
                    if intersecta:
                        clasificacion = clase
                        break

            # Escribimos atributo solo si cambia, para minimizar operaciones de edicion.
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

            # Avance global del algoritmo para la barra de progreso.
            feedback.setProgress(100.0 * i / total)

        # Confirmamos cambios solo si la sesion de edicion fue abierta por este algoritmo.
        if inicio_edicion:
            if not capa_lineas.commitChanges():
                errores = "; ".join(capa_lineas.commitErrors())
                capa_lineas.rollBack()
                raise QgsProcessingException(
                    "No se pudieron guardar los cambios en Colectores: " + errores
                )

    except Exception:
        # Si ocurre cualquier error, revertimos solo nuestra sesion de edicion.
        if inicio_edicion and capa_lineas.isEditable():
            capa_lineas.rollBack()
        raise

    # Output de Processing con cantidad de colectores efectivamente modificados.
    return {"ACTUALIZADAS": actualizadas}