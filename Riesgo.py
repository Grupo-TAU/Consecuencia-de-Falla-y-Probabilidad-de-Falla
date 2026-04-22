from qgis.processing import alg
from qgis.core import (
    QgsField,
    QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Campo final a calcular en Colectores.
CAMPO_RIESGO = "Riesgo"

# Candidatos para detectar automaticamente los campos de entrada.
CAMPO_CF_FINAL_CANDIDATOS = (
    "CF_Final",
    "CF final",
    "cf_final",
)
CAMPO_PF_CANDIDATOS = (
    "PF",
    "pf",
)


def _find_field_index(fields, candidates, partial_tokens=(), exclude_names=()):
    """Busca un campo por candidatos exactos o, en fallback, por coincidencia parcial."""
    if isinstance(candidates, str):
        candidates = (candidates,)

    nombres = [fields.at(i).name() for i in range(fields.count())]
    lower_to_index = {name.lower(): i for i, name in enumerate(nombres)}
    exclude_lower = {str(name).lower() for name in exclude_names}

    for candidate in candidates:
        candidate_lower = str(candidate).lower()
        if candidate_lower in exclude_lower:
            continue
        idx = lower_to_index.get(candidate_lower)
        if idx is not None:
            return idx

    if partial_tokens:
        for i, name in enumerate(nombres):
            lower_name = name.lower()
            if lower_name in exclude_lower:
                continue
            if all(token in lower_name for token in partial_tokens):
                return i

    return -1


def _to_float_or_none(value):
    """Convierte valor a float, tolerando texto con coma decimal."""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _calcular_riesgo(cf_final, pf):
    """Calcula el Riesgo como suma de CF_Final + PF."""
    cf_val = _to_float_or_none(cf_final)
    pf_val = _to_float_or_none(pf)
    
    # Si ambos son None, retorna None
    if cf_val is None and pf_val is None:
        return None
    
    # Si uno es None, retorna el otro valor
    if cf_val is None:
        return pf_val
    if pf_val is None:
        return cf_val
    
    # Si ambos tienen valores, retorna la suma
    return cf_val + pf_val


@alg(name="riesgo_calculo",
     label="Riesgo Calculo",
     group="personalizados",
     group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Capa Colectores")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def riesgo_calculo(instance, parameters, context, feedback, inputs):
    """Calcula el Riesgo como suma de CF_Final + PF."""

    capa_colectores = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)

    if capa_colectores is None:
        raise QgsProcessingException("No se pudo leer la capa Colectores.")

    fields = capa_colectores.fields()

    idx_cf_final = _find_field_index(
        fields,
        CAMPO_CF_FINAL_CANDIDATOS,
        exclude_names=(CAMPO_RIESGO,),
    )
    if idx_cf_final == -1:
        idx_cf_final = _find_field_index(
            fields,
            (),
            partial_tokens=("cf", "final"),
            exclude_names=(CAMPO_RIESGO,),
        )
    if idx_cf_final == -1:
        raise QgsProcessingException(
            "No se encontro el campo CF_Final en Colectores."
        )

    idx_pf = _find_field_index(
        fields,
        CAMPO_PF_CANDIDATOS,
        exclude_names=(CAMPO_RIESGO,),
    )
    if idx_pf == -1:
        idx_pf = _find_field_index(
            fields,
            (),
            partial_tokens=("pf",),
            exclude_names=(CAMPO_RIESGO,),
        )
    if idx_pf == -1:
        raise QgsProcessingException(
            "No se encontro el campo PF en Colectores."
        )

    feedback.pushInfo(
        f"Campo CF_Final detectado: {fields.at(idx_cf_final).name()}"
    )
    feedback.pushInfo(
        f"Campo PF detectado: {fields.at(idx_pf).name()}"
    )

    # Crea campo de salida si aun no existe.
    idx_riesgo = fields.lookupField(CAMPO_RIESGO)
    if idx_riesgo == -1:
        ok = capa_colectores.dataProvider().addAttributes(
            [QgsField(CAMPO_RIESGO, QVariant.Double, len=10, prec=2)]
        )
        if not ok:
            raise QgsProcessingException(
                f"No se pudo crear el campo {CAMPO_RIESGO} en Colectores."
            )

        capa_colectores.updateFields()
        idx_riesgo = capa_colectores.fields().lookupField(CAMPO_RIESGO)
        if idx_riesgo == -1:
            raise QgsProcessingException(
                f"El campo {CAMPO_RIESGO} no quedo disponible."
            )

    inicio_edicion = False
    if not capa_colectores.isEditable():
        if not capa_colectores.startEditing():
            raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
        inicio_edicion = True

    features = list(capa_colectores.getFeatures())
    total = len(features)
    if total == 0:
        if inicio_edicion:
            if not capa_colectores.commitChanges():
                errores = "; ".join(capa_colectores.commitErrors())
                capa_colectores.rollBack()
                raise QgsProcessingException(
                    "No se pudieron guardar los cambios en Colectores: " + errores
                )
        return {"ACTUALIZADAS": 0}

    actualizadas = 0

    try:
        for i, feature in enumerate(features, start=1):
            if feedback.isCanceled():
                break

            cf_final_val = feature[idx_cf_final]
            pf_val = feature[idx_pf]
            nuevo_riesgo = _calcular_riesgo(cf_final_val, pf_val)

            valor_actual = feature[idx_riesgo]
            
            # Debug: mostrar valores para las primeras 5 features
            if i <= 5:
                feedback.pushInfo(
                    f"FID {feature.id()}: CF_Final={cf_final_val} ({type(cf_final_val)}), PF={pf_val} ({type(pf_val)}) -> Riesgo={nuevo_riesgo} (actual: {valor_actual})"
                )
            
            # Actualizar si el valor calculado es diferente al actual, o si el actual es None/NULL
            if valor_actual != nuevo_riesgo or valor_actual is None:
                ok = capa_colectores.changeAttributeValue(
                    feature.id(), idx_riesgo, nuevo_riesgo
                )
                if not ok:
                    raise QgsProcessingException(
                        f"No se pudo actualizar {CAMPO_RIESGO} en FID {feature.id()}."
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

    return {"ACTUALIZADAS": actualizadas}
