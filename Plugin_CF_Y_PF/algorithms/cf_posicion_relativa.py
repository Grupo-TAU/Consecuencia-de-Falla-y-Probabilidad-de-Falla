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
PENDIENTE_CANDIDATOS_DEFAULT      = ("Pendiente",)
REGISTRO_INICIAL_CANDIDATOS_DEFAULT = ("Registro_Inicial",)
REGISTRO_FINAL_CANDIDATOS_DEFAULT   = ("Registro_Final",)
CAMPO_POS_REL_DEFAULT               = "posicionRelativa"
CAMPO_POS_REL_CLAS_DEFAULT          = "CF_PosicionRelativa"
RANGO_POS_REL_DEFAULT               = (10.0, 30.0, 70.0, 120.0, 150.0)

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES             = "Colectores"
PARAM_PENDIENTE        = "PENDIENTE"
PARAM_REG_INI          = "REG_INI"
PARAM_REG_FIN          = "REG_FIN"
PARAM_CAMPO_POS_REL    = "CAMPO_POS_REL"
PARAM_CAMPO_POS_REL_CLAS = "CAMPO_POS_REL_CLAS"
PARAM_RANGO_POS_REL    = "RANGO_POS_REL"
OUTPUT_ACTUALIZADAS    = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

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
    return tuple(sorted(set(limites)))


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
    for idx, limite in enumerate(limites, start=1):
        if valor <= limite:
            return idx
    return len(limites) + 1


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfPosicionRelativa(QgsProcessingAlgorithm):
    """Calcula posicionRelativa, su clasificacion y actualiza Colectores en sitio."""

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
            "Calcula la posicion relativa de cada colector en la red a partir de "
            "la conectividad (Registro_Inicial / Registro_Final) y la pendiente. "
            "Escribe el valor numerico en 'posicionRelativa' y su clasificacion "
            "en 'CF_PosicionRelativa' (o los nombres configurados)."
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
                "Nombre campo pendiente",
                defaultValue=",".join(PENDIENTE_CANDIDATOS_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_REG_INI,
                "Nombre campo registro inicial",
                defaultValue=",".join(REGISTRO_INICIAL_CANDIDATOS_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_REG_FIN,
                "Nombre campo registro final",
                defaultValue=",".join(REGISTRO_FINAL_CANDIDATOS_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_POS_REL,
                "Nombre campo salida (posicion relativa)",
                defaultValue=CAMPO_POS_REL_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_POS_REL_CLAS,
                "Nombre campo salida (CF posicion relativa)",
                defaultValue=CAMPO_POS_REL_CLAS_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_RANGO_POS_REL,
                "Rango posicion relativa (limites, separados por coma)",
                defaultValue=", ".join(str(int(v)) for v in RANGO_POS_REL_DEFAULT),
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

        feedback.pushInfo(f"Campo pendiente configurado: {', '.join(pendiente_candidatos)}")
        feedback.pushInfo(f"Campo registro inicial configurado: {', '.join(reg_ini_candidatos)}")
        feedback.pushInfo(f"Campo registro final configurado: {', '.join(reg_fin_candidatos)}")
        feedback.pushInfo(f"Campo salida posicion relativa: {campo_pos_rel}")
        feedback.pushInfo(f"Campo salida CF posicion relativa: {campo_pos_rel_clas}")
        feedback.pushInfo(
            f"Rango posicion relativa configurado: {', '.join(str(int(v)) for v in rango_pos_rel)}"
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

            start_node          = {}
            end_node            = {}
            pendiente           = {}
            start_to_segments   = {}
            end_to_segments     = {}

            for feature in features:
                fid          = feature.id()
                nodo_inicio  = _normalize_node(feature[idx_reg_ini])
                nodo_final   = _normalize_node(feature[idx_reg_fin])
                start_node[fid]  = nodo_inicio
                end_node[fid]    = nodo_final
                pendiente[fid]   = abs(_to_float(feature[pendiente_idx]))
                if nodo_inicio:
                    start_to_segments.setdefault(nodo_inicio, []).append(fid)
                if nodo_final:
                    end_to_segments.setdefault(nodo_final, []).append(fid)

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

            actualizadas = 0
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

        return {OUTPUT_ACTUALIZADAS: actualizadas}
