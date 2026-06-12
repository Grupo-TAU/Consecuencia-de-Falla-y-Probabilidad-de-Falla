import re

from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProcessingOutputNumber,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
PENDIENTE_CANDIDATOS_DEFAULT        = ("Pendiente",)
REGISTRO_INICIAL_CANDIDATOS_DEFAULT = ("Registro_Inicial",)
REGISTRO_FINAL_CANDIDATOS_DEFAULT   = ("Registro_Final",)
INSPECCION_CANDIDATOS_DEFAULT       = ("Inspeccion",)
INSPECCION_CORTE_VALORES            = {"AL", "EB"}
CAMPO_POS_REL_DEFAULT               = "posicionRelativa"
CAMPO_POS_REL_CLAS_DEFAULT          = "CF_PosicionRelativa"
RANGO_POS_REL_DEFAULT               = [
    (10.0, 1),
    (30.0, 2),
    (70.0, 3),
    (120.0, 4),
    (150.0, 5),
]

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES               = "Colectores"
PARAM_PENDIENTE          = "PENDIENTE"
PARAM_REG_INI            = "REG_INI"
PARAM_REG_FIN            = "REG_FIN"
PARAM_INSPECCION         = "INSPECCION"
PARAM_INSPECCION_VALORES = "INSPECCION_VALORES"
PARAM_CAMPO_POS_REL      = "CAMPO_POS_REL"
PARAM_CAMPO_POS_REL_CLAS = "CAMPO_POS_REL_CLAS"
PARAM_RANGO_POS_REL      = "RANGO_POS_REL"
OUTPUT_ACTUALIZADAS      = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_rango_pos_rel(text, defaults):
    source = str(text).strip() if text is not None else ""
    if not source:
        source = "; ".join(f"{int(valor)}={clase}" for valor, clase in defaults)

    rangos = []
    for pair in source.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        valor_text, _, clase_text = pair.partition("=")
        try:
            valor = float(valor_text.strip().replace(",", "."))
            clase = int(clase_text.strip())
        except ValueError:
            continue
        if valor > 0:
            rangos.append((valor, clase))
    if not rangos:
        return _parse_rango_pos_rel(None, defaults)
    return tuple(sorted(rangos, key=lambda item: item[0]))


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int_or_none(value):
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_node(value):
    if value is None or (hasattr(value, "isNull") and value.isNull()) or str(value).strip() == "":
        return ""
    return str(value).strip()


def _find_field_index(fields, candidates, partial_tokens=()):
    nombres = [fields.at(i).name() for i in range(fields.count())]
    lower_to_index = {n.lower(): i for i, n in enumerate(nombres)}
    for candidate in candidates:
        idx = lower_to_index.get(str(candidate).lower())
        if idx is not None:
            return idx
    if partial_tokens:
        for i, nombre in enumerate(nombres):
            if any(token in nombre.lower() for token in partial_tokens):
                return i
    return -1


def _clasificar_posicion_relativa(valor, limites):
    if valor == 0:
        return 0
    for limite, clase in limites:
        if valor <= limite:
            return clase
    return limites[-1][1] + 1


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfPosicionRelativa(QgsProcessingAlgorithm):
    """Calcula la Posicion Relativa, Clasifica y actualiza Colectores."""

    def name(self):
        return "calculo_posicion_relativa"

    def displayName(self):
        return "Calculo Posicion Relativa"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Calcula el valor de posición relativa siguiendo la red de conexiones, asignandole a cada colector el valor de la suma de la cantidad de tramos que descargan en el. \n"
            "Si hay varios colectores que parten del mismo nodo, elige el “principal” según la pendiente más alta. \n" 
            "Ignorando aquellos tramos de tipo AL o EB (u otros configurados). \n\n"
            "Escribe el valor numerico de la posicion relativa en el campo configurado y lo clasifica segun los rangos configurados"
            "en en campo configurado, donde 0=sin posicion relativa (tramos aislados), 1=posicion relativa baja, ..., n=posicion relativa alta.\n"
        )

    def createInstance(self):
        return CfPosicionRelativa()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_PENDIENTE,
                "Nombre de campo de Pendiente de capa Colectores",
                defaultValue=",".join(PENDIENTE_CANDIDATOS_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_REG_INI,
                "Nombre de campo Registro Inicial en capa Colectores",
                defaultValue=",".join(REGISTRO_INICIAL_CANDIDATOS_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_REG_FIN,
                "Nombre de campo Registro Final en capa Colectores",
                defaultValue=",".join(REGISTRO_FINAL_CANDIDATOS_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_INSPECCION,
                "Nombre de campo Tipo de Tramo (clasificacion, ej: Aliviadero AL, Estacion de bombeo EB, etc) de capa Colectores ",
                defaultValue=",".join(INSPECCION_CANDIDATOS_DEFAULT),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_INSPECCION_VALORES,
                "Valores a ignorar del campo \"Tipo de Tramo\" (separados por coma)",
                defaultValue=",".join(sorted(INSPECCION_CORTE_VALORES)),
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_POS_REL,
                "Nombre de campo salida de la Posicion (Posicion relativa)",
                defaultValue=CAMPO_POS_REL_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_POS_REL_CLAS,
                "Nombre campo salida de la Clasificacion (CF posicion relativa)",
                defaultValue=CAMPO_POS_REL_CLAS_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_RANGO_POS_REL,
                "Rango posicion relativa (valor=clase; separados por punto y coma)",
                defaultValue="; ".join(f"{int(v)}={c}" for v, c in RANGO_POS_REL_DEFAULT),
                multiLine=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        # Parametros de texto con fallback a defaults
        pendiente_str = self.parameterAsString(parameters, PARAM_PENDIENTE, context)
        pendiente_candidatos = (
            [c.strip() for c in pendiente_str.split(",") if c.strip()]
            if pendiente_str
            else list(PENDIENTE_CANDIDATOS_DEFAULT)
        )

        reg_ini_str = self.parameterAsString(parameters, PARAM_REG_INI, context)
        reg_ini_candidatos = (
            [c.strip() for c in reg_ini_str.split(",") if c.strip()]
            if reg_ini_str
            else list(REGISTRO_INICIAL_CANDIDATOS_DEFAULT)
        )

        reg_fin_str = self.parameterAsString(parameters, PARAM_REG_FIN, context)
        reg_fin_candidatos = (
            [c.strip() for c in reg_fin_str.split(",") if c.strip()]
            if reg_fin_str
            else list(REGISTRO_FINAL_CANDIDATOS_DEFAULT)
        )

        campo_pos_rel = (
            self.parameterAsString(parameters, PARAM_CAMPO_POS_REL, context).strip()
            or CAMPO_POS_REL_DEFAULT
        )
        campo_pos_rel_clas = (
            self.parameterAsString(parameters, PARAM_CAMPO_POS_REL_CLAS, context).strip()
            or CAMPO_POS_REL_CLAS_DEFAULT
        )

        rango_str     = self.parameterAsString(parameters, PARAM_RANGO_POS_REL, context)
        rango_pos_rel = _parse_rango_pos_rel(rango_str, RANGO_POS_REL_DEFAULT)

        inspeccion_str = (self.parameterAsString(parameters, PARAM_INSPECCION, context) or "").strip()
        inspeccion_candidatos = (
            [c.strip() for c in inspeccion_str.split(",") if c.strip()]
            if inspeccion_str
            else list(INSPECCION_CANDIDATOS_DEFAULT)
        )

        inspeccion_valores_str = (self.parameterAsString(parameters, PARAM_INSPECCION_VALORES, context) or "").strip()
        inspeccion_corte_valores = (
            {v.strip().upper() for v in inspeccion_valores_str.split(",") if v.strip()}
            if inspeccion_valores_str
            else set(INSPECCION_CORTE_VALORES)
        )

        feedback.pushInfo(f"Campo pendiente configurado: {', '.join(pendiente_candidatos)}")
        feedback.pushInfo(f"Campo registro inicial configurado: {', '.join(reg_ini_candidatos)}")
        feedback.pushInfo(f"Campo registro final configurado: {', '.join(reg_fin_candidatos)}")
        feedback.pushInfo(f"Campo inspeccion configurado: {', '.join(inspeccion_candidatos)}")
        feedback.pushInfo(f"Valores de corte configurados: {', '.join(sorted(inspeccion_corte_valores))}")
        feedback.pushInfo(f"Campo salida posicion relativa: {campo_pos_rel}")
        feedback.pushInfo(f"Campo salida CF posicion relativa: {campo_pos_rel_clas}")
        feedback.pushInfo(
            "Rango posicion relativa configurado: "
            + ", ".join(f"{int(valor)}={clase}" for valor, clase in rango_pos_rel)
        )

        colectores_layer = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if colectores_layer is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        fields = colectores_layer.fields()

        pendiente_idx = _find_field_index(fields, pendiente_candidatos, partial_tokens=("pend",))
        if pendiente_idx == -1:
            raise QgsProcessingException(
                "No se encontro un campo de pendiente. Inclui un campo como Pendiente."
            )

        idx_reg_ini = _find_field_index(fields, reg_ini_candidatos)
        idx_reg_fin = _find_field_index(fields, reg_fin_candidatos)
        if idx_reg_ini == -1 or idx_reg_fin == -1:
            raise QgsProcessingException(
                "No se encontraron los campos Registro_Inicial y/o Registro_Final."
            )

        inicio_edicion = False
        if not colectores_layer.isEditable():
            if not colectores_layer.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        try:
            # Crea posicionRelativa solo si no existe.
            fields   = colectores_layer.fields()
            idx_pos  = _find_field_index(fields, (campo_pos_rel,))
            if idx_pos == -1:
                if not colectores_layer.addAttribute(
                    QgsField(campo_pos_rel, QVariant.Int, len=10, prec=0)
                ):
                    raise QgsProcessingException(
                        "No se pudo crear el campo posicionRelativa en Colectores."
                    )
                colectores_layer.updateFields()
                fields  = colectores_layer.fields()
                idx_pos = _find_field_index(fields, (campo_pos_rel,))
                if idx_pos == -1:
                    raise QgsProcessingException(
                        "El campo posicionRelativa no quedo disponible."
                    )

            # Crea clasificacion de posicion relativa solo si no existe.
            fields       = colectores_layer.fields()
            idx_pos_clas = _find_field_index(fields, (campo_pos_rel_clas,))
            if idx_pos_clas == -1:
                if not colectores_layer.addAttribute(
                    QgsField(campo_pos_rel_clas, QVariant.Int, len=10, prec=0)
                ):
                    raise QgsProcessingException(
                        f"No se pudo crear el campo {campo_pos_rel_clas} en Colectores."
                    )
                colectores_layer.updateFields()
                fields       = colectores_layer.fields()
                idx_pos_clas = _find_field_index(fields, (campo_pos_rel_clas,))
                if idx_pos_clas == -1:
                    raise QgsProcessingException(
                        f"El campo {campo_pos_rel_clas} no quedo disponible."
                    )

            features       = list(colectores_layer.getFeatures())
            total          = len(features)
            feature_by_id  = {f.id(): f for f in features}

            idx_inspeccion = _find_field_index(fields, inspeccion_candidatos)
            valores_corte_str = ", ".join(sorted(inspeccion_corte_valores))
            if idx_inspeccion == -1:
                feedback.pushInfo(
                    f"Campo '{', '.join(inspeccion_candidatos)}' no encontrado: no se aplicara corte por {valores_corte_str}."
                )
            else:
                feedback.pushInfo(
                    f"Campo '{fields.at(idx_inspeccion).name()}' encontrado: se aplicara corte por {valores_corte_str}."
                )

            start_node          = {}
            end_node            = {}
            pendiente           = {}
            inspeccion_val      = {}
            start_to_segments   = {}
            end_to_segments     = {}

            for feature in features:
                fid          = feature.id()
                nodo_inicio  = _normalize_node(feature[idx_reg_ini])
                nodo_final   = _normalize_node(feature[idx_reg_fin])
                start_node[fid]  = nodo_inicio
                end_node[fid]    = nodo_final
                pendiente[fid]   = abs(_to_float(feature[pendiente_idx]))
                if idx_inspeccion != -1:
                    raw = feature[idx_inspeccion]
                    inspeccion_val[fid] = str(raw).strip().upper() if raw is not None else ""
                else:
                    inspeccion_val[fid] = ""
                if nodo_inicio:
                    start_to_segments.setdefault(nodo_inicio, []).append(fid)
                if nodo_final:
                    end_to_segments.setdefault(nodo_final, []).append(fid)

            corte_fids = {fid for fid, val in inspeccion_val.items() if val in inspeccion_corte_valores}
            if corte_fids:
                feedback.pushInfo(f"Colectores con corte ({valores_corte_str}): {len(corte_fids)}")

            incoming_by_seg       = {fid: [] for fid in feature_by_id}
            outgoing_same_start   = {fid: [] for fid in feature_by_id}

            for fid in feature_by_id:
                nodo_inicio = start_node.get(fid, "")
                if not nodo_inicio:
                    incoming_by_seg[fid]     = []
                    outgoing_same_start[fid] = [fid]
                    continue
                incoming_by_seg[fid] = [
                    seg_id for seg_id in end_to_segments.get(nodo_inicio, []) if seg_id != fid
                ]
                outgoing_same_start[fid] = list(start_to_segments.get(nodo_inicio, [fid]))

            memo = {}

            def calcular_posicion(fid, stack):
                if fid in memo:
                    return memo[fid]
                # AL/EB: corte de sumatoria — no tiene posicion relativa y no la propaga
                if fid in corte_fids:
                    memo[fid] = 0
                    return 0
                if fid in stack:
                    return 1
                stack.add(fid)
                incoming_ids = incoming_by_seg.get(fid, [])
                if not incoming_ids:
                    valor = 1
                else:
                    incoming_sum  = sum(calcular_posicion(p, stack) for p in incoming_ids)
                    outgoing_ids  = outgoing_same_start.get(fid, [])
                    if len(outgoing_ids) <= 1:
                        valor = incoming_sum + 1
                    else:
                        outgoing_ordenados = sorted(
                            outgoing_ids,
                            key=lambda seg_id: (-pendiente.get(seg_id, 0.0), seg_id),
                        )
                        principal_id = outgoing_ordenados[0]
                        valor = incoming_sum + 1 if fid == principal_id else 1
                stack.remove(fid)
                memo[fid] = int(valor)
                return memo[fid]

            posicion_relativa = {}
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break
                fid         = feature.id()
                nodo_inicio = start_node[fid]
                nodo_final  = end_node[fid]
                posicion_relativa[fid] = (
                    0 if (nodo_inicio == "" and nodo_final == "")
                    else calcular_posicion(fid, set())
                )
                if total:
                    feedback.setProgress(50.0 * i / total)

            actualizadas     = 0
            ids_actualizados = []
            idx_id_col       = _find_field_index(fields, ("ID", "id"))
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break
                nuevo_valor        = int(posicion_relativa.get(feature.id(), 1))
                nueva_clasificacion = _clasificar_posicion_relativa(nuevo_valor, rango_pos_rel)
                valor_actual       = _to_int_or_none(feature[idx_pos])
                valor_actual_clas  = _to_int_or_none(feature[idx_pos_clas])
                if valor_actual != nuevo_valor or valor_actual_clas != nueva_clasificacion:
                    feature[idx_pos]      = nuevo_valor
                    feature[idx_pos_clas] = nueva_clasificacion
                    if not colectores_layer.updateFeature(feature):
                        raise QgsProcessingException(
                            f"No se pudo actualizar la entidad con FID {feature.id()} en Colectores."
                        )
                    actualizadas += 1
                    col_id = str(feature[idx_id_col]).strip() if idx_id_col != -1 else str(feature.id())
                    ids_actualizados.append(col_id)
                if total:
                    feedback.setProgress(50.0 + (50.0 * i / total))

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

        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas}
