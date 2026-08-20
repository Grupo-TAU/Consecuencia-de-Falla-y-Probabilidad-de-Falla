"""
Sensibilidad del ranking al vector de pesos (Monte Carlo sobre el simplex).

El problema que resuelve: los pesos 30/30/15/25/0 son una decision politica, no
un hecho. Cualquiera puede discutirlos, y si el orden de prioridad se da vuelta
cuando se los mueve, el ranking no sirve para defender un plan de obra.

La pregunta que contesta no es "cual es el tramo mas critico" sino "cuales son
criticos DECIDA LO QUE DECIDA el que pondera". Se muestrean vectores de peso
uniformemente del simplex —Dirichlet(alpha=1) es exactamente eso— y se mira
cuantas veces cada tramo termina arriba.

    Robusto     : casi siempre en el top. La inversion segura: se puede defender
                  frente a cualquier ponderacion razonable.
    Volatil     : su lugar depende de que criterio se privilegie. NO es ruido —
                  son los tramos que hay que llevar a la mesa de decision,
                  porque ahi la ponderacion realmente cambia el resultado.
    Descartable : nunca entra al top. Se puede sacar de la discusion.
"""
import numpy as np
import pandas as pd

# Un tramo es robusto si entra al top en esta proporcion de escenarios.
UMBRAL_ROBUSTO = 0.80
# "Top" = el mejor 10 % de cada escenario.
FRACCION_TOP = 0.10
# Volatil: pct_std por encima de este percentil de la propia distribucion.
PERCENTIL_VOLATIL = 90.0

CATEGORIAS = ["Robusto", "Volátil", "Descartable", "Intermedio"]

# Filas del bloque de simulaciones. 60k x 250 float64 ~ 120 MB: entra comodo en
# memoria y no cambia el resultado, solo el pico. Sin bloques, 1000 simulaciones
# reservan medio giga de una y el argsort duplica eso.
BLOQUE_DEFAULT = 250


def _percentiles_por_columna(S):
    """Percentil [0, 1] de cada fila dentro de su columna (una simulacion).

    Doble argsort = rango. Es O(n log n) por columna pero vectorizado sobre todas
    las columnas del bloque a la vez, que es lo que lo hace viable para 60k x 1000.
    """
    n = S.shape[0]
    if n < 2:
        return np.zeros_like(S)
    rangos = np.argsort(np.argsort(S, axis=0), axis=0)
    return rangos / (n - 1)


def monte_carlo(X, n_sim=1000, seed=42, bloque=BLOQUE_DEFAULT,
                fraccion_top=FRACCION_TOP, progreso=None):
    """Simula n_sim vectores de peso y resume el comportamiento de cada tramo.

    X : (n_tramos, n_criterios) — la matriz de indices.matriz_grupos.
    progreso : callable(fraccion, etiqueta) para la barra del tablero.

    Devuelve un DataFrame con una fila por tramo:
        pct_medio   percentil promedio en todos los escenarios (0 = el menos
                    critico, 1 = el mas critico).
        pct_std     desvio de ese percentil. Es la volatilidad del ranking: cuanto
                    se mueve el tramo segun quien pondere.
        frec_top10  proporcion de escenarios en los que quedo en el top.

    El acumulado se lleva en sumas (media y suma de cuadrados) para no guardar la
    matriz entera de percentiles, que a 1000 simulaciones son 486 MB.
    """
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    if n == 0 or k == 0:
        return pd.DataFrame({"pct_medio": [], "pct_std": [], "frec_top10": []})

    rng = np.random.default_rng(seed)
    suma = np.zeros(n)
    suma2 = np.zeros(n)
    top = np.zeros(n)
    corte_top = 1.0 - fraccion_top

    hechas = 0
    while hechas < n_sim:
        m = min(bloque, n_sim - hechas)
        W = rng.dirichlet(np.ones(k), size=m)          # (m, k), cada fila suma 1
        S = X @ W.T                                    # (n, m)
        pct = _percentiles_por_columna(S)
        suma += pct.sum(axis=1)
        suma2 += (pct ** 2).sum(axis=1)
        top += (pct >= corte_top).sum(axis=1)
        hechas += m
        if progreso:
            progreso(hechas / n_sim, f"{hechas}/{n_sim} escenarios")

    media = suma / n_sim
    # var = E[x^2] - E[x]^2, con clip porque el redondeo puede dar -1e-17.
    var = np.clip(suma2 / n_sim - media ** 2, 0.0, None)
    return pd.DataFrame({
        "pct_medio": media,
        "pct_std": np.sqrt(var),
        "frec_top10": top / n_sim,
    })


def clasificar_robustez(res, umbral_robusto=UMBRAL_ROBUSTO,
                        percentil_volatil=PERCENTIL_VOLATIL):
    """Agrega la columna 'categoria' al resultado de monte_carlo.

    El orden de las reglas importa: robusto gana sobre volatil. Un tramo puede
    tener percentil alto y variable y aun asi no bajar nunca del top —esa
    variabilidad no cambia la decision, asi que llamarlo volatil confundiria.

    El corte de volatilidad es relativo (un percentil de la propia distribucion)
    y no absoluto: cuanto se mueve un ranking depende de cuantos criterios haya y
    de que tan correlacionados esten, asi que un numero fijo no significa lo
    mismo entre capas.
    """
    res = res.copy()
    if res.empty:
        res["categoria"] = pd.Series(dtype="object")
        return res

    corte_vol = float(np.percentile(res["pct_std"], percentil_volatil))
    categoria = np.full(len(res), "Intermedio", dtype=object)
    categoria[res["pct_std"].to_numpy() >= corte_vol] = "Volátil"
    categoria[res["frec_top10"].to_numpy() <= 0.0] = "Descartable"
    categoria[res["frec_top10"].to_numpy() >= umbral_robusto] = "Robusto"
    res["categoria"] = categoria
    return res


def resumen_categorias(res):
    """{categoria: cantidad}, en el orden de CATEGORIAS."""
    cuenta = res["categoria"].value_counts().to_dict() if "categoria" in res else {}
    return {c: int(cuenta.get(c, 0)) for c in CATEGORIAS}


def impacto_marginal(X, nombres, pesos_base, top_n=100):
    """Cuanto cambia el ranking si un criterio se lleva TODO el peso.

    Para cada criterio j se compara el ranking base (pesos actuales) contra el
    ranking con w = e_j, o sea el escenario extremo "solo importa este criterio".

    Devuelve un DataFrame con:
        spearman     correlacion de rangos sobre la capa entera. Cerca de 1 = ese
                     criterio ya manda el ranking; cerca de 0 o negativo = mueve
                     el orden por completo.
        top_comun    cuantos de los top_n del ranking base siguen en el top_n del
                     escenario extremo. Es la version accionable de lo mismo: no
                     interesa el orden de los 60k sino quien sobrevive arriba.

    Un criterio con spearman alto y top_comun bajo esta reordenando justo la
    punta, que es la parte que se ejecuta. Por eso van los dos numeros.
    """
    from scipy.stats import spearmanr

    X = np.asarray(X, dtype=float)
    pesos_base = np.asarray(pesos_base, dtype=float)
    n, k = X.shape
    top_n = min(top_n, n)
    if n == 0 or k == 0 or top_n == 0:
        return pd.DataFrame({"criterio": [], "spearman": [], "top_comun": []})

    total = pesos_base.sum()
    base = X @ (pesos_base / total) if total > 0 else X.mean(axis=1)
    top_base = set(np.argsort(-base)[:top_n].tolist())

    filas = []
    for j, nombre in enumerate(nombres):
        alt = X[:, j]
        # nan_policy no aplica: X no tiene NaN por construccion. Una columna
        # constante si da NaN en spearman, y eso es informacion: el criterio no
        # ordena nada. Se reporta como 0.
        rho = spearmanr(base, alt).statistic
        top_alt = set(np.argsort(-alt)[:top_n].tolist())
        filas.append({
            "criterio": nombre,
            "spearman": 0.0 if rho != rho else float(rho),
            "top_comun": len(top_base & top_alt),
            "top_n": top_n,
        })
    return pd.DataFrame(filas)
