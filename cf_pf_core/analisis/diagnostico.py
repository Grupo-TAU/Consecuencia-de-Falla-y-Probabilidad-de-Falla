"""
Diagnostico del indice: ¿esta bien construido?

Los otros modulos usan el indice; este lo audita. Tres preguntas, en orden de
gravedad:

  1. ¿Hay criterios que miden lo mismo? Dos columnas muy correlacionadas hacen
     que el peso efectivo no sea el que dice el slider — se esta ponderando dos
     veces la misma senal sin saberlo.
  2. ¿Cuantos grados de libertad reales hay? Si dos componentes principales
     explican casi todo, los cinco sliders son teatro.
  3. ¿Hay criterios que no discriminan? Una columna con el 99 % de los tramos en
     un valor no aporta informacion, y su peso es ruido que le saca lugar a los
     criterios que si separan.

Todo devuelve datos; la prosa se arma en `conclusiones()` para que el tablero no
tenga que interpretarlos y el usuario no tenga que deducirlos.
"""
import numpy as np
import pandas as pd

from . import indices as ix

# Por encima de esto, dos criterios estan midiendo lo mismo.
UMBRAL_REDUNDANCIA = 0.80
# Proporcion de tramos en un solo valor a partir de la cual el criterio es inerte.
UMBRAL_CONCENTRACION = 0.90
# Varianza acumulada que, si se alcanza con pocas componentes, delata sliders de mas.
UMBRAL_VARIANZA = 0.90


def correlacion_spearman(df, columnas):
    """Matriz de correlacion de rangos entre columnas. DataFrame cuadrado.

    Spearman y no Pearson porque los CF son ordinales 1-6: lo que importa es si
    ordenan igual los tramos, no si la relacion es lineal.
    """
    import warnings

    from scipy.stats import ConstantInputWarning, spearmanr

    cols = list(columnas)
    X = df[cols].to_numpy(dtype=float)
    if len(cols) < 2:
        return pd.DataFrame(np.ones((len(cols), len(cols))), index=cols, columns=cols)
    # Una columna constante es un caso ESPERADO en estas capas —CF_Obstrucciones
    # esta al 99 % en un valor— y ya se maneja abajo poniendo 0. El warning de
    # scipy solo ensuciaria la consola de quien corre el tablero.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConstantInputWarning)
        rho = spearmanr(X).statistic
    rho = np.atleast_2d(np.asarray(rho, dtype=float))
    # Una columna constante da NaN contra todas: no ordena nada, asi que no
    # correlaciona con nada. 0 es la lectura correcta, no "sin dato".
    rho = np.nan_to_num(rho, nan=0.0)
    np.fill_diagonal(rho, 1.0)
    return pd.DataFrame(rho, index=cols, columns=cols)


def pares_redundantes(matriz, umbral=UMBRAL_REDUNDANCIA):
    """[(a, b, rho), ...] con |rho| sobre el umbral, de mayor a menor."""
    cols = list(matriz.columns)
    pares = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            rho = float(matriz.iloc[i, j])
            if abs(rho) >= umbral:
                pares.append((cols[i], cols[j], rho))
    return sorted(pares, key=lambda t: -abs(t[2]))


def pca(df, columnas):
    """PCA sobre los criterios estandarizados.

    Estandarizar es obligatorio aca aunque todos los CF vivan en 1-6: sus
    varianzas son muy distintas (CF_Obstrucciones casi no varia, CF_Antiguedad
    varia mucho) y sin estandarizar el PCA describiria eso y no la estructura.

    Devuelve dict con:
        varianza    proporcion explicada por componente
        acumulada   su suma acumulada
        loadings    DataFrame (criterio x componente) — cuanto pesa cada criterio
                    en cada componente
        n_para_90   componentes necesarias para el 90 %
    """
    from sklearn.decomposition import PCA

    cols = list(columnas)
    X = df[cols].to_numpy(dtype=float)
    sd = X.std(axis=0)
    # Una columna constante tendria sd=0 y daria NaN al dividir. Se deja en 0:
    # una variable sin varianza no aporta a ninguna componente, que es la verdad.
    sd_seguro = np.where(sd > 0, sd, 1.0)
    Z = (X - X.mean(axis=0)) / sd_seguro
    Z[:, sd == 0] = 0.0

    modelo = PCA().fit(Z)
    var = modelo.explained_variance_ratio_
    acum = np.cumsum(var)
    nombres_comp = [f"PC{i + 1}" for i in range(len(var))]
    loadings = pd.DataFrame(modelo.components_.T, index=cols, columns=nombres_comp)
    n90 = int(np.searchsorted(acum, UMBRAL_VARIANZA) + 1)
    return {
        "varianza": var,
        "acumulada": acum,
        "loadings": loadings,
        "componentes": nombres_comp,
        "n_para_90": min(n90, len(var)),
    }


def comparar_operadores(X, pesos, cortes=None, n_clases=6):
    """Los tres operadores de agregacion, medidos con la misma vara.

    Devuelve {operador: {valores, cv, entropia, alerta, n, promedio, ...}}.

    Los cortes se pasan explicitos para que la entropia sea comparable: medida
    sobre cuantiles propios, cualquier operador da la maxima entropia posible por
    construccion y la comparacion no dice nada.
    """
    cortes = cortes if cortes is not None else ix.cortes_fijos(n_clases)
    salida = {}
    for op in ix.OPERADORES:
        v = ix.agregar(X, pesos, op)
        cv, h, alerta = ix.discrimina(v, cortes)
        n, prom, med, mini, maxi = ix.estadisticos(v)
        salida[op] = {
            "valores": v, "cv": cv, "entropia": h, "alerta": alerta,
            "n": n, "promedio": prom, "mediana": med, "minimo": mini,
            "maximo": maxi,
        }
    return salida


def distribucion_criterios(df, columnas, n_clases=6):
    """Conteo por clase 1..n de cada criterio, y cuan concentrado esta.

    Devuelve {criterio: {conteos, valores, concentracion, valor_dominante, inerte}}.
    `concentracion` es la proporcion del valor mas frecuente: es el numero que
    delata a un criterio que en la practica es una constante con excepciones.
    """
    salida = {}
    for col in columnas:
        v = df[col].to_numpy(dtype=float)
        v = v[np.isfinite(v)]
        k = np.clip(v.astype(int), 1, n_clases)
        conteos = np.bincount(k, minlength=n_clases + 1)[1:].astype(int)
        total = int(conteos.sum())
        idx = int(conteos.argmax()) if total else 0
        conc = float(conteos[idx] / total) if total else 0.0
        salida[col] = {
            "conteos": conteos.tolist(),
            "valores": [str(i + 1) for i in range(n_clases)],
            "concentracion": conc,
            "valor_dominante": idx + 1,
            "n": total,
            "inerte": conc >= UMBRAL_CONCENTRACION,
        }
    return salida


def peso_desperdiciado(distribuciones, pesos_efec):
    """Cuanto del peso total se va en criterios que no discriminan.

    Es el numero que convierte "CF_Obstrucciones esta concentrado" en algo
    accionable: ese porcentaje del indice esta comprado y no compra separacion.
    """
    return float(sum(pesos_efec.get(c, 0.0)
                     for c, d in distribuciones.items() if d["inerte"]))


# ─────────────────────────────── prosa ───────────────────────────────────────

def _num(x, dec=2):
    """Numero con coma decimal. Aplicar .replace('.', ',') sobre la frase entera
    convierte tambien los puntos de la oracion, asi que se formatea solo el numero."""
    return f"{x:.{dec}f}".replace(".", ",")


def _pct(x):
    return f"{_num(x * 100, 1)} %"


def conclusiones(corr, pca_res, operadores, distribuciones, pesos_efec,
                 pesos_parejos=None):
    """Las conclusiones en prosa, autogeneradas. Devuelve lista de (nivel, texto).

    nivel: 'alerta' | 'aviso' | 'ok' — el tablero lo usa para el color.

    Se escribe aca y no en el tab para que las mismas frases sirvan en el HTML,
    en un informe o en la consola, y para que sean testeables.
    """
    salida = []

    # 1. Redundancia entre criterios.
    pares = pares_redundantes(corr)
    if pares:
        detalle = "; ".join(f"<b>{a}</b> y <b>{b}</b> (ρ = {_num(rho)})"
                            for a, b, rho in pares[:3])
        salida.append((
            "alerta",
            f"Hay {len(pares)} par(es) de criterios que miden prácticamente lo "
            f"mismo: {detalle}. Cuando dos criterios correlacionan tan alto, el "
            "peso que los sliders reparten entre ellos se acumula sobre una sola "
            "señal: el peso efectivo de esa dimensión es la suma de los dos, no "
            "cada uno por separado."))
    else:
        salida.append((
            "ok",
            f"Ningún par de criterios supera ρ = {_num(UMBRAL_REDUNDANCIA)}: no hay "
            "redundancia evidente y los pesos de los sliders se reparten sobre "
            "señales distintas."))

    # 2. Grados de libertad reales.
    acum = pca_res["acumulada"]
    n_total = len(acum)
    n90 = pca_res["n_para_90"]
    dos = _pct(float(acum[1])) if n_total >= 2 else "—"
    if n_total >= 2 and acum[1] >= UMBRAL_VARIANZA:
        salida.append((
            "alerta",
            f"Dos componentes principales explican el {dos} de la varianza: hay "
            f"{n_total} sliders para 2 grados de libertad reales. Mover los "
            "demás no cambia sustancialmente el ordenamiento."))
    else:
        salida.append((
            "ok",
            f"Hacen falta {n90} de {n_total} componentes para explicar el 90 % de "
            f"la varianza (dos solas llegan al {dos}). Los criterios aportan "
            "información en buena medida independiente, así que los sliders "
            "representan decisiones efectivamente distintas."))

    # 3. Criterios que no discriminan.
    inertes = [(c, d) for c, d in distribuciones.items() if d["inerte"]]
    if inertes:
        detalle = "; ".join(
            f"<b>{c}</b> ({_pct(d['concentracion'])} en el valor {d['valor_dominante']})"
            for c, d in sorted(inertes, key=lambda t: -t[1]["concentracion"]))
        perdido = peso_desperdiciado(distribuciones, pesos_efec)
        salida.append((
            "alerta",
            f"Criterios que casi no varían: {detalle}. No aportan información para "
            f"ordenar tramos, y se llevan el {_pct(perdido)} del peso efectivo del "
            "índice: ese peso no está comprando separación."))

    # 4. Peso efectivo vs. reparto parejo (columnas en mas de un grupo).
    if pesos_parejos:
        desvios = [(c, pesos_efec.get(c, 0.0), d)
                   for c, d in pesos_parejos.items()
                   if abs(pesos_efec.get(c, 0.0) - d) > 1e-6]
        if desvios:
            detalle = "; ".join(
                f"<b>{c}</b>: {_pct(e)} efectivo contra {_pct(d)} parejo"
                for c, e, d in sorted(desvios, key=lambda t: -abs(t[1] - t[2]))[:3])
            salida.append((
                "aviso",
                "Hay columnas que participan en más de un grupo, así que su peso "
                f"real no es el que sugieren los sliders: {detalle}. El toggle "
                "«descontar variables duplicadas» del panel de pesos las reparte "
                "en partes iguales entre los grupos que las usan."))

    # 5. Que operador separa mejor.
    if operadores:
        mejor_key, mejor = max(operadores.items(), key=lambda kv: kv[1]["entropia"])
        actual = operadores.get("media_aritmetica")
        if actual is not None and actual["alerta"]:
            salida.append((
                "alerta",
                "La media aritmética tiene un coeficiente de variación de "
                f"{_num(actual['cv'], 3)}, por debajo de {_num(ix.CV_MINIMO)}: el "
                "índice prácticamente no separa tramos y el mapa se lee como una "
                "mancha de un solo color."))
        if mejor_key != "media_aritmetica" and actual is not None:
            salida.append((
                "aviso",
                f"El operador que más separa es <b>{ix.OPERADORES[mejor_key]}</b>: "
                f"entropía {_num(mejor['entropia'])} contra "
                f"{_num(actual['entropia'])} de la media aritmética, y CV "
                f"{_num(mejor['cv'], 3)} contra {_num(actual['cv'], 3)}. Promediar "
                "criterios acerca todo a la media por construcción; el máximo "
                "conserva los picos, al costo de perder la noción de cuántos "
                "criterios están mal a la vez."))

    return salida
