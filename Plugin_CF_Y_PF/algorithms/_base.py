"""
Clase base de los algoritmos de calculo del plugin.

Cada algoritmo CF/PF se reduce a declarar que paso del core ejecuta: los
parametros, la lectura de capas, el calculo y la escritura de resultados salen
todos de aca. Los parametros configurables se derivan de cf_pf_core.flujo, asi
que un parametro nuevo en el core aparece en QGIS sin tocar el plugin.
"""
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from ..core_bridge import (
    capa_a_gdf,
    escribir_salida,
    leer_base,
    log_de,
    salida_por_defecto,
)

from cf_pf_core import flujo, gpkg_io

COLECTORES = "COLECTORES"
SALIDA = "SALIDA"
CAPA_SALIDA = "CAPA_SALIDA"
CLAVE = "CLAVE"

ETIQUETAS_ROL = {
    "registros": "Capa Registros",
    "vias": "Capa Vias (para Ubicacion)",
    "calles": "Capa Calles",
    "sitios": "Capa Sitios de Interes",
    "cursos": "Capa Cursos de Agua",
    "construcciones": "Capa Construcciones",
    "asentamientos": "Capa Asentamientos",
    "padrones": "Capa Padrones",
    "peatonales": "Capa Peatonales",
    "verde": "Capa Espacios Verdes",
}


def _nombre_param(clave_cfg):
    return clave_cfg.upper()


def _es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


class PasoCoreAlgorithm(QgsProcessingAlgorithm):
    """Ejecuta uno o todos los pasos de cf_pf_core.flujo sobre la capa de Colectores.

    Las subclases solo definen KEY. KEY = None corre el flujo completo.
    """

    KEY = None

    # ── Que pasos, capas y parametros abarca ──────────────────────────────────

    def _keys(self):
        return [self.KEY] if self.KEY else [p[0] for p in flujo.PASOS]

    def _roles(self):
        """Roles auxiliares de todos los pasos que abarca, sin repetir y en orden."""
        vistos, roles = set(), []
        for key in self._keys():
            for rol in flujo.roles_usados(key):
                if rol not in vistos:
                    vistos.add(rol)
                    roles.append(rol)
        return roles

    def _requeridos(self):
        """En el flujo completo nada es obligatorio: los pasos sin capa se omiten solos."""
        if not self.KEY:
            return set()
        return set(flujo.PASOS_POR_KEY[self.KEY][2])

    def _campos(self):
        vistos, campos = set(), []
        for key in self._keys():
            for campo in flujo.campos_config(key):
                if campo[0] not in vistos:
                    vistos.add(campo[0])
                    campos.append(campo)
        return campos

    # ── Metadatos ─────────────────────────────────────────────────────────────

    def _paso(self):
        return flujo.PASOS_POR_KEY[self.KEY]

    def name(self):
        return self.KEY

    def displayName(self):
        return self._paso()[1]

    def group(self):
        return "Consecuencia de Falla"

    def groupId(self):
        return "consecuencia_de_falla"

    def shortHelpString(self):
        _k, label, requiere, _fn = self._paso()
        partes = [
            f"<strong>{label}</strong>",
            "",
            "Calcula sobre la capa de Colectores y escribe el resultado en la capa "
            f"<strong>{gpkg_io.LAYER_SALIDA_DEFAULT}</strong> de un GeoPackage aparte. "
            "La capa de Colectores no se modifica nunca.",
        ]
        if requiere:
            partes.append("")
            partes.append("Capas requeridas: " + ", ".join(requiere))
        partes.append("")
        partes.append(
            "Si el GeoPackage de salida ya tiene resultados, este calculo se suma a "
            "los que ya estaban (se puede correr de a un paso por vez)."
        )
        return "\n".join(partes)

    def createInstance(self):
        return type(self)()

    # ── Parametros ────────────────────────────────────────────────────────────

    def initAlgorithm(self, config=None):
        requiere = self._requeridos()

        self.addParameter(
            QgsProcessingParameterFeatureSource(COLECTORES, "Capa Colectores")
        )
        for rol in self._roles():
            self.addParameter(
                QgsProcessingParameterFeatureSource(
                    rol.upper(),
                    ETIQUETAS_ROL.get(rol, f"Capa {rol}"),
                    optional=rol not in requiere,
                )
            )

        for clave_cfg, etiqueta, default in self._campos():
            nombre = _nombre_param(clave_cfg)
            if _es_numero(default):
                self.addParameter(
                    QgsProcessingParameterNumber(
                        nombre, etiqueta, QgsProcessingParameterNumber.Double,
                        defaultValue=float(default), optional=True,
                    )
                )
            else:
                self.addParameter(
                    QgsProcessingParameterString(
                        nombre, etiqueta, defaultValue=str(default), optional=True
                    )
                )

        self.addParameter(
            QgsProcessingParameterString(
                CLAVE, "Columna clave de union (vacio = ELEMRED o ID)",
                defaultValue="", optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                CAPA_SALIDA, "Nombre de la capa de resultados",
                defaultValue=gpkg_io.LAYER_SALIDA_DEFAULT,
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                SALIDA, "GeoPackage de resultados",
                fileFilter="GeoPackage (*.gpkg)",
                optional=True, createByDefault=False,
            )
        )

    # ── Ejecucion ─────────────────────────────────────────────────────────────

    def _config(self, parameters, context):
        """Valores de configuracion que el usuario cambio respecto del default."""
        cfg = {}
        for clave_cfg, _etiqueta, default in self._campos():
            nombre = _nombre_param(clave_cfg)
            if nombre not in parameters or parameters[nombre] is None:
                continue
            if _es_numero(default):
                cfg[clave_cfg] = self.parameterAsDouble(parameters, nombre, context)
            else:
                texto = self.parameterAsString(parameters, nombre, context)
                if texto is not None and texto.strip():
                    cfg[clave_cfg] = texto.strip()
        return cfg

    def _antes_de_leer(self, parameters, context, feedback):
        """Hook para lo que deba pasar antes de leer las capas (ver FlujoCompleto)."""

    def processAlgorithm(self, parameters, context, feedback):
        label = self.displayName()
        requiere = self._requeridos()
        log = log_de(feedback)

        self._antes_de_leer(parameters, context, feedback)

        fuente_col = self.parameterAsSource(parameters, COLECTORES, context)
        if fuente_col is None:
            raise QgsProcessingException("No se pudo leer la capa Colectores.")

        feedback.pushInfo("Leyendo Colectores...")
        colectores = capa_a_gdf(fuente_col, feedback)

        registros, aux = None, {}
        for rol in self._roles():
            fuente = self.parameterAsSource(parameters, rol.upper(), context)
            if fuente is None:
                if rol in requiere:
                    raise QgsProcessingException(
                        f"{label} necesita la capa '{rol}'.")
                continue
            feedback.pushInfo(f"Leyendo {rol}...")
            gdf = capa_a_gdf(fuente, feedback)
            if rol == "registros":
                registros = gdf
            else:
                aux[rol] = gdf

        capa_salida = (self.parameterAsString(parameters, CAPA_SALIDA, context)
                       or gpkg_io.LAYER_SALIDA_DEFAULT)
        destino = self.parameterAsFileOutput(parameters, SALIDA, context)
        if not destino:
            destino = salida_por_defecto(
                self.parameterAsVectorLayer(parameters, COLECTORES, context))
        if not destino:
            raise QgsProcessingException(
                "Indica el GeoPackage de resultados: no se pudo deducir uno a partir "
                "de la capa de Colectores.")

        clave = self.parameterAsString(parameters, CLAVE, context).strip() or None
        clave = flujo.resolver_clave(colectores, clave)
        if clave is None:
            raise QgsProcessingException(
                "Colectores no tiene columna ELEMRED ni ID, y no se indico una clave. "
                "Sin clave no se pueden unir los resultados.")

        feedback.pushInfo(f"Calculando {label} (clave: {clave})...")
        # El flujo completo se escribe de cero; un paso suelto se suma a lo que haya.
        completo = self.KEY is None
        res = flujo.correr(
            colectores, registros=registros, aux=aux,
            config=self._config(parameters, context), clave=clave,
            solo=None if completo else [self.KEY], log=log,
            base=None if completo else leer_base(destino, capa_salida),
        )

        if feedback.isCanceled():
            return {}

        escribir_salida(res, destino, capa_salida, clave, context, feedback,
                        reemplazar=completo)
        return {SALIDA: destino, CAPA_SALIDA: capa_salida}
