from qgis.core import (
    QgsCoordinateTransform,
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
CAMPO_CF_ACCESO_DEFAULT      = "CF_Acceso_Mantenimiento"
CAMPO_REGISTRO_INICIAL       = "Registro_Inicial"
CAMPO_REGISTRO_FINAL         = "Registro_Final"
CAMPO_ID_REGISTRO            = "ID"
CAMPO_TIPO_VIA               = "Tipo_Via"
BUFFER_CALLES_DEFAULT        = 1.0   # metros — punto vs. linea de calle

DESCRIPTORES_CLASE_2_DEFAULT = {"local mayor", "autopista/canal", "arteria/edificaciones"}

# ── Nombres de parametros ─────────────────────────────────────────────────────
COLECTORES                    = "COLECTORES"
REGISTROS                     = "REGISTROS"
CALLES                        = "CALLES"
ESPACIOS_VERDES               = "ESPACIOS_VERDES"
ESPACIOS_PEATONALES           = "ESPACIOS_PEATONALES"
PADRONES                      = "PADRONES"
CONSTRUCCIONES                = "CONSTRUCCIONES"
ASENTAMIENTOS                 = "ASENTAMIENTOS"
PARAM_CAMPO_CF_ACCESO         = "CAMPO_CF_ACCESO"
PARAM_CAMPO_REGISTRO_INICIAL  = "CAMPO_REGISTRO_INICIAL"
PARAM_CAMPO_REGISTRO_FINAL    = "CAMPO_REGISTRO_FINAL"
PARAM_CAMPO_ID_REGISTRO       = "CAMPO_ID_REGISTRO"
PARAM_CAMPO_TIPO_VIA          = "CAMPO_TIPO_VIA"
PARAM_DESCRIPTORES_CLASE_2    = "DESCRIPTORES_CLASE_2"
PARAM_BUFFER_CALLES           = "BUFFER_CALLES"
OUTPUT_ACTUALIZADAS           = "ACTUALIZADAS"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_field_index(fields, candidates, partial_tokens=()):
    lower_to_index = {fields.at(i).name().lower(): i for i in range(fields.count())}
    for candidate in candidates:
        idx = lower_to_index.get(str(candidate).lower())
        if idx is not None:
            return idx
    if partial_tokens:
        for i in range(fields.count()):
            name_lower = fields.at(i).name().lower()
            if any(tok in name_lower for tok in partial_tokens):
                return i
    return -1


def _normalize_id(value):
    if value is None:
        return ""
    return str(value).strip()


def _build_index_transformed(source, transformador=None):
    """Igual a _build_index pero reconstruye la geometria transformada en el indice."""
    from qgis.core import QgsFeature
    index    = QgsSpatialIndex()
    geom_map = {}
    for feat in source.getFeatures():
        if not feat.hasGeometry():
            continue
        geom = feat.geometry()
        if geom is None or geom.isEmpty():
            continue
        if transformador is not None:
            geom.transform(transformador)
        # Necesitamos un QgsFeature con la geometria transformada para el indice
        f_idx = QgsFeature(feat.id())
        f_idx.setGeometry(geom)
        index.addFeature(f_idx)
        geom_map[feat.id()] = geom
    return index, geom_map


def _intersecta(geom_punto, index, geom_map):
    for fid in index.intersects(geom_punto.boundingBox()):
        geom = geom_map.get(fid)
        if geom is not None and geom.intersects(geom_punto):
            return True
    return False


def _descriptor_calles_en_punto(geom_punto, index_calles, geom_calles, attr_calles, buf):
    """Devuelve el conjunto de DESCRIPTOR de calles que intersectan el punto (con buffer)."""
    geom_buf    = geom_punto.buffer(buf, 8)
    descriptors = set()
    for fid in index_calles.intersects(geom_buf.boundingBox()):
        geom = geom_calles.get(fid)
        if geom is not None and geom.intersects(geom_buf):
            desc = attr_calles.get(fid, "")
            if desc is None:
                desc = ""
            descriptors.add(str(desc).strip().lower())
    return descriptors


def _clasificar_registro(geom_punto,
                          index_constr,   geom_constr,
                          index_asent,    geom_asent,
                          index_padrones, geom_padrones,
                          index_peatonal, geom_peatonal,
                          index_verdes,   geom_verdes,
                          index_calles,   geom_calles, attr_calles,
                          buffer_calles,  descriptores_clase_2):
    if index_constr is not None and _intersecta(geom_punto, index_constr, geom_constr):
        return 6
    if index_asent is not None and _intersecta(geom_punto, index_asent, geom_asent):
        return 6
    if index_padrones is not None and _intersecta(geom_punto, index_padrones, geom_padrones):
        return 5
    if index_peatonal is not None and _intersecta(geom_punto, index_peatonal, geom_peatonal):
        return 4
    if index_verdes is not None and _intersecta(geom_punto, index_verdes, geom_verdes):
        return 3
    if index_calles is not None:
        descriptors = _descriptor_calles_en_punto(
            geom_punto, index_calles, geom_calles, attr_calles, buffer_calles
        )
        if descriptors & descriptores_clase_2:
            return 2
    return 1


# ── Algoritmo ─────────────────────────────────────────────────────────────────

class CfAccesoMantenimiento(QgsProcessingAlgorithm):
    """Clasifica colectores por accesibilidad para mantenimiento (1=mejor, 6=peor)."""

    def name(self):
        return "cf_acceso_mantenimiento"

    def displayName(self):
        return "CF Acceso Mantenimiento"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Clasifica cada colector segun la accesibilidad para su mantenimiento "
            "basandose en la informacion espacial de los registros y de varias capaz auxiliares.\n\n"
            "Clasifica primero cada registro adyacente y luego asigna al colector el mejor (con menor clasificacion) de sus dos extremos."
        )

    def createInstance(self):
        return CfAccesoMantenimiento()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(COLECTORES, "Capa Colectores"))
        self.addParameter(QgsProcessingParameterFeatureSource(REGISTROS, "Capa Registros (puntos)"))
        self.addParameter(QgsProcessingParameterFeatureSource(CALLES, "Capa Calles (opcional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(ESPACIOS_VERDES, "Capa Espacios Verdes (opcional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(ESPACIOS_PEATONALES, "Capa Espacios Peatonales (opcional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(PADRONES, "Capa Padrones (opcional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(CONSTRUCCIONES, "Capa Construcciones (opcional)", optional=True))
        self.addParameter(QgsProcessingParameterFeatureSource(ASENTAMIENTOS, "Capa Asentamientos (opcional)", optional=True))
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_CF_ACCESO,
                "Nombre campo salida (CF Acceso Mantenimiento)",
                defaultValue=CAMPO_CF_ACCESO_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REGISTRO_INICIAL,
                "Registro Inicial en capa de Colectores",
                defaultValue=CAMPO_REGISTRO_INICIAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_REGISTRO_FINAL,
                "Registro Final en capa de Colectores",
                defaultValue=CAMPO_REGISTRO_FINAL,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_ID_REGISTRO,
                "Campo ID en Registros",
                defaultValue=CAMPO_ID_REGISTRO,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_CAMPO_TIPO_VIA,
                "Tipo Via de Calles",
                defaultValue=CAMPO_TIPO_VIA,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_DESCRIPTORES_CLASE_2,
                "Tipos de Via que dificultan acceso, clasifican como clase 2 (separados por coma)",
                defaultValue=", ".join(sorted(DESCRIPTORES_CLASE_2_DEFAULT)),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                PARAM_BUFFER_CALLES,
                "Buffer para interseccion con Calles (metros)",
                defaultValue=str(BUFFER_CALLES_DEFAULT),
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(OUTPUT_ACTUALIZADAS, "Cantidad de colectores actualizados")
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):
        capa_colectores = self.parameterAsVectorLayer(parameters, COLECTORES, context)
        src_registros   = self.parameterAsSource(parameters, REGISTROS, context)
        src_calles      = self.parameterAsSource(parameters, CALLES, context)
        src_verdes      = self.parameterAsSource(parameters, ESPACIOS_VERDES, context)
        src_peatonal    = self.parameterAsSource(parameters, ESPACIOS_PEATONALES, context)
        src_padrones    = self.parameterAsSource(parameters, PADRONES, context)
        src_constr      = self.parameterAsSource(parameters, CONSTRUCCIONES, context)
        src_asent       = self.parameterAsSource(parameters, ASENTAMIENTOS, context)

        if capa_colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")
        if src_registros is None:
            raise QgsProcessingException("No se pudo leer la capa Registros.")

        campo_cf_acceso = (
            self.parameterAsString(parameters, PARAM_CAMPO_CF_ACCESO, context).strip()
            or CAMPO_CF_ACCESO_DEFAULT
        )
        campo_reg_ini = (
            self.parameterAsString(parameters, PARAM_CAMPO_REGISTRO_INICIAL, context).strip()
            or CAMPO_REGISTRO_INICIAL
        )
        campo_reg_fin = (
            self.parameterAsString(parameters, PARAM_CAMPO_REGISTRO_FINAL, context).strip()
            or CAMPO_REGISTRO_FINAL
        )
        campo_id_reg = (
            self.parameterAsString(parameters, PARAM_CAMPO_ID_REGISTRO, context).strip()
            or CAMPO_ID_REGISTRO
        )
        campo_tipo_via = (
            self.parameterAsString(parameters, PARAM_CAMPO_TIPO_VIA, context).strip()
            or CAMPO_TIPO_VIA
        )
        descriptores_str = (
            self.parameterAsString(parameters, PARAM_DESCRIPTORES_CLASE_2, context) or ""
        ).strip()
        descriptores_clase_2 = (
            {v.strip().lower() for v in descriptores_str.split(",") if v.strip()}
            if descriptores_str
            else set(DESCRIPTORES_CLASE_2_DEFAULT)
        )
        feedback.pushInfo(f"Descriptores Clase 2: {', '.join(sorted(descriptores_clase_2))}")
        try:
            buffer_calles = float(
                self.parameterAsString(parameters, PARAM_BUFFER_CALLES, context)
                .strip().replace(",", ".")
            )
        except (ValueError, AttributeError):
            buffer_calles = BUFFER_CALLES_DEFAULT

        col_fields = capa_colectores.fields()
        reg_fields = src_registros.fields()

        idx_reg_ini = _find_field_index(col_fields, (campo_reg_ini,), ("registro", "inicial"))
        idx_reg_fin = _find_field_index(col_fields, (campo_reg_fin,), ("registro", "final"))
        if idx_reg_ini == -1:
            raise QgsProcessingException(f"No se encontro '{campo_reg_ini}' en Colectores.")
        if idx_reg_fin == -1:
            raise QgsProcessingException(f"No se encontro '{campo_reg_fin}' en Colectores.")

        idx_id_reg = _find_field_index(reg_fields, (campo_id_reg,), ("id",))
        if idx_id_reg == -1:
            raise QgsProcessingException(f"No se encontro '{campo_id_reg}' en Registros.")

        feedback.pushInfo("Construyendo indices espaciales...")
        crs_ref = src_registros.sourceCrs()

        def _transformador(src):
            crs_src = src.sourceCrs()
            if crs_ref.isValid() and crs_src.isValid() and crs_ref != crs_src:
                return QgsCoordinateTransform(crs_src, crs_ref, QgsProject.instance())
            return None

        def _build_optional(src, label):
            if src is None:
                feedback.pushInfo(f"  → {label}: no proporcionada, se omite.")
                return None, {}
            feedback.pushInfo(f"  → {label}")
            return _build_index_transformed(src, _transformador(src))

        idx_calles,   geom_calles   = _build_optional(src_calles,   "Calles")
        idx_verdes,   geom_verdes   = _build_optional(src_verdes,   "Espacios Verdes")
        idx_peatonal, geom_peatonal = _build_optional(src_peatonal, "Espacios Peatonales")
        idx_padrones, geom_padrones = _build_optional(src_padrones, "Padrones")
        idx_constr,   geom_constr   = _build_optional(src_constr,   "Construcciones")
        idx_asent,    geom_asent    = _build_optional(src_asent,    "Asentamientos")

        attr_calles = {}
        if src_calles is not None:
            idx_tipo_via = _find_field_index(
                src_calles.fields(), (campo_tipo_via,), ("tipo", "via")
            )
            if idx_tipo_via == -1:
                raise QgsProcessingException(f"No se encontro '{campo_tipo_via}' en Calles.")
            for feat in src_calles.getFeatures():
                attr_calles[feat.id()] = feat[idx_tipo_via]

        # ── Clasificar cada Registro ───────────────────────────────────────────
        feedback.pushInfo("Clasificando Registros...")
        clase_por_id_registro = {}
        registros_list = list(src_registros.getFeatures())
        total_reg      = len(registros_list)

        for i, reg in enumerate(registros_list, start=1):
            if feedback.isCanceled():
                break
            if not reg.hasGeometry():
                continue
            geom_punto = reg.geometry()
            if geom_punto is None or geom_punto.isEmpty():
                continue

            reg_id = _normalize_id(reg[idx_id_reg])
            if not reg_id:
                continue

            clase = _clasificar_registro(
                geom_punto,
                idx_constr,   geom_constr,
                idx_asent,    geom_asent,
                idx_padrones, geom_padrones,
                idx_peatonal, geom_peatonal,
                idx_verdes,   geom_verdes,
                idx_calles,   geom_calles, attr_calles,
                buffer_calles, descriptores_clase_2,
            )
            clase_por_id_registro[reg_id] = clase
            feedback.setProgress(50.0 * i / max(total_reg, 1))

        feedback.pushInfo(f"Registros clasificados: {len(clase_por_id_registro)}")

        # ── Crear campo de salida si no existe ────────────────────────────────
        idx_cf = col_fields.lookupField(campo_cf_acceso)
        if idx_cf == -1:
            if not capa_colectores.dataProvider().addAttributes(
                [QgsField(campo_cf_acceso, QVariant.Int, len=10, prec=0)]
            ):
                raise QgsProcessingException(
                    f"No se pudo crear el campo '{campo_cf_acceso}' en Colectores."
                )
            capa_colectores.updateFields()
            idx_cf = capa_colectores.fields().lookupField(campo_cf_acceso)
            if idx_cf == -1:
                raise QgsProcessingException(
                    f"El campo '{campo_cf_acceso}' no quedo disponible tras crearlo."
                )

        inicio_edicion = False
        if not capa_colectores.isEditable():
            if not capa_colectores.startEditing():
                raise QgsProcessingException("No se pudo iniciar el modo de edicion en Colectores.")
            inicio_edicion = True

        colectores_list = list(capa_colectores.getFeatures())
        total_col       = len(colectores_list)
        if total_col == 0:
            if inicio_edicion:
                capa_colectores.commitChanges()
            return {OUTPUT_ACTUALIZADAS: 0}

        actualizadas     = 0
        sin_datos        = 0
        ids_actualizados = []
        idx_id_col       = _find_field_index(col_fields, ("ID", "id"))

        try:
            for i, col in enumerate(colectores_list, start=1):
                if feedback.isCanceled():
                    break

                id_ini = _normalize_id(col[idx_reg_ini])
                id_fin = _normalize_id(col[idx_reg_fin])

                clase_ini = clase_por_id_registro.get(id_ini)
                clase_fin = clase_por_id_registro.get(id_fin)

                if clase_ini is not None and clase_fin is not None:
                    nueva_clase = min(clase_ini, clase_fin)
                elif clase_ini is not None:
                    nueva_clase = clase_ini
                elif clase_fin is not None:
                    nueva_clase = clase_fin
                else:
                    nueva_clase = None
                    sin_datos += 1

                valor_actual = col[idx_cf]
                if valor_actual != nueva_clase:
                    if not capa_colectores.changeAttributeValue(col.id(), idx_cf, nueva_clase):
                        raise QgsProcessingException(
                            f"No se pudo actualizar '{campo_cf_acceso}' en FID {col.id()}."
                        )
                    actualizadas += 1
                    col_id = str(col[idx_id_col]).strip() if idx_id_col != -1 else str(col.id())
                    ids_actualizados.append(col_id)

                feedback.setProgress(50.0 + 50.0 * i / max(total_col, 1))

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

        if sin_datos:
            feedback.pushInfo(
                f"Advertencia: {sin_datos} colectores sin datos en ninguno de sus registros."
            )
        feedback.pushInfo(f"Colectores actualizados: {actualizadas}")
        if ids_actualizados:
            if len(ids_actualizados) <= 50:
                feedback.pushInfo("IDs actualizados: " + ", ".join(ids_actualizados))
            else:
                feedback.pushInfo("(Demasiados IDs para listar, ver conteo arriba)")
        return {OUTPUT_ACTUALIZADAS: actualizadas}
