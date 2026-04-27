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
CAMPO_CF_DIAMETRO = "CF_Diametro"
CAMPO_DIAMETRO    = "DIAMETRO"
RANGO_DIAMETRO    = (200.0, 300.0, 400.0, 500.0, 800.0)

# ── Nombres de parametros (constantes) ────────────────────────────────────────
COLECTORES              = "COLECTORES"
PARAM_CAMPO_CF_DIAMETRO = "CAMPO_CF_DIAMETRO"
PARAM_CAMPO_DIAMETRO    = "CAMPO_DIAMETRO"
PARAM_RANGO_DIAMETRO    = "RANGO_DIAMETRO"
OUTPUT_ACTUALIZADAS     = "ACTUALIZADAS"


# ── Helpers (identicos a la version @alg) ─────────────────────────────────────

def _find_field_index(fields, field_name):
    nombres = [fields.at(i).name() for i in range(fields.count())]
    lower_to_index = {name.lower(): i for i, name in enumerate(nombres)}
    return lower_to_index.get(str(field_name).strip().lower(), -1)


def _to_mm_or_none(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"[-+]?\d[\d\.,]*", text)
    if match is None:
        return None
    number_text = match.group(0)
    if "." in number_text and "," in number_text:
        if number_text.rfind(",") > number_text.rfind("."):
            number_text = number_text.replace(".", "").replace(",", ".")
        else:
            number_text = number_text.replace(",", "")
    elif "," in number_text:
        if number_text.count(",") == 1:
            left, right = number_text.split(",")
            if len(right) == 3 and len(left) >= 1:
                number_text = left + right
            else:
                number_text = left + "." + right
        else:
            number_text = number_text.replace(",", "")
    elif "." in number_text and number_text.count(".") > 1:
        number_text = number_text.replace(".", "")
    elif "." in number_text and number_text.count(".") == 1:
        left, right = number_text.split(".")
        if len(right) == 3 and len(left) >= 1:
            number_text = left + right
    try:
        return float(number_text)
    except ValueError:
        return None


def _parse_rango_diametro(text, defaults):
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


def _clasificar_diametro(diametro_mm, limites_mm):
    for idx, limite in enumerate(limites_mm, start=1):
        if diametro_mm < limite:
            return idx
    return len(limites_mm) + 1


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfDiametro(QgsProcessingAlgorithm):
    """Clasifica colectores por diametro y escribe el resultado en CF_Diametro."""

    def name(self):
        return "cf_diametro"

    def displayName(self):
        return "CF Diametro"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector segun su diametro y escribe el resultado "
            "en el campo CF_Diametro (o el nombre configurado).\n\n"
            "Los limites de clasificacion se expresan en mm separados por coma. "
            "Con los valores por defecto (200, 300, 400, 500, 800) se generan "
            "6 clases (1 = menor a 200 mm, ..., 6 = mayor o igual a 800 mm)."
        )

    def createInstance(self):
        return CfDiametro()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                COLECTORES,
                "Capa Colectores",
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_CF_DIAMETRO,
                "Nombre campo salida (CF Diametro)",
                defaultValue=CAMPO_CF_DIAMETRO,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_DIAMETRO,
                "Nombre campo diametro (entrada)",
                defaultValue=CAMPO_DIAMETRO,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_RANGO_DIAMETRO,
                "Rango Diametro (limites mm, separados por coma)",
                defaultValue=", ".join(str(int(v)) for v in RANGO_DIAMETRO),
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
        capa_colectores = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        if capa_colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        # Parametros de texto con fallback a defaults
        campo_cf_diametro = (
            self.parameterAsString(parameters, PARAM_CAMPO_CF_DIAMETRO, context).strip()
            or CAMPO_CF_DIAMETRO
        )
        campo_diametro = (
            self.parameterAsString(parameters, PARAM_CAMPO_DIAMETRO, context).strip()
            or CAMPO_DIAMETRO
        )
        texto_rango = self.parameterAsString(parameters, PARAM_RANGO_DIAMETRO, context)
        rango_cfg   = _parse_rango_diametro(texto_rango, RANGO_DIAMETRO)

        fields      = capa_colectores.fields()
        idx_diam    = _find_field_index(fields, campo_diametro)
        if idx_diam == -1:
            raise QgsProcessingException(
                f"No se encontro el campo de diametro '{campo_diametro}' en Colectores."
            )

        feedback.pushInfo(f"Campo diametro detectado : {fields.at(idx_diam).name()}")
        feedback.pushInfo(f"Campo salida CF Diametro : {campo_cf_diametro}")
        feedback.pushInfo(
            "Rango configurado (mm): "
            + ", ".join(str(int(v)) if float(v).is_integer() else str(v) for v in rango_cfg)
        )

        # Crea el campo de salida si no existe
        idx_cf = fields.lookupField(campo_cf_diametro)
        if idx_cf == -1:
            ok = capa_colectores.dataProvider().addAttributes(
                [QgsField(campo_cf_diametro, QVariant.Int, len=10, prec=0)]
            )
            if not ok:
                raise QgsProcessingException(
                    f"No se pudo crear el campo {campo_cf_diametro} en Colectores."
                )
            capa_colectores.updateFields()
            idx_cf = capa_colectores.fields().lookupField(campo_cf_diametro)
            if idx_cf == -1:
                raise QgsProcessingException(
                    f"El campo {campo_cf_diametro} no quedo disponible tras crearlo."
                )

        inicio_edicion = False
        if not capa_colectores.isEditable():
            if not capa_colectores.startEditing():
                raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
            inicio_edicion = True

        features = list(capa_colectores.getFeatures())
        total    = len(features)
        if total == 0:
            if inicio_edicion:
                capa_colectores.commitChanges()
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas = 0
        try:
            for i, feature in enumerate(features, start=1):
                if feedback.isCanceled():
                    break

                diam_mm     = _to_mm_or_none(feature[idx_diam])
                nueva_clase = (
                    _clasificar_diametro(diam_mm, rango_cfg) if diam_mm is not None else 0
                )

                if feature[idx_cf] != nueva_clase:
                    ok = capa_colectores.changeAttributeValue(feature.id(), idx_cf, nueva_clase)
                    if not ok:
                        raise QgsProcessingException(
                            f"No se pudo actualizar {campo_cf_diametro} en FID {feature.id()}."
                        )
                    actualizadas += 1

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

        return {OUTPUT_ACTUALIZADAS: actualizadas}
