import re

from qgis.core import (
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterString,
    QgsProcessingOutputNumber,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_CF_ANTIGUEDAD = "CF_Antiguedad"
CAMPO_EDAD          = "Antiguedad"

# Clase 1: 0-10 | Clase 2: 11-20 | Clase 3: 21-30 | Clase 4: 31-50 | Clase 6: >50
LIMITES_DEFAULT = [10, 20, 30, 50]
CLASES_DEFAULT  = [1,   2,  3,  4,  6]

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES           = "COLECTORES"
PARAM_CAMPO_SALIDA   = "CAMPO_CF_ANTIGUEDAD"
PARAM_CAMPO_EDAD     = "CAMPO_EDAD"
PARAM_LIMITES        = "LIMITES_EDAD"
PARAM_CLASES         = "CLASES_EDAD"
OUTPUT_ACTUALIZADAS  = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_field_index(fields, field_name):
    lower_map = {fields.at(i).name().lower(): i for i in range(fields.count())}
    return lower_map.get(str(field_name).strip().lower(), -1)


def _to_float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_enteros(texto, defaults):
    """Parsea una cadena de enteros separados por coma. Devuelve defaults si falla."""
    if not texto or not str(texto).strip():
        return list(defaults)
    numeros = re.findall(r"\d+", str(texto))
    if not numeros:
        return list(defaults)
    return [int(n) for n in numeros]


def _clasificar_antiguedad(edad, limites, clases):
    for limite, clase in zip(limites, clases):
        if edad <= limite:
            return clase
    return clases[-1]


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfAntiguedad(QgsProcessingAlgorithm):
    """Clasifica colectores por antiguedad (edad en anos) y escribe CF_Antiguedad."""

    def name(self):
        return "cf_antiguedad"

    def displayName(self):
        return "CF Antiguedad"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector segun la edad (anos) y escribe el resultado "
            "en CF_Antiguedad.\n\n"
            "Los rangos son configurables mediante dos parametros:\n"
            "  - Limites: limites superiores de cada tramo, separados por coma.\n"
            "  - Clases: valor asignado a cada tramo (debe haber un valor mas que limites).\n\n"
            "Ejemplo por defecto:\n"
            "  Limites: 10, 20, 30, 50\n"
            "  Clases:   1,  2,  3,  4,  6\n"
            "  Resultado: 0-10→1 | 11-20→2 | 21-30→3 | 31-50→4 | >50→6"
        )

    def createInstance(self):
        return CfAntiguedad()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_SALIDA,
                "Nombre campo salida (CF Antiguedad)",
                defaultValue=CAMPO_CF_ANTIGUEDAD,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_EDAD,
                "Nombre campo antiguedad (entrada)",
                defaultValue=CAMPO_EDAD,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_LIMITES,
                "Limites de antiguedad por tramo (anos, separados por coma)",
                defaultValue=", ".join(str(v) for v in LIMITES_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CLASES,
                "Clases por tramo (un valor mas que limites, separados por coma)",
                defaultValue=", ".join(str(v) for v in CLASES_DEFAULT),
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
        capa = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        campo_salida = (
            self.parameterAsString(parameters, PARAM_CAMPO_SALIDA, context).strip()
            or CAMPO_CF_ANTIGUEDAD
        )
        campo_edad = (
            self.parameterAsString(parameters, PARAM_CAMPO_EDAD, context).strip()
            or CAMPO_EDAD
        )

        limites = _parse_enteros(
            self.parameterAsString(parameters, PARAM_LIMITES, context),
            LIMITES_DEFAULT,
        )
        clases = _parse_enteros(
            self.parameterAsString(parameters, PARAM_CLASES, context),
            CLASES_DEFAULT,
        )

        if len(clases) != len(limites) + 1:
            raise QgsProcessingException(
                f"La cantidad de clases ({len(clases)}) debe ser exactamente "
                f"uno mas que la cantidad de limites ({len(limites)})."
            )

        feedback.pushInfo(
            "Limites (anos): " + ", ".join(str(v) for v in limites)
        )
        feedback.pushInfo(
            "Clases por tramo: " + ", ".join(str(v) for v in clases)
        )

        fields   = capa.fields()
        idx_edad = _find_field_index(fields, campo_edad)
        if idx_edad == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_edad}' en Colectores."
            )

        feedback.pushInfo(f"Campo edad detectado : {fields.at(idx_edad).name()}")
        feedback.pushInfo(f"Campo salida         : {campo_salida}")

        # Crear el campo de salida si no existe
        idx_cf = fields.lookupField(campo_salida)
        if idx_cf == -1:
            ok = capa.dataProvider().addAttributes(
                [QgsField(campo_salida, QVariant.Int, len=10, prec=0)]
            )
            if not ok:
                raise QgsProcessingException(
                    f"No se pudo crear el campo '{campo_salida}' en Colectores."
                )
            capa.updateFields()
            idx_cf = capa.fields().lookupField(campo_salida)
            if idx_cf == -1:
                raise QgsProcessingException(
                    f"El campo '{campo_salida}' no quedo disponible tras crearlo."
                )

        inicio_edicion = False
        if not capa.isEditable():
            if not capa.startEditing():
                raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
            inicio_edicion = True

        features = list(capa.getFeatures())
        total    = len(features)
        if total == 0:
            if inicio_edicion:
                capa.commitChanges()
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas     = 0
        ids_actualizados = []
        idx_id_col       = _find_field_index(capa.fields(), "ID")
        try:
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break

                edad        = _to_float_or_none(feature[idx_edad])
                nueva_clase = (
                    _clasificar_antiguedad(edad, limites, clases)
                    if edad is not None else 0
                )

                valor_actual = feature[idx_cf]
                if valor_actual is None or valor_actual != nueva_clase:
                    ok = capa.changeAttributeValue(feature.id(), idx_cf, nueva_clase)
                    if not ok:
                        raise QgsProcessingException(
                            f"No se pudo actualizar '{campo_salida}' en FID {feature.id()}."
                        )
                    actualizadas += 1
                    col_id = str(feature[idx_id_col]).strip() if idx_id_col != -1 else str(feature.id())
                    ids_actualizados.append(col_id)

                feedback.setProgress(100.0 * i / total)

            if inicio_edicion:
                if not capa.commitChanges():
                    errores = "; ".join(capa.commitErrors())
                    capa.rollBack()
                    raise QgsProcessingException(
                        "No se pudieron guardar los cambios en Colectores: " + errores
                    )

        except Exception:
            if inicio_edicion and capa.isEditable():
                capa.rollBack()
            raise

        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas}
