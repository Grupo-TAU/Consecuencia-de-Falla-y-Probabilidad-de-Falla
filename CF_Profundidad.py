import re

from qgis.processing import alg
from qgis.core import (
	QgsField,
	QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Nombre del campo de salida con la clasificacion de profundidad.
CAMPO_CF_PROFUNDIDAD = "CF_Profundidad"
# Nombres por defecto de campos en Colectores.
CAMPO_REGISTRO_INICIAL = "Registro_Inicial"
CAMPO_REGISTRO_FINAL = "Registro_Final"
# Nombres por defecto de campos en Registros.
CAMPO_ID_REGISTRO = "ID"
CAMPO_PROFUNDIDAD = "PROFUNDIDAD"
CAMPO_PROFUNDIDAD_INSPECCIONADA = "Profundidad_Inspeccionada"
# Limites de profundidad (metros) para clasificacion por defecto.
RANGO_PROFUNDIDAD = (2.0, 3.0, 4.0, 5.0, 7.0)

# Parametros configurables en el algoritmo.
PARAM_CAMPO_CF_PROFUNDIDAD = "CAMPO_CF_PROFUNDIDAD"
PARAM_CAMPO_REGISTRO_INICIAL = "CAMPO_REGISTRO_INICIAL"
PARAM_CAMPO_REGISTRO_FINAL = "CAMPO_REGISTRO_FINAL"
PARAM_CAMPO_ID_REGISTRO = "CAMPO_ID_REGISTRO"
PARAM_CAMPO_PROFUNDIDAD = "CAMPO_PROFUNDIDAD"
PARAM_CAMPO_PROFUNDIDAD_INSPECCIONADA = "CAMPO_PROFUNDIDAD_INSPECCIONADA"
PARAM_RANGO_PROFUNDIDAD = "RANGO_PROFUNDIDAD"


def _find_field_index(fields, candidates, partial_tokens=()):
	"""Busca un campo por lista de candidatos exactos o coincidencia parcial."""
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
	"""Normaliza un valor a string para comparacion como clave."""
	if value is None:
		return ""
	return str(value).strip()


def _to_float_or_none(value):
	"""Convierte el valor a float, tolerando diferentes formatos."""
	if value is None:
		return None

	if isinstance(value, (int, float)):
		return float(value)

	text = str(value).strip()
	if not text:
		return None

	# Soporta decimal con coma cuando el origen viene como texto.
	text = text.replace(",", ".")

	try:
		return float(text)
	except ValueError:
		return None


def _parse_rango_profundidad(text, defaults):
	"""Convierte el texto de rangos a una tupla de limites en metros."""
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


def _clasificar_profundidad(profundidad, limites):
	"""Clasifica segun limites configurables de profundidad."""
	if profundidad is None:
		return None
	for idx, limite in enumerate(limites, start=1):
		if profundidad < limite:
			return idx
	return len(limites) + 1


@alg(name="cf_profundidad",
	 label="CF Profundidad",
	 group="personalizados",
	 group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Capa Colectores")
@alg.input(type=alg.SOURCE, name="REGISTROS", label="Capa Registros")
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_CF_PROFUNDIDAD,
	label="Nombre campo salida (CF Profundidad)",
	default=CAMPO_CF_PROFUNDIDAD,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_REGISTRO_INICIAL,
	label="Nombre campo Registro Inicial en Colectores",
	default=CAMPO_REGISTRO_INICIAL,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_REGISTRO_FINAL,
	label="Nombre campo Registro Final en Colectores",
	default=CAMPO_REGISTRO_FINAL,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_ID_REGISTRO,
	label="Nombre campo ID en Registros",
	default=CAMPO_ID_REGISTRO,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_PROFUNDIDAD,
	label="Nombre campo Profundidad en Registros",
	default=CAMPO_PROFUNDIDAD,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_CAMPO_PROFUNDIDAD_INSPECCIONADA,
	label="Nombre campo Profundidad Inspeccionada en Registros (opcional)",
	default=CAMPO_PROFUNDIDAD_INSPECCIONADA,
	optional=True,
)
@alg.input(
	type=alg.STRING,
	name=PARAM_RANGO_PROFUNDIDAD,
	label="Rango Profundidad (limites en metros, separados por coma)",
	default=", ".join(str(v) for v in RANGO_PROFUNDIDAD),
)
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_profundidad(instance, parameters, context, feedback, inputs):
	"""Clasifica colectores por profundidad maxima de sus registros asociados."""

	capa_colectores = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
	registros_source = instance.parameterAsSource(parameters, "REGISTROS", context)

	if capa_colectores is None:
		raise QgsProcessingException("No se pudo leer la capa Colectores.")
	if registros_source is None:
		raise QgsProcessingException("No se pudo leer la capa Registros.")

	campo_cf_profundidad = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_CF_PROFUNDIDAD,
		context,
	)
	campo_cf_profundidad = campo_cf_profundidad.strip() if campo_cf_profundidad is not None else ""
	if not campo_cf_profundidad:
		campo_cf_profundidad = CAMPO_CF_PROFUNDIDAD

	campo_registro_inicial = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_REGISTRO_INICIAL,
		context,
	)
	campo_registro_inicial = campo_registro_inicial.strip() if campo_registro_inicial is not None else ""
	if not campo_registro_inicial:
		campo_registro_inicial = CAMPO_REGISTRO_INICIAL

	campo_registro_final = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_REGISTRO_FINAL,
		context,
	)
	campo_registro_final = campo_registro_final.strip() if campo_registro_final is not None else ""
	if not campo_registro_final:
		campo_registro_final = CAMPO_REGISTRO_FINAL

	campo_id_registro = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_ID_REGISTRO,
		context,
	)
	campo_id_registro = campo_id_registro.strip() if campo_id_registro is not None else ""
	if not campo_id_registro:
		campo_id_registro = CAMPO_ID_REGISTRO

	campo_profundidad = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_PROFUNDIDAD,
		context,
	)
	campo_profundidad = campo_profundidad.strip() if campo_profundidad is not None else ""
	if not campo_profundidad:
		campo_profundidad = CAMPO_PROFUNDIDAD

	campo_profundidad_inspeccionada = instance.parameterAsString(
		parameters,
		PARAM_CAMPO_PROFUNDIDAD_INSPECCIONADA,
		context,
	)
	if campo_profundidad_inspeccionada is not None:
		campo_profundidad_inspeccionada = campo_profundidad_inspeccionada.strip()
		if not campo_profundidad_inspeccionada:
			campo_profundidad_inspeccionada = CAMPO_PROFUNDIDAD_INSPECCIONADA
	else:
		campo_profundidad_inspeccionada = None

	texto_rango_profundidad = instance.parameterAsString(
		parameters,
		PARAM_RANGO_PROFUNDIDAD,
		context,
	)
	rango_profundidad_cfg = _parse_rango_profundidad(texto_rango_profundidad, RANGO_PROFUNDIDAD)

	colectores_fields = capa_colectores.fields()
	registros_fields = registros_source.fields()

	# Busca campos en Colectores.
	idx_reg_ini = _find_field_index(
		colectores_fields,
		(campo_registro_inicial,),
		partial_tokens=("registro", "inicial"),
	)
	idx_reg_fin = _find_field_index(
		colectores_fields,
		(campo_registro_final,),
		partial_tokens=("registro", "final"),
	)

	if idx_reg_ini == -1:
		raise QgsProcessingException(
			f"No se encontro el campo '{campo_registro_inicial}' en Colectores."
		)
	if idx_reg_fin == -1:
		raise QgsProcessingException(
			f"No se encontro el campo '{campo_registro_final}' en Colectores."
		)

	# Busca campos en Registros.
	idx_id_reg = _find_field_index(
		registros_fields,
		(campo_id_registro,),
		partial_tokens=("id",),
	)
	idx_prof_reg = _find_field_index(
		registros_fields,
		(campo_profundidad,),
		partial_tokens=("profundidad", "prof"),
	)
	idx_prof_inspec = -1
	if campo_profundidad_inspeccionada is not None:
		idx_prof_inspec = _find_field_index(
			registros_fields,
			(campo_profundidad_inspeccionada,),
			partial_tokens=("inspeccion",),
		)

	if idx_id_reg == -1:
		raise QgsProcessingException(
			f"No se encontro el campo '{campo_id_registro}' en Registros."
		)
	if idx_prof_reg == -1:
		raise QgsProcessingException(
			f"No se encontro el campo '{campo_profundidad}' en Registros."
		)

	# El campo de profundidad inspeccionada es opcional
	usa_profundidad_inspeccionada = idx_prof_inspec != -1

	feedback.pushInfo(f"Campo salida CF Profundidad: {campo_cf_profundidad}")
	feedback.pushInfo(f"Registro Inicial en Colectores: {campo_registro_inicial}")
	feedback.pushInfo(f"Registro Final en Colectores: {campo_registro_final}")
	feedback.pushInfo(f"ID en Registros: {campo_id_registro}")
	feedback.pushInfo(f"Profundidad en Registros: {campo_profundidad}")
	if usa_profundidad_inspeccionada:
		feedback.pushInfo(f"Profundidad Inspeccionada en Registros: {campo_profundidad_inspeccionada}")
	else:
		feedback.pushInfo("Campo Profundidad Inspeccionada no especificado - se usara solo Profundidad")
	feedback.pushInfo(
		"Rango Profundidad configurado (m): "
		+ ", ".join(
			str(int(v)) if float(v).is_integer() else str(v)
			for v in rango_profundidad_cfg
		)
	)

	# Construye mapa de profundidades por ID de registro
	mapa_profundidad = {}
	for registro in registros_source.getFeatures():
		reg_id = _normalize_value(registro[idx_id_reg])
		if not reg_id:
			continue

		profundidad = _to_float_or_none(registro[idx_prof_reg])
		if usa_profundidad_inspeccionada:
			prof_inspec = _to_float_or_none(registro[idx_prof_inspec])
			if prof_inspec is not None:
				if profundidad is not None:
					profundidad = max(profundidad, prof_inspec)
				else:
					profundidad = prof_inspec

		if profundidad is not None:
			mapa_profundidad[reg_id] = profundidad

	# Crea campo de salida si aun no exista.
	idx_cf_profundidad = colectores_fields.lookupField(campo_cf_profundidad)
	if idx_cf_profundidad == -1:
		ok = capa_colectores.dataProvider().addAttributes(
			[QgsField(campo_cf_profundidad, QVariant.Int, len=10, prec=0)]
		)
		if not ok:
			raise QgsProcessingException(
				f"No se pudo crear el campo {campo_cf_profundidad} en Colectores."
			)

		capa_colectores.updateFields()
		idx_cf_profundidad = capa_colectores.fields().lookupField(campo_cf_profundidad)
		if idx_cf_profundidad == -1:
			raise QgsProcessingException(
				f"El campo {campo_cf_profundidad} no quedo disponible."
			)

	inicio_edicion = False
	if not capa_colectores.isEditable():
		if not capa_colectores.startEditing():
			raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
		inicio_edicion = True

	colectores_list = list(capa_colectores.getFeatures())
	total = len(colectores_list)
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
		for i, colector in enumerate(colectores_list, start=1):
			if feedback.isCanceled():
				break

			reg_ini_id = _normalize_value(colector[idx_reg_ini])
			reg_fin_id = _normalize_value(colector[idx_reg_fin])

			prof_ini = mapa_profundidad.get(reg_ini_id)
			prof_fin = mapa_profundidad.get(reg_fin_id)

			# Toma la mayor profundidad entre los dos registros.
			profundidad_maxima = None
			if prof_ini is not None and prof_fin is not None:
				profundidad_maxima = max(prof_ini, prof_fin)
			elif prof_ini is not None:
				profundidad_maxima = prof_ini
			elif prof_fin is not None:
				profundidad_maxima = prof_fin

			nueva_clase = _clasificar_profundidad(profundidad_maxima, rango_profundidad_cfg)

			valor_actual = colector[idx_cf_profundidad]
			if valor_actual != nueva_clase:
				ok = capa_colectores.changeAttributeValue(
					colector.id(), idx_cf_profundidad, nueva_clase
				)
				if not ok:
					raise QgsProcessingException(
						f"No se pudo actualizar {CAMPO_CF_PROFUNDIDAD} en FID {colector.id()}."
					)
				actualizadas += 1

			feedback.setProgress(25.0 + 75.0 * i / total)

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
