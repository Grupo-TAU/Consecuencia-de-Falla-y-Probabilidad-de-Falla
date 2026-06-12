import re

from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProcessingOutputNumber,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_CF_PROFUNDIDAD            = "CF_Profundidad"
CAMPO_REGISTRO_INICIAL          = "Registro_Inicial"
CAMPO_REGISTRO_FINAL            = "Registro_Final"
CAMPO_ID_REGISTRO               = "ID"
CAMPO_PROFUNDIDAD               = "PROFUNDIDAD"
CAMPO_PROFUNDIDAD_INSPECCIONADA = "Profundidad_Inspeccionada"
RANGO_PROFUNDIDAD               = [
    (2.0, 1),
    (3.0, 2),
    (4.0, 3),
    (5.0, 4),
    (7.0, 5),
]

# ── Nombres de parametros (constantes) ────────────────────────────────────────
COLECTORES                          = "COLECTORES"
REGISTROS                           = "REGISTROS"
PARAM_CAMPO_CF_PROFUNDIDAD          = "CAMPO_CF_PROFUNDIDAD"
PARAM_CAMPO_REGISTRO_INICIAL        = "CAMPO_REGISTRO_INICIAL"
PARAM_CAMPO_REGISTRO_FINAL          = "CAMPO_REGISTRO_FINAL"
PARAM_CAMPO_ID_REGISTRO             = "CAMPO_ID_REGISTRO"
PARAM_CAMPO_PROFUNDIDAD             = "CAMPO_PROFUNDIDAD"
PARAM_CAMPO_PROFUNDIDAD_INSPECCIONADA = "CAMPO_PROFUNDIDAD_INSPECCIONADA"
PARAM_RANGO_PROFUNDIDAD             = "RANGO_PROFUNDIDAD"
OUTPUT_ACTUALIZADAS                 = "ACTUALIZADAS"


def _find_field_index(fields, candidates, partial_tokens=()):
    nombres = [fields.at(i).name() for i in range(fields.count())]
    lower_to_index = {name.lower(): i for i, name in enumerate(nombres)}
    for candidate in candidates:
        idx = lower_to_index.get(str(candidate).lower())
        if idx is not None:
            return idx
    if partial_tokens:
        for i, name in enumerate(nombres):
            lower_name = name.lower()
            if any(token in lower_name for token in partial_tokens):
                return i
    return -1


def _normalize_value(value):
    if value is None:
        return ""
    return str(value).strip()


def _to_float_or_none(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_rango_profundidad(text, defaults):
    source = str(text).strip() if text is not None else ""
    if not source:
        source = "; ".join(f"{int(lim)}={c}" for lim, c in defaults)

    limites = []
    for pair in source.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        valor_text, _, clase_text = pair.partition("=")
        try:
            limite = float(valor_text.strip().replace(",", "."))
            clase = int(clase_text.strip())
        except ValueError:
            continue
        if limite > 0:
            limites.append((limite, clase))

    if not limites:
        return _parse_rango_profundidad(None, defaults)

    return sorted(limites, key=lambda item: item[0])


def _clasificar_profundidad(profundidad, limites):
    if profundidad is None:
        return None
    for limite, clase in limites:
        if profundidad < limite:
            return clase
    return limites[-1][1] + 1


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfProfundidad(QgsProcessingAlgorithm):
    """Clasifica colectores por profundidad maxima de sus registros asociados."""

    def name(self):
        return "cf_profundidad"

    def displayName(self):
        return "CF Profundidad"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector según la mayor profundidad registrada en sus registros adyacentes." 
            "Usa el campo de profundidad de los registros y, si está disponible, también compara con la profundidad inspeccionada para tomar el valor más profundo. \n"
            "Luego clasifica el resultado en el campo configurado, usando los límites configurados en metros separados por coma. "
        )

    def createInstance(self):
        return CfProfundidad()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                COLECTORES,
                "Capa Colectores",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                REGISTROS,
                "Capa Registros",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_CF_PROFUNDIDAD,
                "Nombre de campo de salida (CF Profundidad)",
                defaultValue=CAMPO_CF_PROFUNDIDAD,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REGISTRO_INICIAL,
                "Nombre de campo Registro Inicial en capa Colectores",
                defaultValue=CAMPO_REGISTRO_INICIAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REGISTRO_FINAL,
                "Nombre de campo Registro Final en capa Colectores",
                defaultValue=CAMPO_REGISTRO_FINAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_ID_REGISTRO,
                "Nombre de campo Identidad en capa Registros",
                defaultValue=CAMPO_ID_REGISTRO,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_PROFUNDIDAD,
                "Nombre de campo Profundidad en capa Registros",
                defaultValue=CAMPO_PROFUNDIDAD,
            )
        )

        # Campo opcional: profundidad inspeccionada
        param_pi = QgsProcessingParameterString(
            PARAM_CAMPO_PROFUNDIDAD_INSPECCIONADA,
            "Nombre de campo Profundidad Inspeccionada (opcional en caso de que haya un segundo campo de registro manual)",
            defaultValue=CAMPO_PROFUNDIDAD_INSPECCIONADA,
            optional=True,
        )
        self.addParameter(param_pi)

        self.addParameter(
            QgsProcessingParameterString(
                PARAM_RANGO_PROFUNDIDAD,
                "Rango Profundidad (valor=clase; separados por punto y coma)",
                defaultValue="; ".join(f"{int(v)}={c}" for v, c in RANGO_PROFUNDIDAD),
                multiLine=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                OUTPUT_ACTUALIZADAS,
                "Cantidad de colectores actualizados",
            )
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        capa_colectores  = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        registros_source = self.parameterAsSource(parameters, REGISTROS, context)

        if capa_colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")
        if registros_source is None:
            raise QgsProcessingException("No se pudo leer la capa Registros.")

        # Parametros de texto con fallback a defaults
        campo_cf_profundidad = (
            self.parameterAsString(parameters, PARAM_CAMPO_CF_PROFUNDIDAD, context).strip()
            or CAMPO_CF_PROFUNDIDAD
        )
        campo_reg_ini = (
            self.parameterAsString(parameters, PARAM_CAMPO_REGISTRO_INICIAL, context).strip()
            or CAMPO_REGISTRO_INICIAL
        )
        campo_reg_fin = (
            self.parameterAsString(parameters, PARAM_CAMPO_REGISTRO_FINAL, context).strip()
            or CAMPO_REGISTRO_FINAL
        )
        campo_id_reg = (
            self.parameterAsString(parameters, PARAM_CAMPO_ID_REGISTRO, context).strip()
            or CAMPO_ID_REGISTRO
        )
        campo_prof = (
            self.parameterAsString(parameters, PARAM_CAMPO_PROFUNDIDAD, context).strip()
            or CAMPO_PROFUNDIDAD
        )
        campo_prof_inspec_raw = self.parameterAsString(
            parameters, PARAM_CAMPO_PROFUNDIDAD_INSPECCIONADA, context
        )
        campo_prof_inspec = (
            campo_prof_inspec_raw.strip() if campo_prof_inspec_raw else None
        ) or None

        texto_rango = self.parameterAsString(parameters, PARAM_RANGO_PROFUNDIDAD, context)
        rango_cfg   = _parse_rango_profundidad(texto_rango, RANGO_PROFUNDIDAD)

        col_fields = capa_colectores.fields()
        reg_fields = registros_source.fields()

        # Indices en Colectores
        idx_reg_ini = _find_field_index(col_fields, (campo_reg_ini,), ("registro", "inicial"))
        idx_reg_fin = _find_field_index(col_fields, (campo_reg_fin,), ("registro", "final"))
        if idx_reg_ini == -1:
            raise QgsProcessingException(
                f"No se encontro '{campo_reg_ini}' en Colectores."
            )
        if idx_reg_fin == -1:
            raise QgsProcessingException(
                f"No se encontro '{campo_reg_fin}' en Colectores."
            )

        # Indices en Registros
        idx_id_reg   = _find_field_index(reg_fields, (campo_id_reg,), ("id",))
        idx_prof_reg = _find_field_index(reg_fields, (campo_prof,), ("profundidad", "prof"))
        idx_prof_inspec = -1
        if campo_prof_inspec:
            idx_prof_inspec = _find_field_index(
                reg_fields, (campo_prof_inspec,), ("inspeccion",)
            )

        if idx_id_reg == -1:
            raise QgsProcessingException(
                f"No se encontro '{campo_id_reg}' en Registros."
            )
        if idx_prof_reg == -1:
            raise QgsProcessingException(
                f"No se encontro '{campo_prof}' en Registros."
            )

        usa_prof_inspec = idx_prof_inspec != -1

        feedback.pushInfo(f"Campo salida CF Profundidad  : {campo_cf_profundidad}")
        feedback.pushInfo(f"Registro Inicial en Colectores: {campo_reg_ini}")
        feedback.pushInfo(f"Registro Final en Colectores  : {campo_reg_fin}")
        feedback.pushInfo(f"ID en Registros               : {campo_id_reg}")
        feedback.pushInfo(f"Profundidad en Registros      : {campo_prof}")
        if usa_prof_inspec:
            feedback.pushInfo(f"Profundidad Inspeccionada     : {campo_prof_inspec}")
        else:
            feedback.pushInfo("Campo Profundidad Inspeccionada no encontrado, se usara solo Profundidad.")
        feedback.pushInfo(
            "Rango configurado: "
            + ", ".join(f"{int(lim)}={clase}" for lim, clase in rango_cfg)
        )

        # Construye mapa id_registro -> profundidad_maxima
        mapa_profundidad = {}
        for registro in registros_source.getFeatures():
            reg_id = _normalize_value(registro[idx_id_reg])
            if not reg_id:
                continue
            profundidad = _to_float_or_none(registro[idx_prof_reg])
            if usa_prof_inspec:
                prof_inspec = _to_float_or_none(registro[idx_prof_inspec])
                if prof_inspec is not None:
                    profundidad = (
                        max(profundidad, prof_inspec)
                        if profundidad is not None
                        else prof_inspec
                    )
            if profundidad is not None:
                mapa_profundidad[reg_id] = profundidad

        # Crea campo de salida si no existe
        idx_cf = col_fields.lookupField(campo_cf_profundidad)
        if idx_cf == -1:
            ok = capa_colectores.dataProvider().addAttributes(
                [QgsField(campo_cf_profundidad, QVariant.Int, len=10, prec=0)]
            )
            if not ok:
                raise QgsProcessingException(
                    f"No se pudo crear el campo {campo_cf_profundidad} en Colectores."
                )
            capa_colectores.updateFields()
            idx_cf = capa_colectores.fields().lookupField(campo_cf_profundidad)
            if idx_cf == -1:
                raise QgsProcessingException(
                    f"El campo {campo_cf_profundidad} no quedo disponible tras crearlo."
                )

        inicio_edicion = False
        if not capa_colectores.isEditable():
            if not capa_colectores.startEditing():
                raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
            inicio_edicion = True

        colectores_list = list(capa_colectores.getFeatures())
        total           = len(colectores_list)
        if total == 0:
            if inicio_edicion:
                capa_colectores.commitChanges()
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas     = 0
        ids_actualizados = []
        idx_id_col       = _find_field_index(col_fields, ("ID", "id"))
        try:
            for i, colector in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                reg_ini_id = _normalize_value(colector[idx_reg_ini])
                reg_fin_id = _normalize_value(colector[idx_reg_fin])

                prof_ini = mapa_profundidad.get(reg_ini_id)
                prof_fin = mapa_profundidad.get(reg_fin_id)

                if prof_ini is not None and prof_fin is not None:
                    profundidad_max = max(prof_ini, prof_fin)
                elif prof_ini is not None:
                    profundidad_max = prof_ini
                elif prof_fin is not None:
                    profundidad_max = prof_fin
                else:
                    profundidad_max = None

                nueva_clase  = _clasificar_profundidad(profundidad_max, rango_cfg)
                valor_actual = colector[idx_cf]

                if valor_actual != nueva_clase:
                    ok = capa_colectores.changeAttributeValue(
                        colector.id(), idx_cf, nueva_clase
                    )
                    if not ok:
                        raise QgsProcessingException(
                            f"No se pudo actualizar {campo_cf_profundidad} en FID {colector.id()}."
                        )
                    actualizadas += 1
                    col_id = str(colector[idx_id_col]).strip() if idx_id_col != -1 else str(colector.id())
                    ids_actualizados.append(col_id)

                feedback.setProgress(100.0 * i / total)

            if inicio_edicion:
                if not capa_colectores.commitChanges():
                    errores = "; ".join(capa_colectores.commitErrors())
                    capa_colectores.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )

        except Exception:
            if inicio_edicion and capa_colectores.isEditable():
                capa_colectores.rollBack()
            raise

        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas}
