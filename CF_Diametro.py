import re

from qgis.processing import alg
from qgis.core import (
	QgsField,
	QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Nombre del campo de salida con la clasificacion de diametro.
CAMPO_CF_DIAMETRO = "CF_Diametro"
# Nombre del campo de diametro de entrada.
CAMPO_DIAMETRO = "DIAMETRO"
# Limites de diametro (mm) para clasificacion por defecto.
RANGO_DIAMETRO = (200.0, 300.0, 400.0, 500.0, 800.0)

# Parametros configurables en el algoritmo.
PARAM_CAMPO_CF_DIAMETRO = "CAMPO_CF_DIAMETRO"
PARAM_CAMPO_DIAMETRO = "CAMPO_DIAMETRO"
PARAM_RANGO_DIAMETRO = "RANGO_DIAMETRO"


def _find_field_index(fields, field_name):
	"""Busca un campo por nombre exacto (sin candidatos)."""
	nombres = [fields.at(i).name() for i in range(fields.count())]
	lower_to_index = {name.lower(): i for i, name in enumerate(nombres)}
	return lower_to_index.get(str(field_name).strip().lower(), -1)


def _to_mm_or_none(value):
	"""Convierte el valor de diametro a milimetros, tolerando texto como '200 mm'."""
	if value is None:
		return None

	if isinstance(value, (int, float)):
		return float(value)

	text = str(value).strip()
	if not text:
		return None

	# Extrae el primer numero, admitiendo separadores de miles/decimales.
	match = re.search(r"[-+]?\d[\d\.,]*", text)
	if match is None:
		return None

	number_text = match.group(0)

	if "." in number_text and "," in number_text:
		# Si ambos separadores aparecen, se toma el ultimo como separador decimal.
		if number_text.rfind(",") > number_text.rfind("."):
			number_text = number_text.replace(".", "").replace(",", ".")
		else:
			number_text = number_text.replace(",", "")
	elif "," in number_text:
		# Caso comun en formato local: decimal con coma.
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
	"""Convierte el texto de rangos a una tupla de limites en mm."""
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


def _clasificar_diametro(diametro_mm, limites_mm):
	"""Clasifica segun limites configurables de diametro en mm."""
	for idx, limite in enumerate(limites_mm, start=1):
		if diametro_mm < limite:
			return idx
	return len(limites_mm) + 1


@alg(name="cf_diametro",
	 label="CF Diametro",
	 group="personalizados",
	 group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Capa Colectores")
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_CF_DIAMETRO,
	label="Nombre campo salida (CF diametro)",
	default=CAMPO_CF_DIAMETRO,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_DIAMETRO,
	label="Nombre campo diametro (entrada)",
	default=CAMPO_DIAMETRO,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_RANGO_DIAMETRO,
	label="Rango_Diametro (limites mm, separados por coma)",
	default=", ".join(str(int(v)) for v in RANGO_DIAMETRO),
)
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_diametro(instance, parameters, context, feedback, inputs):
	"""Clasifica colectores por diametro y escribe el resultado en CF_Diametro."""

	capa_colectores = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)

	if capa_colectores is None:
		raise QgsProcessingException("No se pudo leer la capa Colectores.")

	campo_cf_diametro = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_CF_DIAMETRO,
		context,
	)
	campo_cf_diametro = campo_cf_diametro.strip() if campo_cf_diametro is not None else ""
	if not campo_cf_diametro:
		campo_cf_diametro = CAMPO_CF_DIAMETRO

	campo_diametro = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_DIAMETRO,
		context,
	)
	campo_diametro = campo_diametro.strip() if campo_diametro is not None else ""
	if not campo_diametro:
		campo_diametro = CAMPO_DIAMETRO

	texto_rango_diametro = instance.parameterAsString(
		parameters,
		PARAM_RANGO_DIAMETRO,
		context,
	)
	rango_diametro_cfg = _parse_rango_diametro(texto_rango_diametro, RANGO_DIAMETRO)

	fields = capa_colectores.fields()

	idx_diametro = _find_field_index(fields, campo_diametro)
	if idx_diametro == -1:
		raise QgsProcessingException(
			f"No se encontro el campo de diametro '{campo_diametro}' en Colectores."
		)

	feedback.pushInfo(
		f"Campo de diametro detectado: {fields.at(idx_diametro).name()}"
	)
	feedback.pushInfo(
		f"Campo de diametro configurado: {campo_diametro}"
	)
	feedback.pushInfo(
		f"Campo de salida configurado: {campo_cf_diametro}"
	)
	feedback.pushInfo(
		"Rango_Diametro configurado (mm): "
		+ ", ".join(
			str(int(v)) if float(v).is_integer() else str(v)
			for v in rango_diametro_cfg
		)
	)

	# Crea campo de salida si aun no existe.
	idx_cf_diametro = fields.lookupField(campo_cf_diametro)
	if idx_cf_diametro == -1:
		ok = capa_colectores.dataProvider().addAttributes(
			[QgsField(campo_cf_diametro, QVariant.Int, len=10, prec=0)]
		)
		if not ok:
			raise QgsProcessingException(
				f"No se pudo crear el campo {campo_cf_diametro} en Colectores."
			)

		capa_colectores.updateFields()
		idx_cf_diametro = capa_colectores.fields().lookupField(campo_cf_diametro)
		if idx_cf_diametro == -1:
			raise QgsProcessingException(
				f"El campo {campo_cf_diametro} no quedo disponible."
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

			diametro_mm = _to_mm_or_none(feature[idx_diametro])
			# Si no se puede interpretar el diametro, se usa clase 0 para evitar NULL.
			nueva_clase = _clasificar_diametro(diametro_mm, rango_diametro_cfg) if diametro_mm is not None else 0

			valor_actual = feature[idx_cf_diametro]
			if valor_actual != nueva_clase:
				ok = capa_colectores.changeAttributeValue(
					feature.id(), idx_cf_diametro, nueva_clase
				)
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

	return {"ACTUALIZADAS": actualizadas}
