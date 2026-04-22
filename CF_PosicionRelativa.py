from qgis.processing import alg
from qgis.core import (
    QgsField,
    QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Nombres comunes para detectar automaticamente el campo de pendiente.
PENDIENTE_CANDIDATOS = ('Pendiente', 'pendiente', 'Slope', 'slope')
REGISTRO_INICIAL_CANDIDATOS = ('Registro_Inicial',)
REGISTRO_FINAL_CANDIDATOS = ('Registro_Final', 'Registro_FInal')
CAMPO_POS_REL = 'posicionRelativas'
CAMPO_POS_REL_CLAS = 'CF_PosicionRelativa'

@alg(name='calculo_PoscicionRelativa',
     label='Calculo Posicion Relativa',
     group='personalizados',
     group_label='Personalizados')
@alg.input(type=alg.VECTOR_LAYER, name='Colectores', label='Capa Colectores')
@alg.output(type=alg.NUMBER, name='ACTUALIZADAS', label='Cantidad de colectores actualizados')
def calculo_PoscicionRelativa(instance, parameters, context, feedback, inputs):
    """Calcula posicionRelativas, su clasificacion y actualiza Colectores en sitio."""

    # Convierte valores de atributos a float de forma segura.
    def to_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # Convierte a int cuando se puede, para comparar sin falsos cambios.
    def to_int_or_none(value):
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    # Asigna clase segun la tabla de posicion relativa definida por negocio.
    def clasificar_posicion_relativa(valor):
        if valor <= 10:
            return 1
        if valor <= 30:
            return 2
        if valor <= 70:
            return 3
        if valor <= 120:
            return 4
        if valor <= 150:
            return 5
        return 6

    # Normaliza IDs de registro para compararlos sin problemas de tipo o espacios.
    def normalize_node(value):
        if value is None:
            return ''
        return str(value).strip()

    # Busca el indice de un campo por candidatos exactos o por coincidencia parcial.
    def find_field_index(fields, candidates, partial_tokens=()):
        nombres = [fields.at(i).name() for i in range(fields.count())]
        lower_to_index = {n.lower(): i for i, n in enumerate(nombres)}

        for candidato in candidates:
            idx = lower_to_index.get(str(candidato).lower())
            if idx is not None:
                return idx

        if partial_tokens:
            for i, nombre in enumerate(nombres):
                nombre_lower = nombre.lower()
                if any(token in nombre_lower for token in partial_tokens):
                    return i

        return -1

    # Lee la capa editable de entrada.
    colectores_layer = instance.parameterAsVectorLayer(parameters, 'Colectores', context)
    if colectores_layer is None:
        raise QgsProcessingException('No se pudo leer la capa Colectores.')

    fields = colectores_layer.fields()

    # Sin pendiente no se puede aplicar la regla en bifurcaciones.
    pendiente_idx = find_field_index(fields, PENDIENTE_CANDIDATOS, partial_tokens=('pend',))
    if pendiente_idx == -1:
        raise QgsProcessingException(
            'No se encontro un campo de pendiente. Inclui un campo como Pendiente.'
        )

    # La conectividad de la red se define por estos dos campos de registros.
    idx_reg_ini = find_field_index(fields, REGISTRO_INICIAL_CANDIDATOS)
    idx_reg_fin = find_field_index(fields, REGISTRO_FINAL_CANDIDATOS)
    if idx_reg_ini == -1 or idx_reg_fin == -1:
        raise QgsProcessingException(
            'No se encontraron los campos Registro_Inicial y/o Registro_Final.'
        )

    inicio_edicion = False
    if not colectores_layer.isEditable():
        if not colectores_layer.startEditing():
            raise QgsProcessingException('No se pudo iniciar el modo de edicion en Colectores.')
        inicio_edicion = True

    try:
        # Crea posicionRelativas solo si no existe.
        fields = colectores_layer.fields()
        idx_pos = find_field_index(fields, (CAMPO_POS_REL,))
        if idx_pos == -1:
            if not colectores_layer.addAttribute(QgsField(CAMPO_POS_REL, QVariant.Int, len=10, prec=0)):
                raise QgsProcessingException(
                    'No se pudo crear el campo posicionRelativas en Colectores.'
                )
            colectores_layer.updateFields()
            fields = colectores_layer.fields()
            idx_pos = find_field_index(fields, (CAMPO_POS_REL,))
            if idx_pos == -1:
                raise QgsProcessingException('El campo posicionRelativas no quedo disponible.')

        # Crea la clasificacion de posicion relativa solo si no existe.
        fields = colectores_layer.fields()
        idx_pos_clas = find_field_index(fields, (CAMPO_POS_REL_CLAS,))
        if idx_pos_clas == -1:
            if not colectores_layer.addAttribute(QgsField(CAMPO_POS_REL_CLAS, QVariant.Int, len=10, prec=0)):
                raise QgsProcessingException(
                    f'No se pudo crear el campo {CAMPO_POS_REL_CLAS} en Colectores.'
                )
            colectores_layer.updateFields()
            fields = colectores_layer.fields()
            idx_pos_clas = find_field_index(fields, (CAMPO_POS_REL_CLAS,))
            if idx_pos_clas == -1:
                raise QgsProcessingException(f'El campo {CAMPO_POS_REL_CLAS} no quedo disponible.')

        # Carga todas las features para poder construir indices y resolver recursion.
        features = list(colectores_layer.getFeatures())
        total = len(features)

        # Diccionario por feature para acceso directo por ID interno.
        feature_by_id = {f.id(): f for f in features}

        # Estructuras auxiliares por segmento basadas en IDs de registros.
        start_node = {}
        end_node = {}
        pendiente = {}
        start_to_segments = {}
        end_to_segments = {}

        # Carga nodos inicial/final y pendiente por cada tramo.
        for feature in features:
            fid = feature.id()
            nodo_inicio = normalize_node(feature[idx_reg_ini])
            nodo_final = normalize_node(feature[idx_reg_fin])

            start_node[fid] = nodo_inicio
            end_node[fid] = nodo_final
            pendiente[fid] = abs(to_float(feature[pendiente_idx]))

            if nodo_inicio:
                start_to_segments.setdefault(nodo_inicio, []).append(fid)
            if nodo_final:
                end_to_segments.setdefault(nodo_final, []).append(fid)

        # incoming_by_seg: segmentos cuyo Registro_Final coincide con el Registro_Inicial actual.
        # outgoing_same_start: segmentos que salen del mismo Registro_Inicial (bifurcacion).
        incoming_by_seg = {fid: [] for fid in feature_by_id}
        outgoing_same_start = {fid: [] for fid in feature_by_id}

        # Construye conectividad usando solo columnas de registros.
        for fid in feature_by_id:
            nodo_inicio = start_node.get(fid, '')
            if not nodo_inicio:
                incoming_by_seg[fid] = []
                outgoing_same_start[fid] = [fid]
                continue

            incoming_by_seg[fid] = [
                seg_id for seg_id in end_to_segments.get(nodo_inicio, []) if seg_id != fid
            ]
            outgoing_same_start[fid] = list(start_to_segments.get(nodo_inicio, [fid]))

        # Memoizacion para evitar recalculos en recursion.
        memo = {}

        # Regla de negocio:
        # - Base: sin entrantes => 1.
        # - Sin bifurcacion: suma(entrantes) + 1.
        # - Con bifurcacion: solo el tramo de mayor pendiente recibe suma(entrantes)+1; resto = 1.
        def calcular_posicion(fid, stack):
            if fid in memo:
                return memo[fid]

            if fid in stack:
                # Corta ciclos para evitar recursion infinita.
                return 1

            stack.add(fid)

            incoming_ids = incoming_by_seg.get(fid, [])
            if not incoming_ids:
                valor = 1
            else:
                incoming_sum = sum(calcular_posicion(prev_fid, stack) for prev_fid in incoming_ids)
                outgoing_ids = outgoing_same_start.get(fid, [])

                if len(outgoing_ids) <= 1:
                    valor = incoming_sum + 1
                else:
                    outgoing_ordenados = sorted(
                        outgoing_ids,
                        # Orden descendente por pendiente; desempata por id para estabilidad.
                        key=lambda seg_id: (-pendiente.get(seg_id, 0.0), seg_id)
                    )
                    principal_id = outgoing_ordenados[0]
                    valor = incoming_sum + 1 if fid == principal_id else 1

            stack.remove(fid)
            memo[fid] = int(valor)
            return memo[fid]

        # Calcula posicion relativa para cada tramo.
        posicion_relativa = {}
        for i, feature in enumerate(features, start=1):
            if feedback.isCanceled():
                break
            fid = feature.id()
            posicion_relativa[fid] = calcular_posicion(fid, set())
            if total:
                feedback.setProgress(50.0 * i / total)

        # Actualiza el campo sobre la misma capa de Colectores.
        actualizadas = 0
        for i, feature in enumerate(features, start=1):
            if feedback.isCanceled():
                break

            nuevo_valor = int(posicion_relativa.get(feature.id(), 1))
            nueva_clasificacion = clasificar_posicion_relativa(nuevo_valor)
            valor_actual = to_int_or_none(feature[idx_pos])
            valor_actual_clas = to_int_or_none(feature[idx_pos_clas])
            if valor_actual != nuevo_valor or valor_actual_clas != nueva_clasificacion:
                feature[idx_pos] = nuevo_valor
                feature[idx_pos_clas] = nueva_clasificacion
                if not colectores_layer.updateFeature(feature):
                    raise QgsProcessingException(
                        f'No se pudo actualizar la entidad con FID {feature.id()} en Colectores.'
                    )
                actualizadas += 1

            if total:
                feedback.setProgress(50.0 + (50.0 * i / total))

        if inicio_edicion:
            if not colectores_layer.commitChanges():
                errores = '; '.join(colectores_layer.commitErrors())
                colectores_layer.rollBack()
                raise QgsProcessingException(
                    'No se pudieron guardar los cambios en Colectores: ' + errores
                )

    except Exception:
        if inicio_edicion and colectores_layer.isEditable():
            colectores_layer.rollBack()
        raise

    return {'ACTUALIZADAS': actualizadas}