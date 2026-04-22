from qgis.processing import alg
from qgis.core import (
	QgsField,
	QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Campo final a calcular en Colectores.
CAMPO_CF_FINAL = "CF_Final"

# Candidatos para detectar automaticamente los CF de entrada.
CAMPO_POS_REL_CANDIDATOS = (
	"CF_PosicionRelativa",
	"CF_PosiciónRelativa",
)
CAMPO_DIAMETRO_CANDIDATOS = (
	"CF_Diametro",
	"CF_Diámetro",
)
CAMPO_PROFUNDIDAD_CANDIDATOS = (
	"CF_Profundidad",
)
CAMPO_PROX_MA_CANDIDATOS = (
	"CF_Prox_MedioAmbiental",
	"CF_ProxMedioAmbiental",
	"cf_MA",
)
CAMPO_PROX_CI_CANDIDATOS = (
	"CF_Prox_ClienteImportante",
	"CF_ProxClienteImportante",
	"cf_CI",
)

# Ponderaciones de la matriz definida por negocio.
PESO_ECONOMICO = 0.40
PESO_SOCIAL = 0.40
PESO_MEDIOAMBIENTAL = 0.20

# Maximos posibles por componente para normalizar CF_TOTAL/CF_POSIBLE.
POSIBLE_ECONOMICO = 12.0  # X2 + X3
POSIBLE_SOCIAL = 12.0     # X1 + X5
POSIBLE_MEDIOAMBIENTAL = 6.0  # X4


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


def _to_cf_value(value):
	"""Normaliza cada CF individual al rango [1, 6]. Si falta, usa 1."""
	val = _to_float_or_none(value)
	if val is None:
		return 1.0
	if val < 1.0:
		return 1.0
	if val > 6.0:
		return 6.0
	return val


@alg(name="cf_total",
	 label="CF Total (CF_Final)",
	 group="personalizados",
	 group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Capa Colectores")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def cf_total(instance, parameters, context, feedback, inputs):
	"""Calcula CF_Final por tramo segun la matriz de ponderacion definida."""

	capa_colectores = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)
	if capa_colectores is None:
		raise QgsProcessingException("No se pudo leer la capa Colectores.")

	fields = capa_colectores.fields()

	idx_x1 = _find_field_index(
		fields,
		CAMPO_POS_REL_CANDIDATOS,
		partial_tokens=("cf", "pos", "rel"),
		exclude_names=(CAMPO_CF_FINAL,),
	)
	idx_x2 = _find_field_index(
		fields,
		CAMPO_DIAMETRO_CANDIDATOS,
		partial_tokens=("cf", "diam"),
		exclude_names=(CAMPO_CF_FINAL,),
	)
	idx_x3 = _find_field_index(
		fields,
		CAMPO_PROFUNDIDAD_CANDIDATOS,
		partial_tokens=("cf", "prof"),
		exclude_names=(CAMPO_CF_FINAL,),
	)
	idx_x4 = _find_field_index(
		fields,
		CAMPO_PROX_MA_CANDIDATOS,
		partial_tokens=("cf", "medio"),
		exclude_names=(CAMPO_CF_FINAL,),
	)
	idx_x5 = _find_field_index(
		fields,
		CAMPO_PROX_CI_CANDIDATOS,
		partial_tokens=("cf", "cliente"),
		exclude_names=(CAMPO_CF_FINAL,),
	)

	required = {
		"CF_PosicionRelativa (X_1)": idx_x1,
		"CF_Diametro (X_2)": idx_x2,
		"CF_Profundidad (X_3)": idx_x3,
		"CF_Prox_MedioAmbiental (X_4)": idx_x4,
		"CF_Prox_ClienteImportante (X_5)": idx_x5,
	}
	missing = [name for name, idx in required.items() if idx == -1]
	if missing:
		raise QgsProcessingException(
			"Faltan columnas requeridas en Colectores: " + ", ".join(missing)
		)

	feedback.pushInfo(f"Campo X_1 detectado: {fields.at(idx_x1).name()}")
	feedback.pushInfo(f"Campo X_2 detectado: {fields.at(idx_x2).name()}")
	feedback.pushInfo(f"Campo X_3 detectado: {fields.at(idx_x3).name()}")
	feedback.pushInfo(f"Campo X_4 detectado: {fields.at(idx_x4).name()}")
	feedback.pushInfo(f"Campo X_5 detectado: {fields.at(idx_x5).name()}")

	idx_cf_final = fields.lookupField(CAMPO_CF_FINAL)
	if idx_cf_final == -1:
		ok = capa_colectores.dataProvider().addAttributes(
			[QgsField(CAMPO_CF_FINAL, QVariant.Double, len=10, prec=2)]
		)
		if not ok:
			raise QgsProcessingException(
				f"No se pudo crear el campo {CAMPO_CF_FINAL} en Colectores."
			)

		capa_colectores.updateFields()
		idx_cf_final = capa_colectores.fields().lookupField(CAMPO_CF_FINAL)
		if idx_cf_final == -1:
			raise QgsProcessingException(
				f"El campo {CAMPO_CF_FINAL} no quedo disponible."
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

			# X_1..X_5 segun la matriz compartida por negocio.
			x1 = _to_cf_value(colector[idx_x1])
			x2 = _to_cf_value(colector[idx_x2])
			x3 = _to_cf_value(colector[idx_x3])
			x4 = _to_cf_value(colector[idx_x4])
			x5 = _to_cf_value(colector[idx_x5])

			cf_total_economico = x2 + x3
			cf_total_social = x1 + x5
			cf_total_medioambiental = x4

			cf_pond_economico = (cf_total_economico / POSIBLE_ECONOMICO) * PESO_ECONOMICO
			cf_pond_social = (cf_total_social / POSIBLE_SOCIAL) * PESO_SOCIAL
			cf_pond_medioambiental = (
				(cf_total_medioambiental / POSIBLE_MEDIOAMBIENTAL) * PESO_MEDIOAMBIENTAL
			)

			# CF_FINAL = SUMA(CF_PONDERADO) * 6.
			cf_final = round((cf_pond_economico + cf_pond_social + cf_pond_medioambiental) * 6.0, 2)

			valor_actual = _to_float_or_none(colector[idx_cf_final])
			if valor_actual is None or abs(valor_actual - cf_final) > 1e-9:
				ok_update = capa_colectores.changeAttributeValue(
					colector.id(), idx_cf_final, cf_final
				)
				if not ok_update:
					raise QgsProcessingException(
						f"No se pudo actualizar {CAMPO_CF_FINAL} en FID {colector.id()}."
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
