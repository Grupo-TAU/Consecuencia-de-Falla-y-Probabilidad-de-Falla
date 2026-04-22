from qgis.processing import alg
from qgis.core import (
	QgsField,
	QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Nombre del campo de salida con la clasificacion de profundidad.
CAMPO_CF_PROFUNDIDAD = "CF_Profundidad"
# Candidatos para ubicar los campos en Colectores.
REGISTRO_INICIAL_CANDIDATOS = ("Registro_Inicial",)
REGISTRO_FINAL_CANDIDATOS = ("Registro_Final", "Registro_FInal")
# Candidatos para ubicar el ID en Registros.
ID_REGISTRO_CANDIDATOS = ("ID",)
# Candidatos para ubicar el campo de profundidad en Registros.
PROFUNDIDAD_CANDIDATOS = ("PROFUNDIDAD",)
# Campo alternativo cuando PROFUNDIDAD venga nulo.
PROFUNDIDAD_INSPECCIONADA_CANDIDATOS = ("Profundidad_Inspeccionada",)


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


def _clasificar_profundidad(profundidad):
	"""Clasifica segun tabla: <2=1, [2-3)=2, [3-4)=3, [4-5)=4, [5-7)=5, >=7=6."""
	if profundidad is None:
		return None
	if profundidad < 2.0:
		return 1
	if profundidad < 3.0:
		return 2
	if profundidad < 4.0:
		return 3
	if profundidad < 5.0:
		return 4
	if profundidad < 7.0:
		return 5
	return 6


@alg(name="cf_profundidad",
	 label="CF Profundidad",
	 group="personalizados",
	 group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Capa Colectores")
@alg.input(type=alg.SOURCE, name="REGISTROS", label="Capa Registros")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_profundidad(instance, parameters, context, feedback, inputs):
	"""Clasifica colectores por profundidad maxima de sus registros asociados."""

	capa_colectores = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
	registros_source = instance.parameterAsSource(parameters, "REGISTROS", context)

	if capa_colectores is None:
		raise QgsProcessingException("No se pudo leer la capa Colectores.")
	if registros_source is None:
		raise QgsProcessingException("No se pudo leer la capa Registros.")

	colectores_fields = capa_colectores.fields()
	registros_fields = registros_source.fields()

	# Busca campos en Colectores.
	idx_reg_ini = _find_field_index(colectores_fields, REGISTRO_INICIAL_CANDIDATOS)
	idx_reg_fin = _find_field_index(colectores_fields, REGISTRO_FINAL_CANDIDATOS)

	if idx_reg_ini == -1:
		raise QgsProcessingException(
			"No se encontro el campo Registro_Inicial en Colectores."
		)
	if idx_reg_fin == -1:
		raise QgsProcessingException(
			"No se encontro el campo Registro_Final en Colectores."
		)

	# Busca campos en Registros.
	idx_id_reg = _find_field_index(registros_fields, ID_REGISTRO_CANDIDATOS)
	idx_prof_reg = _find_field_index(registros_fields, PROFUNDIDAD_CANDIDATOS, partial_tokens=("prof",))
	idx_prof_inspec = _find_field_index(
		registros_fields,
		PROFUNDIDAD_INSPECCIONADA_CANDIDATOS,
		partial_tokens=("inspe",),
	)

	if idx_id_reg == -1:
		raise QgsProcessingException(
			"No se encontro el campo ID en Registros."
		)
	if idx_prof_reg == -1:
		raise QgsProcessingException(
			"No se encontro un campo de profundidad en Registros (ej: Profundidad)."
		)

	# Construye mapa ID -> Profundidad desde la capa Registros.
	mapa_profundidad = {}
	registros_list = list(registros_source.getFeatures())
	for i, registro in enumerate(registros_list, start=1):
		if feedback.isCanceled():
			break

		reg_id = _normalize_value(registro[idx_id_reg])
		reg_prof = _to_float_or_none(registro[idx_prof_reg])
		if reg_prof is None and idx_prof_inspec != -1:
			reg_prof = _to_float_or_none(registro[idx_prof_inspec])

		if reg_id and reg_prof is not None and reg_id not in mapa_profundidad:
			mapa_profundidad[reg_id] = reg_prof

		if registros_list:
			feedback.setProgress(25.0 * i / len(registros_list))

	# Crea campo de salida si aun no existe.
	idx_cf_profundidad = colectores_fields.lookupField(CAMPO_CF_PROFUNDIDAD)
	if idx_cf_profundidad == -1:
		ok = capa_colectores.dataProvider().addAttributes(
			[QgsField(CAMPO_CF_PROFUNDIDAD, QVariant.Int, len=10, prec=0)]
		)
		if not ok:
			raise QgsProcessingException(
				f"No se pudo crear el campo {CAMPO_CF_PROFUNDIDAD} en Colectores."
			)

		capa_colectores.updateFields()
		idx_cf_profundidad = capa_colectores.fields().lookupField(CAMPO_CF_PROFUNDIDAD)
		if idx_cf_profundidad == -1:
			raise QgsProcessingException(
				f"El campo {CAMPO_CF_PROFUNDIDAD} no quedo disponible."
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

			nueva_clase = _clasificar_profundidad(profundidad_maxima)

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
