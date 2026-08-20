"""
Del ranking al plan de obra: que tramos entran con el presupuesto que hay.

Es un knapsack 0/1 — elegir un subconjunto de tramos que maximice la criticidad
mitigada sin pasarse del presupuesto — con 60.000 items, asi que no se resuelve
exacto y no hace falta.

METODO Y OPTIMALIDAD (esto es lo que hay que poder defender):

  Se usa greedy por ratio beneficio/costo con relleno, mas una pasada de
  intercambios 1-1. El greedy por ratio es optimo para el knapsack FRACCIONARIO;
  para el 0/1 no lo es, pero la diferencia esta acotada:

      valor_greedy  >=  OPT - max(beneficio de un item)

  Con 60.000 tramos y un presupuesto que cubre miles, un item vale una fraccion
  minuscula del total: la cota es de decimas de porciento, no de ordenes de
  magnitud.

  Y la cota no se estima, se calcula: `cota_fraccionaria` resuelve el relajado
  LP en forma cerrada (ordenar por ratio y partir el ultimo item), que es una
  cota superior exacta de OPT. El gap que reporta `comparar` es real, no una
  suposicion. Por eso no hace falta un solver MILP: PuLP u OR-Tools sobre 60.000
  binarias tardarian minutos u horas para cerrar un gap que ya sabemos que es
  menor al 1 %.

  La estrategia por cluster es DELIBERADAMENTE subóptima frente a ese objetivo.
  Toma zonas HH completas y va a puntuar peor en criticidad-por-peso, porque
  arrastra tramos flojos que estan en el medio de la zona. Lo que el modelo no
  ve es la movilizacion: mandar una cuadrilla a 40 tramos contiguos cuesta menos
  por tramo que mandarla a 40 tramos desparramados. El costo por metro de este
  modulo es uniforme y no captura esa economia de escala, asi que la comparacion
  hay que leerla sabiendo que el numero de la columna «criticidad mitigada»
  favorece por construccion a las estrategias que eligen tramos sueltos.
"""
import numpy as np
import pandas as pd

# Costo de referencia por metro de colector intervenido. Es un ORDEN DE MAGNITUD
# para parametrizar, no un presupuesto: no sale de una licitacion.
COSTO_POR_METRO_DEFAULT = 15000.0

ESTRATEGIAS = {
    "criticidad": "Greedy por criticidad pura",
    "ratio": "Greedy por criticidad/costo",
    "cluster": "Por zona HH completa",
}


def costo_estimado(gdf, col_costo=None, costo_por_metro=COSTO_POR_METRO_DEFAULT,
                   col_longitud=None):
    """Costo de intervenir cada tramo. Devuelve (costos, es_estimado).

    Si la capa trae una columna de costo real se usa esa. Si no, se estima como
    longitud x costo_por_metro, y el flag avisa: es una estimacion parametrica
    lineal, no un presupuesto. Ignora profundidad, material, si hay que romper
    pavimento y el desvio de transito, que en la practica dominan.

    La longitud sale de la columna de la capa (viene de campo) y no de la
    geometria: el campo Longitud es el dato relevado, y recalcularlo desde la
    geometria da otro numero.
    """
    if col_costo and col_costo in gdf.columns:
        c = gdf[col_costo].to_numpy(dtype=float)
        return np.where(np.isfinite(c) & (c > 0), c, np.nan), False

    if col_longitud and col_longitud in gdf.columns:
        largo = gdf[col_longitud].to_numpy(dtype=float)
    else:
        largo = gdf.geometry.length.to_numpy(dtype=float)
    largo = np.where(np.isfinite(largo) & (largo > 0), largo, 0.0)
    return largo * float(costo_por_metro), True


def _orden_valido(valores, costos):
    """Items utilizables: costo positivo y finito, beneficio finito."""
    return (np.isfinite(costos) & (costos > 0) & np.isfinite(valores))


def greedy(valores, costos, presupuesto, clave=None):
    """Selecciona items en el orden que dicte `clave` (desc), rellenando huecos.

    clave : array con el criterio de orden. None = beneficio/costo (el ratio).

    "Rellenando" no es un detalle: el greedy de manual se detiene en el primer
    item que no entra y deja plata sin gastar. Seguir recorriendo y meter todo lo
    que quepa es estrictamente mejor y no cuesta nada.

    Devuelve una mascara booleana del tamaño de `valores`.
    """
    valores = np.asarray(valores, dtype=float)
    costos = np.asarray(costos, dtype=float)
    n = len(valores)
    elegidos = np.zeros(n, dtype=bool)
    usables = _orden_valido(valores, costos)
    if not usables.any() or presupuesto <= 0:
        return elegidos

    if clave is None:
        # El ratio se calcula solo donde el item es usable: con costo 0 o valor
        # infinito la division avisa por consola sin que haya nada que arreglar.
        clave = np.full(n, -np.inf)
        clave[usables] = valores[usables] / costos[usables]
    clave = np.asarray(clave, dtype=float)
    clave = np.where(usables, clave, -np.inf)

    orden = np.argsort(-clave, kind="stable")
    # Recorrido acumulado vectorizado hasta donde alcanza el presupuesto, y
    # despues el relleno item por item. Sin el corte previo serian 60.000
    # iteraciones de Python; asi son unos pocos miles.
    costos_ord = costos[orden]
    acum = np.cumsum(np.where(np.isfinite(costos_ord), costos_ord, 0.0))
    corte = int(np.searchsorted(acum, presupuesto, side="right"))
    elegidos[orden[:corte]] = True
    restante = presupuesto - (acum[corte - 1] if corte > 0 else 0.0)

    for i in orden[corte:]:
        if not usables[i]:
            continue
        if costos[i] <= restante:
            elegidos[i] = True
            restante -= costos[i]
            if restante <= 0:
                break
    return elegidos


def cota_fraccionaria(valores, costos, presupuesto):
    """Cota superior EXACTA del optimo: el knapsack fraccionario.

    Permitir intervenir "medio tramo" no tiene sentido fisico, pero relajar la
    restriccion solo puede mejorar el optimo, asi que este numero es >= OPT. Es
    lo que convierte al gap reportado en una garantia y no en una impresion.
    """
    valores = np.asarray(valores, dtype=float)
    costos = np.asarray(costos, dtype=float)
    usables = _orden_valido(valores, costos)
    if not usables.any() or presupuesto <= 0:
        return 0.0
    v, c = valores[usables], costos[usables]
    orden = np.argsort(-(v / c))
    v, c = v[orden], c[orden]
    acum = np.cumsum(c)
    corte = int(np.searchsorted(acum, presupuesto, side="right"))
    total = float(v[:corte].sum())
    if corte < len(v):
        sobra = presupuesto - (acum[corte - 1] if corte > 0 else 0.0)
        total += float(v[corte] * sobra / c[corte])
    return total


def mejora_local(elegidos, valores, costos, presupuesto, candidatos=400):
    """Intercambios 1-1 sobre la solucion greedy: sacar uno, meter uno mejor.

    Mira solo los `candidatos` items no elegidos de mayor beneficio contra los
    elegidos de menor beneficio. Todos contra todos serian 10^9 pares para ganar
    decimas: el gap ya esta acotado por `cota_fraccionaria` y en la practica esta
    pasada lo cierra casi entero.

    Devuelve una mascara nueva; nunca empeora la solucion ni se pasa del presupuesto.
    """
    valores = np.asarray(valores, dtype=float)
    costos = np.asarray(costos, dtype=float)
    elegidos = elegidos.copy()
    usables = _orden_valido(valores, costos)

    holgura = presupuesto - float(costos[elegidos].sum())
    fuera = np.flatnonzero(usables & ~elegidos)
    if fuera.size == 0:
        return elegidos
    fuera = fuera[np.argsort(-valores[fuera])][:candidatos]

    for i in fuera:
        if valores[i] <= 0:
            break
        if costos[i] <= holgura:
            elegidos[i] = True
            holgura -= costos[i]
            continue
        dentro = np.flatnonzero(elegidos)
        if dentro.size == 0:
            continue
        # El unico intercambio que puede ayudar: sacar el de menor beneficio que
        # libere lo suficiente. Si ese ya vale mas que el que entra, ninguno sirve.
        libera = costos[i] - holgura
        aptos = dentro[costos[dentro] >= libera]
        if aptos.size == 0:
            continue
        j = aptos[np.argmin(valores[aptos])]
        if valores[j] >= valores[i]:
            continue
        elegidos[j] = False
        elegidos[i] = True
        holgura += costos[j] - costos[i]
    return elegidos


def por_cluster(valores, costos, presupuesto, zona):
    """Toma zonas HH completas, ordenadas por beneficio/costo de la zona.

    zona : id de zona por tramo, -1 para los que no pertenecen a ninguna.

    Una zona entra entera o no entra: es lo que hace que el plan sea ejecutable
    como obra. Si sobra presupuesto despues de la ultima zona completa se rellena
    por ratio, pero SOLO con tramos que no pertenecen a ninguna zona: agarrar
    tramos sueltos de una zona que quedo afuera romperia la promesa que hace esta
    estrategia —y con ella la economia de movilizacion que la justifica— para
    ganar unos puntos de beneficio que el modelo de costos ni siquiera ve.
    """
    valores = np.asarray(valores, dtype=float)
    costos = np.asarray(costos, dtype=float)
    zona = np.asarray(zona)
    elegidos = np.zeros(len(valores), dtype=bool)
    validos = _orden_valido(valores, costos)

    df = pd.DataFrame({"zona": zona, "v": np.where(validos, valores, 0.0),
                       "c": np.where(validos, costos, 0.0)})
    agg = df[df["zona"] >= 0].groupby("zona").agg(v=("v", "sum"), c=("c", "sum"))
    agg = agg[agg["c"] > 0]
    if not agg.empty:
        agg = agg.assign(ratio=agg["v"] / agg["c"]).sort_values("ratio", ascending=False)
        restante = float(presupuesto)
        adentro = []
        for zid, fila in agg.iterrows():
            if fila["c"] <= restante:
                adentro.append(zid)
                restante -= fila["c"]
        if adentro:
            elegidos |= np.isin(zona, adentro) & validos
    else:
        restante = float(presupuesto)

    if restante > 0:
        sueltos = validos & ~elegidos & (zona < 0)
        if sueltos.any():
            relleno = greedy(np.where(sueltos, valores, 0.0),
                             np.where(sueltos, costos, np.inf), restante)
            elegidos |= relleno
    return elegidos


def beneficio_de(criticidad, longitud=None, ponderar_por_longitud=True):
    """Que se maximiza. Devuelve el vector de beneficio por tramo.

    Ponderar por longitud es el default y no es cosmetico: sin eso, 100 metros de
    colector critico valen lo mismo que 5 metros, y el optimizador se llena de
    tramos cortitos porque son baratos. Con criticidad a secas el ranking premia
    la fragmentacion; con criticidad x longitud premia atender mas red critica.
    """
    c = np.asarray(criticidad, dtype=float)
    if not ponderar_por_longitud or longitud is None:
        return c
    largo = np.asarray(longitud, dtype=float)
    return c * np.where(np.isfinite(largo) & (largo > 0), largo, 0.0)


def greedies_equivalentes(costos, longitud, tol=1e-9):
    """True si el greedy por criticidad y el greedy por ratio ordenan igual.

    Pasa siempre que el costo sea longitud x constante, que es el caso cuando no
    hay columna de costo real: ahi

        beneficio/costo = (criticidad x longitud) / (longitud x $/m) ∝ criticidad

    o sea que el ratio ES la criticidad reescalada y las dos estrategias eligen
    exactamente los mismos tramos. Compararlas en esa situacion no dice nada, y
    presentar dos filas casi iguales como si fueran alternativas es peor que no
    compararlas. El tablero avisa cuando esto pasa.

    La comparacion recien tiene contenido con costos reales, donde un tramo
    profundo bajo pavimento cuesta mucho mas por metro que uno somero en tierra.
    """
    if longitud is None:
        return False
    c = np.asarray(costos, dtype=float)
    l = np.asarray(longitud, dtype=float)
    ok = np.isfinite(c) & np.isfinite(l) & (l > 0)
    if ok.sum() < 2:
        return False
    razon = c[ok] / l[ok]
    return bool(np.nanmax(razon) - np.nanmin(razon) <= tol * max(1.0, np.nanmean(razon)))


def comparar(valores, costos, presupuesto, zona=None, longitud=None,
             criticidad=None):
    """Corre las tres estrategias y las devuelve en una tabla comparable.

    criticidad : el valor con el que ordena la estrategia "criticidad pura". Es
        distinto de `valores` cuando el beneficio esta ponderado por longitud:
        ordenar por criticidad x longitud no es "criticidad pura", es preferir
        tramos largos, y da una comparacion que no es la que se pidio.

    Devuelve (tabla, mascaras): la tabla es lo que se muestra, las mascaras son
    para pintar el mapa y exportar el plan.

    La columna `gap` es la distancia a la cota fraccionaria: cuanto MENOS podria
    estar dejando sobre la mesa la heuristica. Es una cota, no el error real, que
    es todavia mas chico.
    """
    valores = np.asarray(valores, dtype=float)
    costos = np.asarray(costos, dtype=float)
    largo = (np.asarray(longitud, dtype=float) if longitud is not None
             else np.zeros(len(valores)))
    clave_crit = (np.asarray(criticidad, dtype=float)
                  if criticidad is not None else valores)

    mascaras = {}
    mascaras["criticidad"] = greedy(valores, costos, presupuesto, clave=clave_crit)
    ratio = mejora_local(greedy(valores, costos, presupuesto), valores, costos,
                         presupuesto)
    mascaras["ratio"] = ratio
    if zona is not None:
        mascaras["cluster"] = por_cluster(valores, costos, presupuesto, zona)

    cota = cota_fraccionaria(valores, costos, presupuesto)
    filas = []
    for key, m in mascaras.items():
        total = float(valores[m].sum())
        gasto = float(costos[m].sum())
        filas.append({
            "estrategia": ESTRATEGIAS[key],
            "key": key,
            "tramos": int(m.sum()),
            "longitud": float(largo[m].sum()),
            "beneficio": total,
            "costo": gasto,
            "uso_presupuesto": gasto / presupuesto if presupuesto > 0 else 0.0,
            "gap": (cota - total) / cota if cota > 0 else 0.0,
        })
    tabla = pd.DataFrame(filas).sort_values("beneficio", ascending=False)
    tabla.attrs["cota"] = cota
    tabla.attrs["greedies_equivalentes"] = greedies_equivalentes(costos, longitud)
    return tabla.reset_index(drop=True), mascaras
