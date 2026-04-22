from qgis.processing import alg
from qgis.core import (
	QgsField,
	QgsProcessingException,
)
from qgis.PyQt.QtCore import QVariant

# Nombre del campo de salida con la Probabilidad de Falla.
CAMPO_PF = "PF"
# Candidatos para ubicar el campo de clasificacion PACP.
PACP_CLASIFICACION_CANDIDATOS = (
	"PACP_Clasificacion",
	"PACP_Clasificación",
	"pacp_clasificacion",
	"pacp_clasificación",
)


def _find_field_index(fields, candidates, partial_tokens=(), exclude_names=()):
	"""Busca un campo por lista de candidatos exactos o coincidencia parcial."""
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
			if any(token in lower_name for token in partial_tokens):
				return i

	return -1


def _calcular_pf(pacp_clasificacion):
	"""
	Calcula la Probabilidad de Falla (PF) basada en PACP_Clasificacion.
	
	Reglas segun ejemplos:
	- Si no hay informacion: PF = 0
	- Si 2do caracter es letra: PF = primer_digito + 1
	- Si ambos son numeros: PF = (primeros_dos_digitos) / 10
	  - Si resultado es 0 (clasificacion 0000), PF = 1 (sin defectos)
	
	PACP_Clasificacion es un codigo de 4 caracteres:
	- Caracter 1: Grado mas alto de inspeccion
	- Caracter 2: Numero de veces (o letra si >9)
	- Caracter 3: Siguiente grado mas alto
	- Caracter 4: Numero de veces (o letra si >9)
	"""
	
	if pacp_clasificacion is None:
		return 0
	
	texto = str(pacp_clasificacion).strip()
	
	if not texto:
		return 0
	
	# Si tiene menos de 2 caracteres no podemos procesar
	if len(texto) < 2:
		return 0
	
	# Extraer primeros 2 caracteres
	char1 = texto[0]
	char2 = texto[1]
	
	# Si el segundo caracter es una letra
	if char1.isdigit() and char2.isalpha():
		# Reemplazar letra con 0, dividir entre 10, sumar 1
		# Ejemplo: 5B -> 50/10 + 1 = 6.0
		return (int(char1) * 10 / 10.0) + 1.0
	
	# Si ambos caracteres son numeros
	elif char1.isdigit() and char2.isdigit():
		valor_dos_primeros = int(char1 + char2) / 10.0
		# Si es 0000 (sin defectos), retorna 1.0
		# Ejemplo: 0000 -> 0/10 = 0 -> 1.0
		# Ejemplo: 3222 -> 32/10 = 3.2
		return valor_dos_primeros if valor_dos_primeros > 0 else 1.0
	
	# Si el primer caracter es letra o casos no definidos
	else:
		# Por defecto retornar 0
		return 0


@alg(name="pf_probabilidad_falla",
	 label="PF Probabilidad de Falla",
	 group="personalizados",
	 group_label="Personalizados")
@alg.input(type=alg.VECTOR_LAYER, name="COLECTORES", label="Capa Colectores")
@alg.output(type=alg.NUMBER, name="ACTUALIZADAS", label="Cantidad de colectores actualizados")
def pf_probabilidad_falla(instance, parameters, context, feedback, inputs):
	"""Calcula Probabilidad de Falla (PF) basada en PACP_Clasificacion."""

	capa_colectores = instance.parameterAsVectorLayer(parameters, "COLECTORES", context)

	if capa_colectores is None:
		raise QgsProcessingException("No se pudo leer la capa Colectores.")

	fields = capa_colectores.fields()

	idx_pacp = _find_field_index(
		fields,
		PACP_CLASIFICACION_CANDIDATOS,
		exclude_names=(CAMPO_PF,),
	)
	if idx_pacp == -1:
		idx_pacp = _find_field_index(
			fields,
			(),
			partial_tokens=("pacp",),
			exclude_names=(CAMPO_PF,),
		)
	if idx_pacp == -1:
		raise QgsProcessingException(
			"No se encontro un campo de clasificacion PACP en Colectores (ej: PACP_Clasificacion)."
		)

	feedback.pushInfo(
		f"Campo de clasificacion PACP detectado: {fields.at(idx_pacp).name()}"
	)

	# Crea campo de salida si aun no existe.
	idx_pf = fields.lookupField(CAMPO_PF)
	if idx_pf == -1:
		ok = capa_colectores.dataProvider().addAttributes(
			[QgsField(CAMPO_PF, QVariant.Double, len=10, prec=2)]
		)
		if not ok:
			raise QgsProcessingException(
				f"No se pudo crear el campo {CAMPO_PF} en Colectores."
			)

		capa_colectores.updateFields()
		idx_pf = capa_colectores.fields().lookupField(CAMPO_PF)
		if idx_pf == -1:
			raise QgsProcessingException(
				f"El campo {CAMPO_PF} no quedo disponible."
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

			pacp_valor = feature[idx_pacp]
			nueva_pf = _calcular_pf(pacp_valor)

			valor_actual = feature[idx_pf]
			if valor_actual != nueva_pf:
				ok = capa_colectores.changeAttributeValue(
					feature.id(), idx_pf, nueva_pf
				)
				if not ok:
					raise QgsProcessingException(
						f"No se pudo actualizar {CAMPO_PF} en FID {feature.id()}."
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
