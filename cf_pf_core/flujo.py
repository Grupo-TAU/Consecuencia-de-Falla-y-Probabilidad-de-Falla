"""
Orquestador del flujo de Consecuencia de Falla.

Corre los calculos del core en orden y acumula los resultados en un GeoDataFrame
(la futura capa DatosConsecuenciaDeFalla): clave + geometria + todos los CF +
criticidad + PF + Riesgo. NO toca la capa fuente.

Cada paso es una entrada de PASOS con:
  key      : identificador
  label    : nombre visible
  requiere : roles auxiliares necesarios ('registros', 'vias', ...) — si falta
             alguno, el paso se omite (no rompe el resto del flujo).
  fn(ctx)  : devuelve {columna: Serie} para mergear en los resultados.

Los pasos individuales tambien se exponen para correr de a uno desde la app.
"""
import geopandas as gpd

from cf_pf_core.claves import normalizar as normalizar_clave
from cf_pf_core.calculos import (
    acceso_mantenimiento,
    arboles,
    antiguedad,
    criticidad,
    diametro,
    material,
    obstrucciones,
    posicion_relativa,
    probabilidad_falla,
    profundidad,
    proximidad,
    riesgo,
    ubicacion,
)


def _col(gdf, *cands):
    """Resuelve un nombre de columna case-insensitive entre candidatos."""
    lower = {c.lower(): c for c in gdf.columns}
    for n in cands:
        if n and n.lower() in lower:
            return lower[n.lower()]
    return None


def _lista_descriptores(texto):
    """'a, b, c' -> {'a','b','c'}. Vacio -> None (usa los descriptores del calculo)."""
    if not texto or not str(texto).strip():
        return None
    partes = [p.strip().lower() for p in str(texto).split(",") if p.strip()]
    return set(partes) or None


class Contexto:
    def __init__(self, colectores, registros=None, aux=None, config=None):
        self.colectores = colectores
        self.registros = registros
        self.aux = aux or {}
        self.config = config or {}
        self.resultados = None  # GeoDataFrame acumulador (se setea en correr)

    def cfg(self, clave, default):
        v = self.config.get(clave)
        return default if v is None else v


# ── Pasos: cada fn(ctx) -> {columna: Serie alineada al indice de colectores} ──

def paso_diametro(ctx):
    c = _col(ctx.colectores, ctx.cfg("diametro_campo", "DIAMETRO"), "DIAMETRO", "Diametro", "Diámetro")
    return {"CF_Diametro": diametro.calcular(ctx.colectores, campo_diam=c,
                                             rango=ctx.cfg("diametro_rango", diametro.RANGO_DEFAULT))}


def paso_material(ctx):
    c = _col(ctx.colectores, ctx.cfg("material_campo", "Material"), "Material")
    return {"CF_Material": material.calcular(ctx.colectores, campo_mat=c,
                                             mapeo=ctx.cfg("material_mapeo", material.MAPEO_DEFAULT))}


def paso_antiguedad(ctx):
    c = _col(ctx.colectores, ctx.cfg("antiguedad_campo", "Antiguedad"), "Antiguedad")
    return {"CF_Antiguedad": antiguedad.calcular(
        ctx.colectores, campo_edad=c,
        limites=antiguedad.parse_enteros(ctx.cfg("antiguedad_limites", None),
                                         antiguedad.LIMITES_DEFAULT),
        clases=antiguedad.parse_enteros(ctx.cfg("antiguedad_clases", None),
                                        antiguedad.CLASES_DEFAULT))}


def paso_obstrucciones(ctx):
    c = _col(ctx.colectores, ctx.cfg("obstrucciones_campo", "Obstrucciones"), "Obstrucciones")
    return {"CF_Obstrucciones": obstrucciones.calcular(ctx.colectores, campo_obs=c)}


def paso_posicion_relativa(ctx):
    df = posicion_relativa.calcular(
        ctx.colectores,
        campo_reg_ini=ctx.cfg("reg_ini_campo", posicion_relativa.CAMPO_REG_INI_DEFAULT),
        campo_reg_fin=ctx.cfg("reg_fin_campo", posicion_relativa.CAMPO_REG_FIN_DEFAULT),
        campo_pendiente=ctx.cfg("posrel_pendiente", posicion_relativa.CAMPO_PENDIENTE_DEFAULT),
        campo_tipo=ctx.cfg("posrel_tipo", posicion_relativa.CAMPO_TIPO_DEFAULT),
        valores_corte=ctx.cfg("posrel_corte", posicion_relativa.VALORES_CORTE_DEFAULT),
        rango=ctx.cfg("posrel_rango", posicion_relativa.RANGO_DEFAULT),
    )
    return {"posicionRelativa": df["posicionRelativa"], "CF_PosicionRelativa": df["CF_PosicionRelativa"]}


def _entero_o_none(v):
    """La config llega como texto desde la app y el plugin. Vacio -> None, que
    para 'clase si no se conoce la profundidad' significa dejarla NULL."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def paso_profundidad(ctx):
    return {"CF_Profundidad": profundidad.calcular(
        ctx.colectores, ctx.registros,
        campo_reg_ini=ctx.cfg("reg_ini_campo", profundidad.CAMPO_REG_INI_DEFAULT),
        campo_reg_fin=ctx.cfg("reg_fin_campo", profundidad.CAMPO_REG_FIN_DEFAULT),
        campo_id_reg=ctx.cfg("id_reg_campo", profundidad.CAMPO_ID_REG_DEFAULT),
        campo_prof=ctx.cfg("profundidad_campo", profundidad.CAMPO_PROF_DEFAULT),
        campo_prof_inspec=ctx.cfg("profundidad_inspec_campo", profundidad.CAMPO_PROF_INSPEC_DEFAULT),
        rango=ctx.cfg("profundidad_rango", profundidad.RANGO_DEFAULT),
        clase_sin_dato=_entero_o_none(
            ctx.cfg("profundidad_clase_sin_dato", profundidad.CLASE_SIN_DATO_DEFAULT)))}


def paso_ubicacion(ctx):
    return {"CF_Ubicacion": ubicacion.calcular(
        ctx.colectores, ctx.aux["vias"],
        campo_tipo=ctx.cfg("ubicacion_campo_tipo", ubicacion.CAMPO_TIPO_DEFAULT),
        buffer_1=float(ctx.cfg("ubicacion_buffer_1", ubicacion.BUFFER_1_DEFAULT)),
        buffer_2=float(ctx.cfg("ubicacion_buffer_2", ubicacion.BUFFER_2_DEFAULT)),
        mapping=ctx.cfg("ubicacion_mapping", ubicacion.TIPO_MAPPING_DEFAULT),
    )}


def paso_prox_sitios(ctx):
    # Ademas de la clase se guarda la distancia al sitio mas cercano: es el
    # numero que la origino y el visualizador lo muestra entre parentesis.
    clase, dist = proximidad.calcular_detalle(
        ctx.colectores, ctx.aux["sitios"],
        ctx.cfg("sitios_rango", proximidad.RANGOS_SITIOS_DEFAULT))
    return {"CF_Prox_SitiosInteres": clase,
            proximidad.CAMPO_DIST_SITIOS_DEFAULT: dist}


def paso_prox_medioamb(ctx):
    clase, dist = proximidad.calcular_detalle(
        ctx.colectores, ctx.aux["cursos"],
        ctx.cfg("cursos_rango", proximidad.RANGOS_MEDIOAMBIENTAL_DEFAULT))
    return {"CF_Prox_MedioAmbiental": clase,
            proximidad.CAMPO_DIST_MEDIOAMBIENTAL_DEFAULT: dist}


def paso_acceso(ctx):
    return {"CF_Acceso_Mantenimiento": acceso_mantenimiento.calcular(
        ctx.colectores, ctx.registros,
        construcciones=ctx.aux.get("construcciones"),
        asentamientos=ctx.aux.get("asentamientos"),
        padrones=ctx.aux.get("padrones"),
        peatonales=ctx.aux.get("peatonales"),
        verde=ctx.aux.get("verde"),
        calles=ctx.aux.get("calles"),
        campo_reg_ini=ctx.cfg("reg_ini_campo", acceso_mantenimiento.CAMPO_REG_INI_DEFAULT),
        campo_reg_fin=ctx.cfg("reg_fin_campo", acceso_mantenimiento.CAMPO_REG_FIN_DEFAULT),
        campo_id_reg=ctx.cfg("id_reg_campo", acceso_mantenimiento.CAMPO_ID_REG_DEFAULT),
        campo_tipo_via=ctx.cfg("acceso_campo_tipo_via", acceso_mantenimiento.CAMPO_TIPO_VIA_DEFAULT),
        descriptores_clase2=_lista_descriptores(ctx.cfg("acceso_descriptores_cl2", None)),
        buffer_calles=float(ctx.cfg("acceso_buffer_calles",
                                    acceso_mantenimiento.BUFFER_CALLES_DEFAULT)),
    )}


def paso_arboles(ctx):
    return {"CF_Arboles": arboles.calcular(
        ctx.colectores,
        campo_nro=ctx.cfg("arboles_campo_nro", arboles.CAMPO_NRO_DEFAULT),
        campo_dist=ctx.cfg("arboles_campo_dist", arboles.CAMPO_DIST_DEFAULT),
        clase_con=int(ctx.cfg("arboles_clase_con", arboles.CLASE_CON_DEFAULT)),
        clase_sin=int(ctx.cfg("arboles_clase_sin", arboles.CLASE_SIN_DEFAULT)))}


def paso_pf(ctx):
    return {"PF": probabilidad_falla.calcular(ctx.colectores,
                                              campo_pacp=ctx.cfg("pf_campo_pacp", None))}


def campo_criticidad(config=None):
    """Nombre de la columna donde se escribe la criticidad.

    Configurable porque no todos los consumidores la llaman igual: la simbologia
    de QGIS y los .gpkg de trabajo usan 'criticidad', mientras que el
    visualizador interactivo de las entregas la lee como 'CF'. Es el mismo
    numero; cambia solo el nombre de la columna.
    """
    v = (config or {}).get("criticidad_campo")
    return str(v).strip() if v and str(v).strip() else criticidad.CAMPO_SALIDA_DEFAULT


def paso_criticidad(ctx):
    # Lee los CF ya acumulados en resultados. grupos configurable (pesos + params).
    return {campo_criticidad(ctx.config): criticidad.calcular(
        ctx.resultados, grupos=ctx.cfg("criticidad_grupos", None))}


def paso_riesgo(ctx):
    # Riesgo = criticidad x PF: tiene que buscar la criticidad con el mismo
    # nombre con el que la escribio paso_criticidad.
    return {"Riesgo": riesgo.calcular(
        ctx.resultados, campo_criticidad=campo_criticidad(ctx.config))}


# (key, label, requiere, fn)
PASOS = [
    ("diametro", "CF Diámetro", [], paso_diametro),
    ("posicion_relativa", "CF Posición Relativa", [], paso_posicion_relativa),
    ("profundidad", "CF Profundidad", ["registros"], paso_profundidad),
    ("prox_sitios", "CF Prox. Sitios de Interés", ["sitios"], paso_prox_sitios),
    ("prox_medioamb", "CF Prox. Medio Ambiental", ["cursos"], paso_prox_medioamb),
    ("antiguedad", "CF Antigüedad", [], paso_antiguedad),
    ("material", "CF Material", [], paso_material),
    ("acceso", "CF Acceso Mantenimiento", ["registros"], paso_acceso),
    ("ubicacion", "CF Ubicación de la Tubería", ["vias"], paso_ubicacion),
    ("obstrucciones", "CF Obstrucciones", [], paso_obstrucciones),
    ("arboles", "CF Árboles", [], paso_arboles),
    ("pf", "PF Probabilidad de Falla", [], paso_pf),
    ("criticidad", "Criticidad", [], paso_criticidad),
    ("riesgo", "Riesgo", [], paso_riesgo),
]

PASOS_POR_KEY = {p[0]: p for p in PASOS}

# Columnas que produce cada paso. Con esto se sabe que columnas de la capa fuente
# son "resultados ya calculados" y se pueden reaprovechar (ver _previas_de_fuente).
COLUMNAS_POR_PASO = {
    "diametro": ["CF_Diametro"],
    "posicion_relativa": ["posicionRelativa", "CF_PosicionRelativa"],
    "profundidad": ["CF_Profundidad"],
    "prox_sitios": ["CF_Prox_SitiosInteres", proximidad.CAMPO_DIST_SITIOS_DEFAULT],
    "prox_medioamb": ["CF_Prox_MedioAmbiental",
                      proximidad.CAMPO_DIST_MEDIOAMBIENTAL_DEFAULT],
    "antiguedad": ["CF_Antiguedad"],
    "material": ["CF_Material"],
    "acceso": ["CF_Acceso_Mantenimiento"],
    "ubicacion": ["CF_Ubicacion"],
    "obstrucciones": ["CF_Obstrucciones"],
    "arboles": ["CF_Arboles"],
    "pf": ["PF"],
    "criticidad": ["criticidad"],
    "riesgo": ["Riesgo"],
}

COLUMNAS_SALIDA = [c for cols in COLUMNAS_POR_PASO.values() for c in cols]

# Roles auxiliares que un paso aprovecha si estan disponibles, pero que no le
# impiden correr si faltan (a diferencia de los de `requiere`).
ROLES_OPCIONALES = {
    "acceso": ["construcciones", "asentamientos", "padrones", "peatonales",
               "verde", "calles"],
}


def roles_usados(key):
    """Roles auxiliares que tiene sentido pasarle a un paso: obligatorios + opcionales."""
    if key not in PASOS_POR_KEY:
        return []
    return [*PASOS_POR_KEY[key][2], *ROLES_OPCIONALES.get(key, [])]


# Metadata para la app: campos editables por seccion.
# (config_key, etiqueta, valor_default). "comunes" agrupa columnas compartidas.
CONFIG_CAMPOS = {
    "comunes": [
        ("reg_ini_campo", "Columna Registro Inicial (Colectores)", posicion_relativa.CAMPO_REG_INI_DEFAULT),
        ("reg_fin_campo", "Columna Registro Final (Colectores)", posicion_relativa.CAMPO_REG_FIN_DEFAULT),
        ("id_reg_campo", "Columna ID (Registros)", profundidad.CAMPO_ID_REG_DEFAULT),
    ],
    "diametro": [
        ("diametro_campo", "Columna Diámetro", diametro.CAMPO_DIAMETRO_DEFAULT),
        ("diametro_rango", "Rangos (límite=clase)", diametro.RANGO_DEFAULT),
    ],
    "material": [
        ("material_campo", "Columna Material", material.CAMPO_MATERIAL_DEFAULT),
        ("material_mapeo", "Mapeo material", material.MAPEO_DEFAULT),
    ],
    "antiguedad": [
        ("antiguedad_campo", "Columna Antigüedad", antiguedad.CAMPO_EDAD_DEFAULT),
        ("antiguedad_limites", "Límites de años",
         ", ".join(str(x) for x in antiguedad.LIMITES_DEFAULT)),
        ("antiguedad_clases", "Clases (una más que los límites)",
         ", ".join(str(x) for x in antiguedad.CLASES_DEFAULT)),
    ],
    "obstrucciones": [
        ("obstrucciones_campo", "Columna Obstrucciones", obstrucciones.CAMPO_OBS_DEFAULT),
    ],
    "posicion_relativa": [
        ("posrel_pendiente", "Columna Pendiente", posicion_relativa.CAMPO_PENDIENTE_DEFAULT),
        ("posrel_tipo", "Columna Tipo/Inspección", posicion_relativa.CAMPO_TIPO_DEFAULT),
        ("posrel_corte", "Tipos a ignorar (corte)", posicion_relativa.VALORES_CORTE_DEFAULT),
        ("posrel_rango", "Rangos", posicion_relativa.RANGO_DEFAULT),
    ],
    "profundidad": [
        ("profundidad_campo", "Columna Profundidad (Registros)", profundidad.CAMPO_PROF_DEFAULT),
        ("profundidad_inspec_campo", "Columna Prof. Inspeccionada", profundidad.CAMPO_PROF_INSPEC_DEFAULT),
        ("profundidad_rango", "Rangos", profundidad.RANGO_DEFAULT),
        ("profundidad_clase_sin_dato", "Clase si no se conoce la profundidad",
         profundidad.CLASE_SIN_DATO_DEFAULT),
    ],
    "ubicacion": [
        ("ubicacion_campo_tipo", "Columna TIPO (Vías)", ubicacion.CAMPO_TIPO_DEFAULT),
        ("ubicacion_buffer_1", "Buffer 1 (m)", ubicacion.BUFFER_1_DEFAULT),
        ("ubicacion_buffer_2", "Buffer 2 (m)", ubicacion.BUFFER_2_DEFAULT),
        ("ubicacion_mapping", "Mapeo TIPO", ubicacion.TIPO_MAPPING_DEFAULT),
    ],
    "prox_sitios": [
        ("sitios_rango", "Rangos buffer", proximidad.RANGOS_SITIOS_DEFAULT),
    ],
    "prox_medioamb": [
        ("cursos_rango", "Rangos buffer", proximidad.RANGOS_MEDIOAMBIENTAL_DEFAULT),
    ],
    "acceso": [
        ("acceso_campo_tipo_via", "Columna Tipo_Via (Calles)", acceso_mantenimiento.CAMPO_TIPO_VIA_DEFAULT),
        ("acceso_descriptores_cl2", "Descriptores de clase 2 (coma)",
         ", ".join(sorted(acceso_mantenimiento.DESCRIPTORES_CLASE_2))),
        ("acceso_buffer_calles", "Buffer de calles (m)",
         acceso_mantenimiento.BUFFER_CALLES_DEFAULT),
    ],
    "pf": [
        ("pf_campo_pacp", "Columna PACP (vacío = autodetecta)", ""),
    ],
    "arboles": [
        ("arboles_campo_nro", "Columna cantidad de árboles",
         arboles.CAMPO_NRO_DEFAULT),
        ("arboles_campo_dist", "Columna distancia al árbol",
         arboles.CAMPO_DIST_DEFAULT),
        ("arboles_clase_con", "Clase si tiene al menos un árbol",
         arboles.CLASE_CON_DEFAULT),
        ("arboles_clase_sin", "Clase si no tiene ninguno",
         arboles.CLASE_SIN_DEFAULT),
    ],
    "criticidad": [
        ("criticidad_campo", "Columna de salida", criticidad.CAMPO_SALIDA_DEFAULT),
    ],
}

# Etiquetas legibles por seccion (para la app).
ETIQUETAS_SECCION = {"comunes": "Columnas comunes", **{p[0]: p[1] for p in PASOS}}

# Que columnas comunes usa realmente cada paso (el resto no le sirve de nada).
COMUNES_POR_PASO = {
    "posicion_relativa": ["reg_ini_campo", "reg_fin_campo"],
    "profundidad": ["reg_ini_campo", "reg_fin_campo", "id_reg_campo"],
    "acceso": ["reg_ini_campo", "reg_fin_campo", "id_reg_campo"],
}


def campos_config(key):
    """Campos configurables de un paso: los comunes que usa mas los propios.

    Es la fuente de verdad que consumen la app y los scripts, para que agregar un
    parametro al core lo publique en las dos puntas sin tocarlas.
    """
    usa = set(COMUNES_POR_PASO.get(key, []))
    comunes = [c for c in CONFIG_CAMPOS.get("comunes", []) if c[0] in usa]
    return [*comunes, *CONFIG_CAMPOS.get(key, [])]


def columnas_de_paso(key, config=None):
    """Columnas que produce un paso, ya resueltos los nombres configurables.

    COLUMNAS_POR_PASO tiene los nombres por defecto; este es el que hay que usar
    cuando esta en juego la config, porque la criticidad se puede renombrar.
    """
    if key == "criticidad":
        return [campo_criticidad(config)]
    return COLUMNAS_POR_PASO.get(key, [])


def _nombres_conocidos(config=None):
    """Nombres de columna de resultado, en minusculas, incluidos los alias viejos."""
    conocidos = {c.lower() for c in COLUMNAS_SALIDA}
    for alias in criticidad.ALIASES.values():
        conocidos.update(a.lower() for a in alias)
    # El nombre configurado de la criticidad tambien cuenta como resultado: si no,
    # una capa que ya trae 'CF' no se reconoceria como corrida anterior.
    conocidos.add(campo_criticidad(config).lower())
    return conocidos


def previas_de_fuente(colectores_gdf, config=None):
    """Columnas de resultado que la capa de Colectores ya trae calculadas.

    Muchas capas de trabajo ya tienen los CF_* cargados de corridas anteriores
    (hechas con el plugin viejo, o a mano). Reaprovecharlas permite recalcular un
    solo paso —tipico: Criticidad— sin tener que rehacer todos los CF antes.
    """
    conocidos = _nombres_conocidos(config)
    return [c for c in colectores_gdf.columns if c.lower() in conocidos]


def _base_resultados(colectores_gdf, clave, config=None):
    """Acumulador inicial: clave + geometria + lo que la fuente ya traiga calculado."""
    geom = colectores_gdf.geometry.name
    cols = [c for c in (clave, geom) if c is not None]
    cols += [c for c in previas_de_fuente(colectores_gdf, config) if c not in cols]
    return colectores_gdf[cols].copy()


def resolver_clave(colectores_gdf, clave=None):
    """Elige la columna clave: la indicada, o ELEMRED/ID si existen, o el indice."""
    if clave and clave in colectores_gdf.columns:
        return clave
    return _col(colectores_gdf, "ELEMRED", "ID", "id")


def _reenganchar(resultados, base, clave):
    """Trae al acumulador las columnas ya calculadas de una corrida anterior.

    Sin esto, correr 'criticidad' o 'riesgo' de a uno no encuentra los CF_* que
    necesita y devuelve todo vacio.
    """
    if base is None or clave is None or clave not in base.columns:
        return resultados
    geom_base = base.geometry.name if hasattr(base, "geometry") else None
    previas = [c for c in base.columns if c not in (clave, geom_base)]
    if not previas:
        return resultados

    aporte = base[[clave, *previas]].copy()
    aporte["__clave"] = aporte[clave].map(normalizar_clave)
    aporte = aporte.drop(columns=[clave])

    # Un merge left solo conserva las filas si la clave es unica del lado derecho.
    # Sin este control el merge multiplica las filas y despues falla al reponer el
    # indice, con un ValueError de pandas que no dice nada del problema real.
    repes = int(aporte["__clave"].duplicated().sum())
    if repes:
        raise ValueError(
            f"La capa de resultados anterior tiene {repes} valores repetidos en "
            f"'{clave}' ({len(aporte)} filas, {aporte['__clave'].nunique()} claves "
            "distintas). Suele significar que se escribio dos veces. Corré el flujo "
            "completo, que reescribe la capa de cero."
        )

    geom = resultados.geometry.name
    orden = resultados.index
    izq = resultados.copy()
    # La capa de salida manda sobre lo que trajera la fuente: es lo que calculo
    # esta herramienta. Se descartan las repetidas antes de unir (ademas evita
    # que el merge las renombre a _x/_y).
    repetidas = [c for c in previas if c in izq.columns]
    if repetidas:
        izq = izq.drop(columns=repetidas)
    izq["__clave"] = izq[clave].map(normalizar_clave)
    unido = izq.merge(aporte, on="__clave", how="left").drop(columns="__clave")
    unido.index = orden
    return gpd.GeoDataFrame(unido, geometry=geom, crs=resultados.crs)


def correr(colectores_gdf, registros=None, aux=None, config=None, clave=None,
           solo=None, log=None, base=None, progreso=None):
    """Corre el flujo (o solo los pasos en `solo`) y devuelve el GeoDataFrame de
    resultados. `log(mensaje, nivel)` opcional para reportar progreso.

    solo: lista de keys de PASOS a ejecutar; None = todos.
    base: resultados de una corrida anterior (la capa DatosConsecuenciaDeFalla).
    progreso: callable(fraccion, etiqueta) con fraccion en [0, 1]. Se llama antes
        de cada paso y una vez al terminar. Sirve para barras de progreso; los
        pasos salteados igual avanzan, asi la fraccion no se queda trabada.

    De donde salen los CF que un paso necesita pero no calcula (el caso de
    'criticidad' y 'riesgo'), de menor a mayor prioridad:
      1. la propia capa de Colectores, si ya los trae cargados;
      2. `base`, o sea lo que dejaron las corridas anteriores;
      3. lo que se calcule en esta corrida.
    Asi se puede recalcular un solo paso sobre una capa que ya venia con los CF
    hechos, sin tener que rehacerlos todos primero.
    """
    def _log(msg, nivel="info"):
        if log:
            log(msg, nivel)

    def _prog(fraccion, etiqueta):
        if progreso:
            progreso(max(0.0, min(1.0, fraccion)), etiqueta)

    clave = resolver_clave(colectores_gdf, clave)
    ctx = Contexto(colectores_gdf, registros, aux, config)

    keys = solo if solo is not None else [p[0] for p in PASOS]

    # Lo que se reaprovecha se avisa: si un paso no se corre y su columna sale de
    # la fuente, el usuario tiene que poder distinguirlo de un valor recien calculado.
    a_calcular = {c.lower() for k in keys for c in columnas_de_paso(k, config)}
    reusadas = [c for c in previas_de_fuente(colectores_gdf, config)
                if c.lower() not in a_calcular]
    if reusadas:
        _log("Se reusan columnas ya presentes en Colectores: " + ", ".join(reusadas))

    ctx.resultados = _reenganchar(
        _base_resultados(colectores_gdf, clave, config), base, clave)

    total = max(len(keys), 1)
    for i, key in enumerate(keys):
        if key not in PASOS_POR_KEY:
            _log(f"Paso desconocido: {key}", "warn")
            _prog((i + 1) / total, f"{i + 1}/{total}")
            continue
        _key, label, requiere, fn = PASOS_POR_KEY[key]
        # El progreso se avisa ANTES de correr el paso: es el unico momento en el
        # que se puede mostrar en que se esta trabajando mientras tarda.
        _prog(i / total, f"{label} ({i + 1}/{total})")
        faltan = [r for r in requiere if r == "registros" and registros is None
                  or r != "registros" and (aux or {}).get(r) is None]
        if faltan:
            _log(f"{label}: se omite (falta capa: {', '.join(faltan)})", "warn")
            _prog((i + 1) / total, f"{i + 1}/{total}")
            continue
        try:
            for col, serie in fn(ctx).items():
                ctx.resultados[col] = serie.reindex(ctx.resultados.index)
            _log(f"{label}: OK", "ok")
        except Exception as e:  # noqa: BLE001
            _log(f"{label}: ERROR — {e}", "error")
        _prog((i + 1) / total, f"{i + 1}/{total}")

    _prog(1.0, "Listo")
    return ctx.resultados
