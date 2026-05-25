from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterString,
    QgsProcessingOutputNumber,
)
import processing


PROVIDER_ID = "colectores_riesgo"


class FlujoCompleto(QgsProcessingAlgorithm):
    """
    Ejecuta todos los algoritmos de clasificacion y riesgo en el orden correcto:

        1. Asignar Registro Inicial y Final en Colectores
        2. Actualizar Registros - Cota Zampeado (Mecanica 1 + Mecanica 2)
        3. Actualizar Colectores Longitud, Cota Zampeado y Pendiente
        4. CF Diametro
        5. CF Posicion Relativa
        6. CF Profundidad
        7. CF Prox Cliente Importante
        8. CF Prox Medio Ambiental
        9. CF Antiguedad
       10. CF Material
       11. CF Acceso Mantenimiento
       12. CF Ubicacion de la Tuberia
       13. CF Obstrucciones
       14. CF Total
       15. PF Probabilidad de Falla
       16. Riesgo
       17. Aplicar Simbologia
    """

    COLECTORES           = "COLECTORES"
    REGISTROS            = "REGISTROS"
    CLIENTES_IMPORTANTES = "CLIENTES_IMPORTANTES"
    CURSOS_AGUA          = "CURSOS_AGUA"
    CALLES               = "CALLES"
    ESPACIOS_VERDES      = "ESPACIOS_VERDES"
    ESPACIOS_PEATONALES  = "ESPACIOS_PEATONALES"
    PADRONES             = "PADRONES"
    CONSTRUCCIONES       = "CONSTRUCCIONES"
    ASENTAMIENTOS        = "ASENTAMIENTOS"
    VIAS                 = "VIAS"
    BUFFERS_CLIENTES     = "BUFFERS_CLIENTES"
    BUFFERS_AGUA         = "BUFFERS_AGUA"
    CAMPO_SIMBOLOGIA     = "CAMPO_SIMBOLOGIA"
    OUTPUT_PASOS_OK      = "PASOS_OK"

    def name(self):
        return "flujo_completo"

    def displayName(self):
        return "Flujo Completo"

    def group(self):
        return "Personalizados"

    def groupId(self):
        return "personalizados"

    def shortHelpString(self):
        return (
            "Ejecuta todos los pasos del flujo de clasificacion y riesgo en orden.\n\n"
            "Requiere las capas: Colectores, Registros, Clientes Importantes y "
            "Cursos de Agua (Medio Ambiental). Corre cada algoritmo secuencialmente "
            "informando el progreso.\n\n"
            "Genera dos capas de buffers visibles: una para Clientes Importantes "
            "y otra para Cursos de Agua.\n\n"
            "Si algun paso falla, el flujo se detiene y muestra el error."
        )

    def createInstance(self):
        return FlujoCompleto()

    # ── Definicion de parametros ───────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.COLECTORES,
                "Capa Colectores",
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.REGISTROS,
                "Capa Registros",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CLIENTES_IMPORTANTES,
                "Capa Clientes Importantes",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CURSOS_AGUA,
                "Capa Cursos de Agua (Medio Ambiental)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CALLES,
                "Capa Calles (Acceso Mantenimiento)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.ESPACIOS_VERDES,
                "Capa Espacios Verdes (Acceso Mantenimiento)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.ESPACIOS_PEATONALES,
                "Capa Espacios Peatonales (Acceso Mantenimiento)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.PADRONES,
                "Capa Padrones (Acceso Mantenimiento)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.CONSTRUCCIONES,
                "Capa Construcciones (Acceso Mantenimiento)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.ASENTAMIENTOS,
                "Capa Asentamientos (Acceso Mantenimiento)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.VIAS,
                "Capa Vias (CF Ubicacion)",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.BUFFERS_CLIENTES,
                "Buffers Clientes Importantes (salida)",
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.BUFFERS_AGUA,
                "Buffers Cursos de Agua (salida)",
            )
        )
        self.addParameter(
           QgsProcessingParameterString(
                self.CAMPO_SIMBOLOGIA,
               "Campo para simbologia (valores 1-6)",
                defaultValue="CF_Final",
            )
        )

        self.addOutput(
            QgsProcessingOutputNumber(
                self.OUTPUT_PASOS_OK,
                "Cantidad de pasos ejecutados correctamente",
            )
        )

    # ── Logica principal ───────────────────────────────────────────────────────

    def processAlgorithm(self, parameters, context, feedback):

        colectores = self.parameterAsVectorLayer(parameters, self.COLECTORES, context)
        registros  = self.parameterAsVectorLayer(parameters, self.REGISTROS, context)
        if colectores is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")
        if registros is None:
            raise QgsProcessingException("No se pudo leer la capa Registros.")
        if self.parameterAsSource(parameters, self.CLIENTES_IMPORTANTES, context) is None:
            raise QgsProcessingException("No se pudo leer la capa Clientes Importantes.")
        if self.parameterAsSource(parameters, self.CURSOS_AGUA, context) is None:
            raise QgsProcessingException("No se pudo leer la capa Cursos de Agua.")
        for nombre, param in [
            ("Calles",              self.CALLES),
            ("Espacios Verdes",     self.ESPACIOS_VERDES),
            ("Espacios Peatonales", self.ESPACIOS_PEATONALES),
            ("Padrones",            self.PADRONES),
            ("Construcciones",      self.CONSTRUCCIONES),
            ("Asentamientos",       self.ASENTAMIENTOS),
        ]:
            if self.parameterAsSource(parameters, param, context) is None:
                raise QgsProcessingException(f"No se pudo leer la capa {nombre}.")

        total_pasos      = 17
        pasos_ok         = 0
        buffers_clientes_id = None
        buffers_agua_id     = None

        def _ejecutar(numero, nombre, alg_id, params):
            """Ejecuta un paso, actualiza progreso y retorna el resultado."""
            if feedback.isCanceled():
                return None
            feedback.pushInfo(f"[{numero}/{total_pasos}] Ejecutando: {nombre} ...")
            feedback.setProgress(100.0 * (numero - 1) / total_pasos)
            try:
                resultado = processing.run(
                    alg_id,
                    params,
                    context=context,
                    feedback=feedback,
                    is_child_algorithm=True,
                )
                feedback.pushInfo(f"  ✔ {nombre} completado.")
                return resultado
            except Exception as e:
                raise QgsProcessingException(
                    f"Error en el paso '{nombre}' ({alg_id}): {e}"
                )

        # ── PASO 1: Asignar Registro Inicial y Final ──────────────────────────
        if _ejecutar(1, "Asignar Registro Inicial y Final",
                     f"{PROVIDER_ID}:asignar_registros_colectores",
                     {
                         "COLECTORES": colectores.id(),
                         "REGISTROS":  registros.id(),
                     }) is not None:
            pasos_ok += 1

        # ── PASO 2: Actualizar Registros - Cota Zampeado ──────────────────────
        if not feedback.isCanceled():
            if _ejecutar(2, "Actualizar Registros - Cota Zampeado",
                         f"{PROVIDER_ID}:actualizar_registros_cota_zampeado",
                         {
                             "REGISTROS":   registros.id(),
                             "COLECTORES":  colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 3: Actualizar Colectores ─────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(3, "Actualizar Colectores",
                         f"{PROVIDER_ID}:actualizar_colectores_long_zamp_pend",
                         {
                             "COLECTORES": colectores.id(),
                             "REGISTROS":  registros.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 4: CF Diametro ────────────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(4, "CF Diametro",
                         f"{PROVIDER_ID}:cf_diametro",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 5: CF Posicion Relativa ───────────────────────────────────────
        # El parametro de capa se llama "Colectores" (mayuscula) en ese algoritmo.
        if not feedback.isCanceled():
            if _ejecutar(5, "CF Posicion Relativa",
                         f"{PROVIDER_ID}:calculo_posicion_relativa",
                         {
                             "Colectores": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 6: CF Profundidad ─────────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(6, "CF Profundidad",
                         f"{PROVIDER_ID}:cf_profundidad",
                         {
                             "COLECTORES": colectores.id(),
                             "REGISTROS":  registros.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 7: CF Prox Cliente Importante ────────────────────────────────
        if not feedback.isCanceled():
            res7 = _ejecutar(7, "CF Prox Cliente Importante",
                             f"{PROVIDER_ID}:CF_Prox_ClienteImportante",
                             {
                                 "COLECTORES":           colectores.id(),
                                 "CLIENTES_IMPORTANTES": parameters[self.CLIENTES_IMPORTANTES],
                                 "BUFFERS_VISIBLES":     parameters[self.BUFFERS_CLIENTES],
                             })
            if res7 is not None:
                buffers_clientes_id = res7.get("BUFFERS_VISIBLES")
                pasos_ok += 1

        # ── PASO 8: CF Prox Medio Ambiental ───────────────────────────────────
        if not feedback.isCanceled():
            res8 = _ejecutar(8, "CF Prox Medio Ambiental",
                             f"{PROVIDER_ID}:CF_Prox_MedioAmbiental",
                             {
                                 "COLECTORES":       colectores.id(),
                                 "CURSOS_AGUA":      parameters[self.CURSOS_AGUA],
                                 "BUFFERS_VISIBLES": parameters[self.BUFFERS_AGUA],
                             })
            if res8 is not None:
                buffers_agua_id = res8.get("BUFFERS_VISIBLES")
                pasos_ok += 1

        # ── PASO 9: CF Antiguedad ─────────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(9, "CF Antiguedad",
                         f"{PROVIDER_ID}:cf_antiguedad",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 10: CF Material ──────────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(10, "CF Material",
                         f"{PROVIDER_ID}:cf_material",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 11: CF Acceso Mantenimiento ──────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(11, "CF Acceso Mantenimiento",
                         f"{PROVIDER_ID}:cf_acceso_mantenimiento",
                         {
                             "COLECTORES":          colectores.id(),
                             "REGISTROS":           registros.id(),
                             "CALLES":              parameters[self.CALLES],
                             "ESPACIOS_VERDES":     parameters[self.ESPACIOS_VERDES],
                             "ESPACIOS_PEATONALES": parameters[self.ESPACIOS_PEATONALES],
                             "PADRONES":            parameters[self.PADRONES],
                             "CONSTRUCCIONES":      parameters[self.CONSTRUCCIONES],
                             "ASENTAMIENTOS":       parameters[self.ASENTAMIENTOS],
                         }) is not None:
                pasos_ok += 1

        # ── PASO 12: CF Ubicacion de la Tuberia ───────────────────────────────
        # Es opcional: si el usuario no provee la capa Vias, se omite el paso.
        if not feedback.isCanceled():
            src_vias = self.parameterAsSource(parameters, self.VIAS, context)
            if src_vias is None:
                feedback.pushInfo(
                    f"[12/{total_pasos}] CF Ubicacion: capa Vias no proporcionada, paso omitido."
                )
            else:
                if _ejecutar(12, "CF Ubicacion de la Tuberia",
                             f"{PROVIDER_ID}:cf_ubicacion",
                             {
                                 "COLECTORES": colectores.id(),
                                 "VIAS":       parameters[self.VIAS],
                             }) is not None:
                    pasos_ok += 1

        # ── PASO 13: CF Obstrucciones ──────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(13, "CF Obstrucciones",
                         f"{PROVIDER_ID}:cf_obstrucciones",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 14: CF Total ──────────────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(14, "CF Total",
                         f"{PROVIDER_ID}:cf_total",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 15: PF Probabilidad de Falla ─────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(15, "PF Probabilidad de Falla",
                         f"{PROVIDER_ID}:pf_probabilidad_falla",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 16: Riesgo ────────────────────────────────────────────────────
        if not feedback.isCanceled():
            if _ejecutar(16, "Riesgo",
                         f"{PROVIDER_ID}:riesgo_calculo",
                         {
                             "COLECTORES": colectores.id(),
                         }) is not None:
                pasos_ok += 1

        # ── PASO 17: Aplicar Simbologia ────────────────────────────────────────
        if not feedback.isCanceled():
            campo_simb = self.parameterAsString(parameters, self.CAMPO_SIMBOLOGIA, context)
            if _ejecutar(17, "Aplicar Simbologia",
                         f"{PROVIDER_ID}:aplicar_simbologia",
                         {
                             "COLECTORES": colectores.id(),
                             "CAMPO":      campo_simb,
                         }) is not None:
                pasos_ok += 1

        if feedback.isCanceled():
            feedback.pushWarning("Flujo cancelado por el usuario.")

        feedback.setProgress(100)
        feedback.pushInfo(f"Flujo completado: {pasos_ok}/{total_pasos} pasos ejecutados correctamente.")

        return {
            self.OUTPUT_PASOS_OK:  pasos_ok,
            self.BUFFERS_CLIENTES: buffers_clientes_id,
            self.BUFFERS_AGUA:     buffers_agua_id,
        }
