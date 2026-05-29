from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsSpatialIndex,
)
from qgis.PyQt.QtCore import QVariant

# ── Defaults ──────────────────────────────────────────────────────────────────
CAMPO_CLASIFICACION_DEFAULT  = "CF_Ubicacion"
CAMPO_TIPO_DEFAULT           = "TIPO"
BUFFER_PRIMERA_DEFAULT       = 5.0   # metros — 1ra pasada (todos los colectores)
BUFFER_SEGUNDA_DEFAULT       = 10.0   # metros — 2da pasada (solo sin interseccion)

# Tabla de clasificacion:
#   Sin pavimentar             → 1
#   Local menor                → 2
#   Local mayor                → 3
#   Céntrica                   → 4
#   Vía colectora/Edificaciones → 5
#   Arteria/Canal              → 6
TIPO_CLASIFICACION_DEFAULT_STR = (
    "Sin pavimentar:1, "
    "Local menor:2, "
    "Local mayor:3, "
    "Céntrica:4, "
    "Vía colectora/Edificaciones:5, "
    "Arteria/Canal:6"
)

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES          = "COLECTORES"
VIAS                = "VIAS"
PARAM_CAMPO_TIPO    = "CAMPO_TIPO"
PARAM_CAMPO_CLASIF  = "CAMPO_CLASIFICACION"
PARAM_BUFFER_1      = "BUFFER_PRIMERA"
PARAM_BUFFER_2      = "BUFFER_SEGUNDA"
PARAM_TIPO_MAPPING  = "TIPO_MAPPING"
OUTPUT_ACTUALIZADAS = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_tipo_mapping(text, default_str):
    """Convierte 'clave:clase, clave2:clase2' en lista de (clave_lower, int_clase)."""
    source = text if (text and str(text).strip()) else default_str
    result = []
    for pair in str(source).split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        key, _, val = pair.partition(":")
        key = key.strip().lower()
        if not key:
            continue
        try:
            result.append((key, int(val.strip())))
        except ValueError:
            continue
    return result if result else []


def _clasificar_tipo(tipo_raw, mapping):
    """
    Mapea un valor TIPO a una clasificacion 1-6.

    Prioridad:
      1. Conversion directa a entero (si el campo ya guarda 1-6).
      2. Coincidencia exacta con la clave normalizada.
      3. Subcadena — se toma la clave mas larga que aparezca dentro del valor.
    Retorna 1 (Sin pavimentar) si no hay match.
    """
    if tipo_raw is None:
        return 1

    try:
        val = int(str(tipo_raw).strip())
        if 1 <= val <= 6:
            return val
    except (ValueError, TypeError):
        pass

    normalized = str(tipo_raw).strip().lower()

    for key, clase in mapping:
        if normalized == key:
            return clase

    best_len   = 0
    best_clase = 1
    for key, clase in mapping:
        if key in normalized and len(key) > best_len:
            best_len   = len(key)
            best_clase = clase

    return best_clase if best_len > 0 else 1


def _find_field_index(fields, candidates, partial_tokens=()):
    lower_to_index = {fields.at(i).name().lower(): i for i in range(fields.count())}
    for candidate in candidates:
        idx = lower_to_index.get(str(candidate).lower())
        if idx is not None:
            return idx
    if partial_tokens:
        for i in range(fields.count()):
            if any(tok in fields.at(i).name().lower() for tok in partial_tokens):
                return i
    return -1


def _build_index_transformed(source, transformador=None):
    """Construye QgsSpatialIndex + dict {fid: geometry} (transformada si aplica)."""
    index    = QgsSpatialIndex()
    geom_map = {}
    for feat in source.getFeatures():
        if not feat.hasGeometry():
            continue
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        if transformador is not None:
            geom = feat.geometry()
            geom.transform(transformador)
        f_idx = QgsFeature(feat.id())
        f_idx.setGeometry(geom)
        index.addFeature(f_idx)
        geom_map[feat.id()] = geom
    return index, geom_map


def _buscar_clase_en_punto_medio(geom_col, buffer_dist, index_vias, geom_vias, attr_tipo, tipo_mapping):
    """
    Calcula el punto medio del colector, aplica un buffer y retorna la clase
    maxima encontrada entre las vias intersectadas.

    Retorna (clase_max, valido):
      - valido=False si la geometria es invalida o de longitud 0.
      - clase_max=0  si no se encontro ninguna via dentro del buffer.
    """
    longitud = geom_col.length()
    if longitud <= 0:
        return 0, False

    geom_punto_medio = geom_col.interpolate(longitud / 2.0)
    if geom_punto_medio is None or geom_punto_medio.isEmpty():
        return 0, False

    geom_buf   = geom_punto_medio.buffer(buffer_dist, 8)
    candidatos = index_vias.intersects(geom_buf.boundingBox())

    clase_max = 0
    for fid_via in candidatos:
        geom_via = geom_vias.get(fid_via)
        if geom_via is None:
            continue
        if not geom_buf.intersects(geom_via):
            continue
        clase = _clasificar_tipo(attr_tipo.get(fid_via), tipo_mapping)
        if clase > clase_max:
            clase_max = clase

    return clase_max, True


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfUbicacion(QgsProcessingAlgorithm):

    def name(self):
        return "cf_ubicacion"

    def displayName(self):
        return "CF Ubicacion de la Tuberia"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector segun el tipo de via sobre la que esta ubicado.\n\n"
            "Usa DOS PASADAS:\n"
            "  1ra pasada — todos los colectores con el radio chico (default 10 m).\n"
            "  2da pasada — solo los que no encontraron via en la 1ra, con el radio "
            "grande (default 20 m).\n\n"
            "En cada pasada se calcula el PUNTO MEDIO del colector (50 % de su longitud) "
            "y se crea un buffer solo alrededor de ese punto, evitando capturar vias "
            "de esquinas o cruces ajenos al tramo principal.\n\n"
            "Si un colector intersecta varias vias de distinto tipo se asigna el valor "
            "mas alto (mayor consecuencia). Si no intersecta ninguna via en ninguna "
            "pasada se asigna clase 1 (Sin pavimentar).\n\n"
            "Tabla por defecto:\n"
            "  1 = Sin pavimentar\n"
            "  2 = Local menor\n"
            "  3 = Local mayor\n"
            "  4 = Centrica\n"
            "  5 = Via colectora / Edificaciones\n"
            "  6 = Arteria / Canal\n\n"
            "Si el campo TIPO ya contiene numeros 1-6 se usan directamente."
        )

    def createInstance(self):
        return CfUbicacion()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores")
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(VIAS, "Capa Vias")
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_TIPO,
                "Campo TIPO en la capa Vias",
                defaultValue=CAMPO_TIPO_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_CLASIF,
                "Nombre campo salida (CF Ubicacion)",
                defaultValue=CAMPO_CLASIFICACION_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_BUFFER_1,
                "Radio 1ra pasada — todos los colectores (metros)",
                defaultValue=str(BUFFER_PRIMERA_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_BUFFER_2,
                "Radio 2da pasada — solo colectores sin via (metros)",
                defaultValue=str(BUFFER_SEGUNDA_DEFAULT),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_TIPO_MAPPING,
                "Mapeo TIPO → clase (formato: valor:clase, ...). Vacio = usar tabla por defecto.",
                defaultValue=TIPO_CLASIFICACION_DEFAULT_STR,
                optional=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):

        # ── Leer parametros ────────────────────────────────────────────────────
        campo_tipo = (
            self.parameterAsString(parameters, PARAM_CAMPO_TIPO, context).strip()
            or CAMPO_TIPO_DEFAULT
        )
        campo_clasif = (
            self.parameterAsString(parameters, PARAM_CAMPO_CLASIF, context).strip()
            or CAMPO_CLASIFICACION_DEFAULT
        )

        def _leer_buffer(param, default):
            try:
                val = float(
                    self.parameterAsString(parameters, param, context)
                    .strip().replace(",", ".")
                )
                return val if val > 0 else default
            except (ValueError, AttributeError):
                return default

        buffer_1 = _leer_buffer(PARAM_BUFFER_1, BUFFER_PRIMERA_DEFAULT)
        buffer_2 = _leer_buffer(PARAM_BUFFER_2, BUFFER_SEGUNDA_DEFAULT)

        mapping_str  = self.parameterAsString(parameters, PARAM_TIPO_MAPPING, context)
        tipo_mapping = _parse_tipo_mapping(mapping_str, TIPO_CLASIFICACION_DEFAULT_STR)

        feedback.pushInfo(f"Campo TIPO en Vias:        {campo_tipo}")
        feedback.pushInfo(f"Campo salida:              {campo_clasif}")
        feedback.pushInfo(f"Radio 1ra pasada:          {buffer_1} m")
        feedback.pushInfo(f"Radio 2da pasada:          {buffer_2} m")
        feedback.pushInfo(f"Entradas en mapeo TIPO:    {len(tipo_mapping)}")

        # ── Cargar capas ───────────────────────────────────────────────────────
        capa_colectores = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        src_vias        = self.parameterAsSource(parameters, VIAS, context)

        if capa_colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")
        if src_vias is None:
            raise QgsProcessingException("No se pudo leer la capa Vias.")

        # ── Validar campo TIPO ─────────────────────────────────────────────────
        idx_tipo_via = _find_field_index(src_vias.fields(), (campo_tipo,), ("tipo",))
        if idx_tipo_via == -1:
            raise QgsProcessingException(
                f"No se encontro el campo '{campo_tipo}' en la capa Vias. "
                f"Campos disponibles: {', '.join(src_vias.fields().names())}"
            )
        feedback.pushInfo(f"Campo TIPO encontrado: '{src_vias.fields().at(idx_tipo_via).name()}'")

        # ── Transformacion de CRS si es necesaria ──────────────────────────────
        crs_col  = capa_colectores.crs()
        crs_vias = src_vias.sourceCrs()
        transformador = None
        if crs_col.isValid() and crs_vias.isValid() and crs_col != crs_vias:
            transformador = QgsCoordinateTransform(crs_vias, crs_col, QgsProject.instance())
            feedback.pushInfo("CRS de Vias diferente al de Colectores — se transformara al vuelo.")

        # ── Construir indice espacial de Vias ──────────────────────────────────
        feedback.pushInfo("Construyendo indice espacial de Vias...")
        index_vias, geom_vias = _build_index_transformed(src_vias, transformador)

        attr_tipo = {feat.id(): feat[idx_tipo_via] for feat in src_vias.getFeatures()}
        feedback.pushInfo(f"Vias indexadas: {len(geom_vias)}")

        # ── Crear/verificar campo de salida ────────────────────────────────────
        col_fields = capa_colectores.fields()
        idx_clasif = col_fields.lookupField(campo_clasif)
        if idx_clasif == -1:
            if not capa_colectores.dataProvider().addAttributes(
                [QgsField(campo_clasif, QVariant.Int, len=10, prec=0)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo '{campo_clasif}' en Colectores."
                )
            capa_colectores.updateFields()
            idx_clasif = capa_colectores.fields().lookupField(campo_clasif)
            if idx_clasif == -1:
                raise QgsProcessingException(
                    f"El campo '{campo_clasif}' no quedo disponible tras crearlo."
                )

        # ── Iniciar edicion ────────────────────────────────────────────────────
        inicio_edicion = False
        if not capa_colectores.isEditable():
            if not capa_colectores.startEditing():
                raise QgsProcessingException(
                    "No se pudo iniciar el modo de edicion en Colectores."
                )
            inicio_edicion = True

        colectores_list = list(capa_colectores.getFeatures())
        total           = len(colectores_list)
        if total == 0:
            if inicio_edicion:
                capa_colectores.commitChanges()
            return {OUTPUT_ACTUALIZADAS: 0}

        idx_id_col       = _find_field_index(capa_colectores.fields(), ("ID", "id"))
        actualizadas     = 0
        ids_actualizados = []
        pendientes       = []   # colectores sin via en la 1ra pasada

        def _aplicar(col, nueva_clase):
            nonlocal actualizadas
            if col[idx_clasif] != nueva_clase:
                if not capa_colectores.changeAttributeValue(col.id(), idx_clasif, nueva_clase):
                    raise QgsProcessingException(
                        f"No se pudo actualizar '{campo_clasif}' en FID {col.id()}."
                    )
                actualizadas += 1
                col_id = (
                    str(col[idx_id_col]).strip() if idx_id_col != -1 else str(col.id())
                )
                ids_actualizados.append(col_id)

        try:
            # ── 1ra PASADA — todos los colectores ─────────────────────────────
            feedback.pushInfo(f"1ra pasada ({buffer_1} m) — {total} colectores...")

            for i, col in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                if not col.hasGeometry():
                    continue
                geom_col = col.geometry()
                if geom_col is None or geom_col.isEmpty():
                    continue

                clase_max, valido = _buscar_clase_en_punto_medio(
                    geom_col, buffer_1, index_vias, geom_vias, attr_tipo, tipo_mapping
                )

                if not valido:
                    feedback.pushInfo(f"  FID {col.id()}: geometria invalida, se omite.")
                    continue

                if clase_max == 0:
                    pendientes.append(col)   # diferir a 2da pasada
                else:
                    _aplicar(col, clase_max)

                feedback.setProgress(50.0 * i / total)

            # ── 2da PASADA — solo los que no intersectaron ────────────────────
            feedback.pushInfo(
                f"2da pasada ({buffer_2} m) — {len(pendientes)} colectores sin via..."
            )
            resueltos_segunda = 0

            for i, col in enumerate(pendientes, start=1):
                if feedback.isCanceled():
                    break

                geom_col = col.geometry()
                clase_max, _ = _buscar_clase_en_punto_medio(
                    geom_col, buffer_2, index_vias, geom_vias, attr_tipo, tipo_mapping
                )

                nueva_clase = clase_max if clase_max > 0 else 1
                if clase_max > 0:
                    resueltos_segunda += 1

                _aplicar(col, nueva_clase)
                feedback.setProgress(50.0 + 50.0 * i / max(len(pendientes), 1))

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

        sin_via_final = len(pendientes) - resueltos_segunda
        feedback.pushInfo(
            f"1ra pasada: {total - len(pendientes)}/{total} colectores con via encontrada."
        )
        feedback.pushInfo(
            f"2da pasada: {resueltos_segunda}/{len(pendientes)} resueltos con radio {buffer_2} m."
        )
        if sin_via_final:
            feedback.pushInfo(
                f"Sin via en ninguna pasada: {sin_via_final} colectores → asignados clase 1."
            )
        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")

        return {OUTPUT_ACTUALIZADAS: actualizadas}
