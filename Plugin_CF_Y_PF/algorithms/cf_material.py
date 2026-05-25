import unicodedata

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
CAMPO_CF_MATERIAL = "CF_Material"
CAMPO_MATERIAL    = "Material"

# Mapeo por defecto: nombre del material (sin acentos, minusculas) → clase
MAPEO_DEFAULT = (
    "PE=1; "
    "PVC=3; PEAD=3; Otro Material=3; "
    "Hormigon Armado=4; "
    "Hormigon Simple=5; "
    "Mamposteria=6"
)

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES          = "COLECTORES"
PARAM_CAMPO_SALIDA  = "CAMPO_CF_MATERIAL"
PARAM_CAMPO_MAT     = "CAMPO_MATERIAL"
PARAM_MAPEO         = "MAPEO_MATERIAL"
OUTPUT_ACTUALIZADAS = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_field_index(fields, field_name):
    lower_map = {fields.at(i).name().lower(): i for i in range(fields.count())}
    return lower_map.get(str(field_name).strip().lower(), -1)


def _normalizar(texto):
    """Minusculas y sin acentos para comparacion robusta."""
    if texto is None:
        return ""
    sin_acentos = unicodedata.normalize("NFD", str(texto))
    sin_acentos = "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")
    return sin_acentos.strip().lower()


def _parse_mapeo(texto, default_str):
    """
    Parsea 'Material A=1; Material B=3; ...' en un dict {normalizado: clase}.
    Devuelve el mapeo del default si el texto esta vacio o es invalido.
    """
    fuente = texto if texto and str(texto).strip() else default_str
    mapeo  = {}
    for par in str(fuente).split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        clave, _, valor = par.partition("=")
        try:
            mapeo[_normalizar(clave)] = int(valor.strip())
        except ValueError:
            continue
    return mapeo if mapeo else _parse_mapeo(default_str, default_str)


def _clasificar_material(valor, mapeo):
    clave = _normalizar(valor)
    return mapeo.get(clave, 0)   # 0 = no reconocido


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfMaterial(QgsProcessingAlgorithm):
    """Clasifica colectores por material y escribe CF_Material."""

    def name(self):
        return "cf_material"

    def displayName(self):
        return "CF Material"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector según el material del tramo mediante una asignación de clases por material y guarda el resultado en el campo de salida.\n\n"
            "Toma el valor del campo de material, lo normaliza para ignorar mayúsculas y acentos, y lo compara con la asignación de clases por material\n"
            "El resultado se guarda en el campo de salida y los materiales no reconocidos quedan con clase 0.\n\n"
            "Mapeo por defecto:\n\n"
            "  PE=1 | PVC=3 | PEAD=3 | Otro Material=3 | Hormigon Armado=4 | Hormigon Simple=5 | Mamposteria=6\n"
            "El usuario puede configurar el mapeo ingresando pares Material=Clase separados por punto y coma.\n\n"
        )

    def createInstance(self):
        return CfMaterial()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_SALIDA,
                "Nombre campo salida (CF Material)",
                defaultValue=CAMPO_CF_MATERIAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_MAT,
                "Material ",
                defaultValue=CAMPO_MATERIAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_MAPEO,
                "Material=Clase (separado por punto y coma)",
                defaultValue=MAPEO_DEFAULT,
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
        capa = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        campo_salida = (
            self.parameterAsString(parameters, PARAM_CAMPO_SALIDA, context).strip()
            or CAMPO_CF_MATERIAL
        )
        campo_mat = (
            self.parameterAsString(parameters, PARAM_CAMPO_MAT, context).strip()
            or CAMPO_MATERIAL
        )

        mapeo = _parse_mapeo(
            self.parameterAsString(parameters, PARAM_MAPEO, context),
            MAPEO_DEFAULT,
        )

        feedback.pushInfo("Mapeo configurado:")
        for k, v in mapeo.items():
            feedback.pushInfo(f"  '{k}' → {v}")

        fields  = capa.fields()
        idx_mat = _find_field_index(fields, campo_mat)
        if idx_mat == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_mat}' en Colectores."
            )

        feedback.pushInfo(f"Campo material detectado : {fields.at(idx_mat).name()}")
        feedback.pushInfo(f"Campo salida             : {campo_salida}")

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

        features     = list(capa.getFeatures())
        total        = len(features)
        no_reconocidos = set()

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

                valor_mat   = feature[idx_mat]
                nueva_clase = _clasificar_material(valor_mat, mapeo)

                if nueva_clase == 0 and valor_mat is not None and str(valor_mat).strip():
                    no_reconocidos.add(str(valor_mat).strip())

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
        if no_reconocidos:
            feedback.pushWarning(
                "Materiales no reconocidos (quedan con clase 0): "
                + ", ".join(sorted(no_reconocidos))
            )

        return {OUTPUT_ACTUALIZADAS: actualizadas}
