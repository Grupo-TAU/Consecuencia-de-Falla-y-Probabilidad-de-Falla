from qgis.processing import alg
from qgis.core import (
    QgsField,
    QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant
import re

# Nombres comunes para detectar automaticamente el campo de pendiente.
PENDIENTE_CANDIDATOS_DEFAULT = ('Pendiente',)
REGISTRO_INICIAL_CANDIDATOS_DEFAULT = ('Registro_Inicial',)
REGISTRO_FINAL_CANDIDATOS_DEFAULT = ('Registro_Final',)
CAMPO_POS_REL_DEFAULT = 'posicionRelativa'
CAMPO_POS_REL_CLAS_DEFAULT = 'CF_PosicionRelativa'
# Limites de posicion relativa para clasificacion por defecto.
RANGO_POS_REL_DEFAULT = (10.0, 30.0, 70.0, 120.0, 150.0)

# Parametros configurables en el algoritmo.
PARAM_PENDIENTE = "PENDIENTE"
PARAM_REG_INI = "REG_INI"
PARAM_REG_FIN = "REG_FIN"
PARAM_CAMPO_POS_REL = "CAMPO_POS_REL"
PARAM_CAMPO_POS_REL_CLAS = "CAMPO_POS_REL_CLAS"
PARAM_RANGO_POS_REL = "RANGO_POS_REL"

def _parse_rango_pos_rel(text, defaults):
    """Convierte el texto de rangos a una tupla de limites."""
    if text is None or not str(text).strip():
        return tuple(defaults)

    numbers = re.findall(r"[-+]?\d+(?:[\.,]\d+)?", str(text))
    if not numbers:
        return tuple(defaults)

    limites = []
    for num in numbers:
        try:
            valor = float(num.replace(",", "."))
        except ValueError:
            continue
        if valor > 0:
            limites.append(valor)

    if not limites:
        return tuple(defaults)

    # Asegura orden ascendente y evita repetidos para clasificacion estable.
    return tuple(sorted(set(limites)))

@alg(name='calculo_PoscicionRelativa',
     label='Calculo Posicion Relativa',
     group='personalizados',
     group_label='Personalizados')
@alg.input(type=alg.VECTOR_LAYER, name='Colectores', label='Capa Colectores')
@alg.input(
    type=alg.STRING,
    name=PARAM_PENDIENTE,
    label="Nombre campo pendiente",
    default=",".join(PENDIENTE_CANDIDATOS_DEFAULT),
)
@alg.input(
    type=alg.STRING,
    name=PARAM_REG_INI,
    label="Nombre campo registro inicial",
    default=",".join(REGISTRO_INICIAL_CANDIDATOS_DEFAULT),
)
@alg.input(
    type=alg.STRING,
    name=PARAM_REG_FIN,
    label="Nombre campo registro final",
    default=",".join(REGISTRO_FINAL_CANDIDATOS_DEFAULT),
)
@alg.input(
    type=alg.STRING,
    name=PARAM_CAMPO_POS_REL,
    label="Nombre campo salida (posicion relativa)",
    default=CAMPO_POS_REL_DEFAULT,
)
@alg.input(
    type=alg.STRING,
    name=PARAM_CAMPO_POS_REL_CLAS,
    label="Nombre campo salida (CF posicion relativa)",
    default=CAMPO_POS_REL_CLAS_DEFAULT,
)
@alg.input(
    type=alg.STRING,
    name=PARAM_RANGO_POS_REL,
    label="Rango posicion relativa (limites, separados por coma)",
    default=", ".join(str(int(v)) for v in RANGO_POS_REL_DEFAULT),
)
@alg.output(type=alg.NUMBER, name='ACTUALIZADAS', label='Cantidad de colectores actualizados')
def calculo_PoscicionRelativa(instance, parameters, context, feedback, inputs):
    """Calcula posicionRelativas, su clasificacion y actualiza Colectores en sitio."""

    # Obtener parametros configurables
    pendiente_str = instance.parameterAsString(parameters, PARAM_PENDIENTE, context)
    pendiente_candidatos = [c.strip() for c in pendiente_str.split(',') if c.strip()] if pendiente_str else list(PENDIENTE_CANDIDATOS_DEFAULT)

    reg_ini_str = instance.parameterAsString(parameters, PARAM_REG_INI, context)
    reg_ini_candidatos = [c.strip() for c in reg_ini_str.split(',') if c.strip()] if reg_ini_str else list(REGISTRO_INICIAL_CANDIDATOS_DEFAULT)

    reg_fin_str = instance.parameterAsString(parameters, PARAM_REG_FIN, context)
    reg_fin_candidatos = [c.strip() for c in reg_fin_str.split(',') if c.strip()] if reg_fin_str else list(REGISTRO_FINAL_CANDIDATOS_DEFAULT)

    campo_pos_rel = instance.parameterAsString(parameters, PARAM_CAMPO_POS_REL, context)
    campo_pos_rel = campo_pos_rel.strip() if campo_pos_rel else CAMPO_POS_REL_DEFAULT

    campo_pos_rel_clas = instance.parameterAsString(parameters, PARAM_CAMPO_POS_REL_CLAS, context)
    campo_pos_rel_clas = campo_pos_rel_clas.strip() if campo_pos_rel_clas else CAMPO_POS_REL_CLAS_DEFAULT

    rango_str = instance.parameterAsString(parameters, PARAM_RANGO_POS_REL, context)
    rango_pos_rel = _parse_rango_pos_rel(rango_str, RANGO_POS_REL_DEFAULT)

    feedback.pushInfo(f"Campo pendiente configurado: {', '.join(pendiente_candidatos)}")
    feedback.pushInfo(f"Campo registro inicial configurado: {', '.join(reg_ini_candidatos)}")
    feedback.pushInfo(f"Campo registro final configurado: {', '.join(reg_fin_candidatos)}")
    feedback.pushInfo(f"Campo salida posicion relativa: {campo_pos_rel}")
    feedback.pushInfo(f"Campo salida CF posicion relativa: {campo_pos_rel_clas}")
    feedback.pushInfo(f"Rango posicion relativa configurado: {', '.join(str(int(v)) for v in rango_pos_rel)}")

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
    def clasificar_posicion_relativa(valor, limites):
        if valor == 0:
            return 0
        for idx, limite in enumerate(limites, start=1):
            if valor <= limite:
                return idx
        return len(limites) + 1

    # Normaliza IDs de registro para compararlos sin problemas de tipo o espacios.
    def normalize_node(value):
        if value is None or (hasattr(value, 'isNull') and value.isNull()) or str(value).strip() == '':
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
    pendiente_idx = find_field_index(fields, pendiente_candidatos, partial_tokens=('pend',))
    if pendiente_idx == -1:
        raise QgsProcessingException(
            'No se encontro un campo de pendiente. Inclui un campo como Pendiente.'
        )

    # La conectividad de la red se define por estos dos campos de registros.
    idx_reg_ini = find_field_index(fields, reg_ini_candidatos)
    idx_reg_fin = find_field_index(fields, reg_fin_candidatos)
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
        idx_pos = find_field_index(fields, (campo_pos_rel,))
        if idx_pos == -1:
            if not colectores_layer.addAttribute(QgsField(campo_pos_rel, QVariant.Int, len=10, prec=0)):
                raise QgsProcessingException(
                    'No se pudo crear el campo posicionRelativas en Colectores.'
                )
            colectores_layer.updateFields()
            fields = colectores_layer.fields()
            idx_pos = find_field_index(fields, (campo_pos_rel,))
            if idx_pos == -1:
                raise QgsProcessingException('El campo posicionRelativas no quedo disponible.')

        # Crea la clasificacion de posicion relativa solo si no existe.
        fields = colectores_layer.fields()
        idx_pos_clas = find_field_index(fields, (campo_pos_rel_clas,))
        if idx_pos_clas == -1:
            if not colectores_layer.addAttribute(QgsField(campo_pos_rel_clas, QVariant.Int, len=10, prec=0)):
                raise QgsProcessingException(
                    f'No se pudo crear el campo {campo_pos_rel_clas} en Colectores.'
                )
            colectores_layer.updateFields()
            fields = colectores_layer.fields()
            idx_pos_clas = find_field_index(fields, (campo_pos_rel_clas,))
            if idx_pos_clas == -1:
                raise QgsProcessingException(f'El campo {campo_pos_rel_clas} no quedo disponible.')

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
            nodo_inicio = start_node[fid]
            nodo_final = end_node[fid]
            if nodo_inicio == '' and nodo_final == '':
                posicion_relativa[fid] = 0
            else:
                posicion_relativa[fid] = calcular_posicion(fid, set())
            if total:
                feedback.setProgress(50.0 * i / total)

        # Actualiza el campo sobre la misma capa de Colectores.
        actualizadas = 0
        for i, feature in enumerate(features, start=1):
            if feedback.isCanceled():
                break

            nuevo_valor = int(posicion_relativa.get(feature.id(), 1))
            nueva_clasificacion = clasificar_posicion_relativa(nuevo_valor, rango_pos_rel)
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