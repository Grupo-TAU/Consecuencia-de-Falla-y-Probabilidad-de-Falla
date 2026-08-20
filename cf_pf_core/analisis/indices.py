"""
El indice de Consecuencia de Falla, visto como algebra en vez de como un loop.

cf_pf_core.calculos.criticidad calcula la criticidad fila por fila (df.apply),
que es lo correcto cuando se escribe una capa una vez. Para el tablero hay que
recalcularla miles de veces —cada simulacion del Monte Carlo es un vector de
pesos nuevo— asi que aca la misma formula esta escrita como producto de matrices.

La equivalencia es exacta y esta testeada contra criticidad.calcular
(tests/test_analisis.py). Si cambia una, tiene que cambiar la otra.

    criticidad = SUMA_g( peso_g * promedio_{p in g}(CF_p) )

Como los pesos suman 1 y cada CF vive en [1, 6], la criticidad tambien queda en
[1, 6]: es una combinacion convexa. Todo lo de este modulo preserva esa
propiedad, incluido el descuento de variables duplicadas.
"""
import numpy as np
import pandas as pd

# Operadores de agregacion sobre los puntajes de grupo.
OPERADORES = {
    "media_aritmetica": "Media aritmética",
    "media_geometrica": "Media geométrica",
    "maximo": "Máximo",
}

# Debajo de este coeficiente de variacion, el indice no separa: la mayoria de los
# tramos queda en la misma clase y el mapa se lee como una mancha de un solo color.
CV_MINIMO = 0.20

ESCALA = 6.0


# ─────────────────────────── pesos dentro del grupo ──────────────────────────

def multiplicidad(grupos):
    """En cuantos grupos aparece cada columna CF. 1 = no esta duplicada."""
    cuenta = {}
    for g in grupos.values():
        for p in g["params"]:
            cuenta[p] = cuenta.get(p, 0) + 1
    return cuenta


def pesos_intra_grupo(grupos, descontar_duplicadas=False):
    """Peso de cada parametro DENTRO de su grupo. Devuelve {grupo: {param: w}}.

    Sin descuento cada parametro pesa 1/n: es el promedio simple que hace
    criticidad.calcular.

    Con descuento, un parametro que aparece en m grupos entra con 1/m y despues
    se renormaliza para que el grupo siga sumando 1. Renormalizar no es un
    detalle: sin eso el puntaje del grupo se cae por debajo de 1 y la criticidad
    deja de estar en escala 1-6, que es justo lo que la hace comparable con las
    entregas anteriores. Lo unico que cambia es el reparto interno.

    Ejemplo real de esta capa: CF_Ubicacion esta en Economico y en Social, asi
    que su peso efectivo declarado (0.30/3 + 0.30/3 = 0.20) es el doble del de
    cualquier otra columna de esos grupos. Con descuento baja a 0.12.
    """
    mult = multiplicidad(grupos) if descontar_duplicadas else {}
    salida = {}
    for nombre, g in grupos.items():
        params = list(g["params"])
        if not params:
            salida[nombre] = {}
            continue
        crudos = np.array([1.0 / mult.get(p, 1) for p in params], dtype=float)
        salida[nombre] = dict(zip(params, crudos / crudos.sum()))
    return salida


def pesos_efectivos(grupos, descontar_duplicadas=False):
    """Peso real de cada columna CF sobre la criticidad final. Suma 1.

    Es el numero que hay que mirar cuando alguien pregunta "cuanto pesa la
    antiguedad": el slider habla de grupos, no de columnas, y una columna
    repetida se lleva mas de lo que el slider sugiere.
    """
    intra = pesos_intra_grupo(grupos, descontar_duplicadas)
    salida = {}
    for nombre, g in grupos.items():
        peso = float(g.get("peso") or 0.0)
        for p, w in intra[nombre].items():
            salida[p] = salida.get(p, 0.0) + peso * w
    return salida


# ────────────────────────────── matriz de criterios ──────────────────────────

def matriz_grupos(df, grupos, descontar_duplicadas=False):
    """Puntaje de cada grupo por tramo. Devuelve (X, nombres).

    X es (n_tramos, n_grupos) en escala 1-6. Es la matriz sobre la que corre todo
    el resto: el Monte Carlo la multiplica por vectores de pesos, el PCA la
    descompone y los operadores de agregacion la colapsan a una columna.

    Se incluyen TODOS los grupos con parametros, tengan peso o no: Arboles hoy
    esta en 0 y el punto del tablero es justamente poder subirlo.
    """
    intra = pesos_intra_grupo(grupos, descontar_duplicadas)
    nombres, columnas = [], []
    for nombre, g in grupos.items():
        if not g.get("params"):
            continue
        pesos = intra[nombre]
        bloque = df[list(pesos)].to_numpy(dtype=float)
        columnas.append(bloque @ np.array([pesos[p] for p in pesos], dtype=float))
        nombres.append(nombre)
    if not columnas:
        return np.zeros((len(df), 0)), []
    return np.column_stack(columnas), nombres


def matriz_criterios(df, columnas):
    """Las columnas CF_* crudas como matriz (n_tramos, n_columnas)."""
    return df[list(columnas)].to_numpy(dtype=float)


def vector_pesos(grupos, nombres):
    """Los pesos de `grupos` en el orden de `nombres` (el de matriz_grupos)."""
    return np.array([float(grupos[n].get("peso") or 0.0) for n in nombres],
                    dtype=float)


# ──────────────────────────────── agregacion ─────────────────────────────────

def agregar(X, pesos, operador="media_aritmetica"):
    """Colapsa los puntajes de grupo a un indice por tramo.

    media_aritmetica : el indice historico. Un 6 en un criterio y 1 en el resto
        se diluye hasta el promedio; es lo que aplana la distribucion.
    media_geometrica : penaliza el desbalance. El mismo tramo desbalanceado
        puntua MAS bajo que uno uniforme de igual promedio, asi que lo que
        destaca no es el pico sino la consistencia. Es la lectura opuesta a la
        intuicion "un criterio grave alcanza" — usar con eso en claro.
    maximo           : manda el peor criterio. IGNORA la magnitud de los pesos;
        solo usa cuales grupos estan activos (peso > 0). Es el unico operador que
        no es una combinacion convexa, y el que mas separa en estos datos.
    """
    X = np.asarray(X, dtype=float)
    pesos = np.asarray(pesos, dtype=float)
    if X.size == 0:
        return np.zeros(X.shape[0] if X.ndim == 2 else 0)
    total = pesos.sum()
    if operador == "maximo":
        activos = pesos > 0
        if not activos.any():
            return np.zeros(X.shape[0])
        return X[:, activos].max(axis=1)
    if total <= 0:
        return np.zeros(X.shape[0])
    w = pesos / total
    if operador == "media_geometrica":
        # clip en 1e-9: un puntaje 0 (grupo sin datos) haria -inf y arrastraria
        # el tramo entero, cuando lo que corresponde es que no aporte.
        return np.exp(np.log(np.clip(X, 1e-9, None)) @ w)
    return X @ w


def criticidad_vectorizada(df, grupos, descontar_duplicadas=False,
                           operador="media_aritmetica", redondeo=2):
    """La criticidad de toda la capa de una. Equivalente a criticidad.calcular
    con los defaults (media aritmetica, sin descuento)."""
    X, nombres = matriz_grupos(df, grupos, descontar_duplicadas)
    valores = agregar(X, vector_pesos(grupos, nombres), operador)
    return pd.Series(np.round(valores, redondeo), index=df.index, dtype="float64")


# ──────────────────────────── cortes y clasificacion ─────────────────────────

def cortes_fijos(n_clases=6):
    """Los cortes historicos: 1, 2, 3, 4, 5, 6. Comparables entre escenarios de
    peso, porque no dependen de los datos."""
    return [float(i + 1) for i in range(n_clases)]


def cortes_cuantiles(valores, n_clases=6):
    """Cortes que dejan 1/n de los tramos en cada clase.

    El indice real vive entre 1.27 y 5.15, asi que con cortes fijos las clases 1
    y 6 quedan casi vacias y se desperdicia media rampa de color. Por cuantiles
    la clase mas alta es siempre el 1/n peor: deja de ser una medida absoluta y
    pasa a ser un ranking, que es lo accionable cuando hay que elegir a quien
    mandar la cuadrilla.

    Los cortes repetidos (variables muy concentradas, como CF_Obstrucciones con
    el 99% en un valor) se dejan pasar: colapsan clases, que es la lectura
    honesta de una variable que no discrimina.
    """
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return cortes_fijos(n_clases)
    qs = np.linspace(0, 100, n_clases + 1)[1:]
    return [float(x) for x in np.percentile(v, qs)]


def clasificar(valores, cortes):
    """Indice de clase 0..n-1 de cada valor. NaN -> -1.

    searchsorted con side='left' reproduce el corte historico "<= limite": un
    valor igual al limite cae en la clase de ese limite, no en la siguiente.
    """
    v = np.asarray(valores, dtype=float)
    k = np.searchsorted(np.asarray(cortes, dtype=float), v, side="left")
    k = np.clip(k, 0, len(cortes) - 1)
    return np.where(np.isfinite(v), k, -1)


# ───────────────────────────── poder discriminante ───────────────────────────

def coef_variacion(valores):
    """std/mean. Cuanto mas chico, menos separa el indice."""
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0 or v.mean() == 0:
        return 0.0
    return float(v.std() / v.mean())


def entropia_shannon(valores, cortes):
    """Entropia (bits) de la distribucion por clase.

    Complementa al CV porque mide otra cosa: el CV mira la dispersion de los
    numeros, la entropia mira cuan repartidos quedan los TRAMOS entre las clases
    que se dibujan. Un indice puede tener CV decente y aun asi mandar el 63% de
    los tramos a dos clases. El maximo con n clases es log2(n) = 2.585 para 6.
    """
    k = clasificar(valores, cortes)
    k = k[k >= 0]
    if k.size == 0:
        return 0.0
    cuenta = np.bincount(k, minlength=len(cortes)).astype(float)
    p = cuenta[cuenta > 0] / cuenta.sum()
    return float(-(p * np.log2(p)).sum())


def entropia_maxima(n_clases=6):
    return float(np.log2(n_clases))


def discrimina(valores, cortes):
    """(cv, entropia, alerta). alerta=True si el indice no separa."""
    cv = coef_variacion(valores)
    h = entropia_shannon(valores, cortes)
    return cv, h, cv < CV_MINIMO


def estadisticos(valores):
    """(n, promedio, mediana, minimo, maximo) ignorando NaN."""
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return 0, 0.0, 0.0, 0.0, 0.0
    return (int(v.size), float(v.mean()), float(np.median(v)),
            float(v.min()), float(v.max()))


# ─────────────────────────────── riesgo (a futuro) ───────────────────────────

def calcular_probabilidad_falla(gdf):
    """Probabilidad de falla por tramo, en [0, 1]. TODAVIA NO IMPLEMENTADA.

    Consecuencia de falla NO es riesgo. El tablero entero mide consecuencia: que
    tan grave es que este tramo falle. Cuan probable es que falle es otra cosa, y
    priorizar por consecuencia sola manda cuadrillas a colectores enormes recien
    construidos.

        riesgo = consecuencia * probabilidad

    Los insumos ya estan en la capa de Colectores y no hace falta relevar nada
    nuevo para empezar:

        antiguedad      años desde la construccion (columna 'antiguedad'/'anio')
        material        'material' — hormigon, PVC, ceramica envejecen distinto
        diametro        'diametro' / dim1, dim2
        obstrucciones   'obstrucciones' — historial de eventos, el unico insumo
                        que es evidencia directa de deterioro y no un proxy
        profundidad     de la capa de Registros, via cota de zampeado
        pendiente       'Pendiente' — la pendiente baja sedimenta

    Lo que falta NO es codigo sino el modelo de deterioro: una curva de
    supervivencia por material calibrada contra fallas observadas. cf_pf_core ya
    tiene un PF (calculos/probabilidad_falla.py) pero sale de inspecciones PACP,
    o sea que solo existe donde hubo camara — cubre una fraccion de la red y no
    sirve para priorizar donde nadie miro todavia.

    Cuando este definido, engancharlo aca y usar `riesgo()`. El resto del tablero
    ya esta preparado para recibir una columna mas.
    """
    raise NotImplementedError(
        "El modelo de deterioro todavia no esta definido. Ver el docstring: "
        "los insumos estan, falta la curva de supervivencia por material."
    )


def riesgo(consecuencia, probabilidad):
    """Riesgo compuesto = consecuencia * probabilidad, elemento a elemento.

    Queda escrito ahora para que el dia que exista calcular_probabilidad_falla
    no haya que discutir la convencion: consecuencia en 1-6, probabilidad en
    [0, 1], riesgo en [0, 6] y comparable con la consecuencia.
    """
    c = np.asarray(consecuencia, dtype=float)
    p = np.asarray(probabilidad, dtype=float)
    return c * p
