"""
Tests de cf_pf_core.analisis.

Lo que se protege acá, en orden de importancia:

  1. Que indices.criticidad_vectorizada dé EXACTAMENTE lo mismo que
     criticidad.calcular. Son dos implementaciones de la misma fórmula (una por
     filas para escribir la capa, otra matricial para el tablero) y el día que
     diverjan, el tablero va a estar mostrando un índice que no es el que se
     entregó, sin que nada falle.

  2. Que el descuento de variables duplicadas conserve la escala 1–6. Es la parte
     fácil de romper: si al repartir el peso de una columna repetida no se
     renormaliza, la criticidad se hunde y el mapa se ve más verde sin avisar.

  3. Que las heurísticas del knapsack nunca se pasen del presupuesto ni superen
     la cota fraccionaria, que son las dos cosas que harían indefendible un plan
     de obra.
"""
import numpy as np
import pandas as pd
import pytest

from cf_pf_core.analisis import diagnostico, indices, optimizacion, sensibilidad
from cf_pf_core.calculos import criticidad as crit


# ─────────────────────────────── fixtures ────────────────────────────────────

GRUPOS = {
    "Economico": {"peso": 0.30,
                  "params": ["CF_Diametro", "CF_Profundidad", "CF_Ubicacion"]},
    "Social": {"peso": 0.30,
               "params": ["CF_PosicionRelativa", "CF_Prox_SitiosInteres",
                          "CF_Ubicacion"]},
    "Medioambiental": {"peso": 0.15, "params": ["CF_Prox_MedioAmbiental"]},
    "Valorizacion": {"peso": 0.25,
                     "params": ["CF_Antiguedad", "CF_Material",
                                "CF_Obstrucciones"]},
    "Arboles": {"peso": 0.0, "params": ["CF_Arboles"]},
}

COLUMNAS = sorted({p for g in GRUPOS.values() for p in g["params"]})


@pytest.fixture
def df():
    """Capa sintética con la misma forma que la real: CF enteros en 1..6."""
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {c: rng.integers(1, 7, size=400) for c in COLUMNAS})


# ──────────────────────────── equivalencia con el core ───────────────────────

def test_vectorizada_reproduce_criticidad_calcular(df):
    """La razón de ser del módulo: misma fórmula, dos implementaciones."""
    ref = crit.calcular(df, GRUPOS)
    mio = indices.criticidad_vectorizada(df, GRUPOS)
    assert np.allclose(ref.to_numpy(), mio.to_numpy())


def test_vectorizada_con_pesos_arbitrarios(df):
    """No alcanza con los pesos por defecto: el tablero los mueve todo el tiempo."""
    grupos = {n: {**g, "peso": w} for (n, g), w in
              zip(GRUPOS.items(), [0.1, 0.4, 0.05, 0.25, 0.2])}
    assert np.allclose(crit.calcular(df, grupos).to_numpy(),
                       indices.criticidad_vectorizada(df, grupos).to_numpy())


# ─────────────────────────────── pesos y escala ──────────────────────────────

def test_pesos_efectivos_suman_uno(df):
    for descontar in (False, True):
        pe = indices.pesos_efectivos(GRUPOS, descontar)
        assert pytest.approx(sum(pe.values()), abs=1e-9) == 1.0


def test_columna_duplicada_pesa_doble_sin_descuento():
    """CF_Ubicacion está en dos grupos: ése es el hallazgo que el tablero reporta."""
    pe = indices.pesos_efectivos(GRUPOS, descontar_duplicadas=False)
    assert pe["CF_Ubicacion"] == pytest.approx(0.20)
    assert pe["CF_Diametro"] == pytest.approx(0.10)


def test_descuento_empareja_las_duplicadas():
    pe = indices.pesos_efectivos(GRUPOS, descontar_duplicadas=True)
    for col in ("CF_Ubicacion", "CF_Diametro", "CF_Profundidad",
                "CF_PosicionRelativa", "CF_Prox_SitiosInteres"):
        assert pe[col] == pytest.approx(0.12)


def test_descuento_conserva_la_escala(df):
    """Sin renormalizar dentro del grupo, el índice se saldría de 1–6."""
    v = indices.criticidad_vectorizada(df, GRUPOS, descontar_duplicadas=True)
    assert v.min() >= 1.0 - 1e-9
    assert v.max() <= 6.0 + 1e-9


@pytest.mark.parametrize("operador", list(indices.OPERADORES))
def test_operadores_quedan_en_escala(df, operador):
    X, nombres = indices.matriz_grupos(df, GRUPOS)
    v = indices.agregar(X, indices.vector_pesos(GRUPOS, nombres), operador)
    assert v.min() >= 1.0 - 1e-9
    assert v.max() <= 6.0 + 1e-9


def test_geometrica_penaliza_el_desbalance():
    """Dos tramos con el mismo promedio: el desbalanceado tiene que puntuar menos."""
    X = np.array([[6.0, 1.0, 1.0, 1.0], [2.25, 2.25, 2.25, 2.25]])
    w = np.array([0.25] * 4)
    geo = indices.agregar(X, w, "media_geometrica")
    arit = indices.agregar(X, w, "media_aritmetica")
    assert arit[0] == pytest.approx(arit[1])       # mismo promedio
    assert geo[0] < geo[1]                          # el desbalanceado, más bajo


def test_maximo_ignora_grupos_sin_peso():
    """El grupo Arboles está en 0: no puede mandar en el máximo."""
    X = np.array([[2.0, 2.0, 2.0, 2.0, 6.0]])
    w = np.array([0.3, 0.3, 0.15, 0.25, 0.0])
    assert indices.agregar(X, w, "maximo")[0] == pytest.approx(2.0)


# ──────────────────────────── cortes y discriminacion ────────────────────────

def test_cuantiles_reparten_parejo(df):
    v = indices.criticidad_vectorizada(df, GRUPOS).to_numpy()
    cortes = indices.cortes_cuantiles(v, 6)
    k = indices.clasificar(v, cortes)
    conteo = np.bincount(k[k >= 0], minlength=6)
    # Con datos discretos los cuantiles no parten exacto, pero ninguna clase
    # puede quedar con el triple de lo que le toca.
    assert conteo.max() <= 3 * len(v) / 6


def test_entropia_maxima_con_clases_parejas():
    v = np.repeat(np.arange(1, 7), 100).astype(float)
    h = indices.entropia_shannon(v, indices.cortes_fijos(6))
    assert h == pytest.approx(indices.entropia_maxima(6), abs=1e-9)


def test_entropia_cero_si_todo_cae_en_una_clase():
    assert indices.entropia_shannon(np.full(50, 3.0),
                                    indices.cortes_fijos(6)) == 0.0


def test_clasificar_respeta_el_corte_inclusivo():
    """El corte histórico es '<= límite': un 2,0 exacto va a la clase del 2."""
    k = indices.clasificar([1.0, 2.0, 2.001, 6.0], indices.cortes_fijos(6))
    assert k.tolist() == [0, 1, 2, 5]


# ──────────────────────────────── sensibilidad ───────────────────────────────

def test_monte_carlo_devuelve_rangos_validos(df):
    X, _ = indices.matriz_grupos(df, GRUPOS)
    res = sensibilidad.monte_carlo(X, n_sim=120, seed=1)
    assert len(res) == len(df)
    assert res["pct_medio"].between(0, 1).all()
    assert res["frec_top10"].between(0, 1).all()
    assert (res["pct_std"] >= 0).all()


def test_monte_carlo_es_reproducible(df):
    X, _ = indices.matriz_grupos(df, GRUPOS)
    a = sensibilidad.monte_carlo(X, n_sim=100, seed=3)
    b = sensibilidad.monte_carlo(X, n_sim=100, seed=3)
    assert np.allclose(a["pct_medio"], b["pct_medio"])


def test_monte_carlo_no_depende_del_tamano_de_bloque(df):
    """Los bloques existen para acotar la memoria; no pueden cambiar el resultado."""
    X, _ = indices.matriz_grupos(df, GRUPOS)
    entero = sensibilidad.monte_carlo(X, n_sim=200, seed=5, bloque=200)
    partido = sensibilidad.monte_carlo(X, n_sim=200, seed=5, bloque=40)
    assert np.allclose(entero["pct_medio"], partido["pct_medio"])
    assert np.allclose(entero["frec_top10"], partido["frec_top10"])


def test_robusto_gana_sobre_volatil(df):
    """Un tramo que nunca baja del top es robusto aunque su percentil oscile."""
    res = pd.DataFrame({"pct_medio": [0.99, 0.5, 0.1],
                        "pct_std": [0.30, 0.30, 0.0],
                        "frec_top10": [1.0, 0.2, 0.0]})
    cat = sensibilidad.clasificar_robustez(res, percentil_volatil=50)["categoria"]
    assert cat.tolist() == ["Robusto", "Volátil", "Descartable"]


def test_impacto_marginal_detecta_criterio_dominante(df):
    """Con todo el peso en un criterio, ese criterio ES el ranking."""
    X, nombres = indices.matriz_grupos(df, GRUPOS)
    pesos = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    im = sensibilidad.impacto_marginal(X, nombres, pesos, top_n=50)
    fila = im[im["criterio"] == nombres[0]].iloc[0]
    assert fila["spearman"] == pytest.approx(1.0)
    assert fila["top_comun"] == 50


# ──────────────────────────────── diagnostico ────────────────────────────────

def test_correlacion_detecta_columnas_gemelas(df):
    d = df.copy()
    d["CF_Material"] = d["CF_Antiguedad"]          # copia exacta
    corr = diagnostico.correlacion_spearman(d, COLUMNAS)
    pares = diagnostico.pares_redundantes(corr)
    assert ("CF_Antiguedad", "CF_Material", pytest.approx(1.0)) in [
        (a, b, pytest.approx(r)) for a, b, r in pares]


def test_columna_constante_no_rompe_correlacion_ni_pca(df):
    """CF_Obstrucciones real está al 99 % en un valor; el caso límite es constante."""
    d = df.copy()
    d["CF_Obstrucciones"] = 1
    corr = diagnostico.correlacion_spearman(d, COLUMNAS)
    assert np.isfinite(corr.to_numpy()).all()
    pca = diagnostico.pca(d, COLUMNAS)
    assert np.isfinite(pca["varianza"]).all()


def test_distribucion_marca_criterio_inerte(df):
    d = df.copy()
    d.loc[d.index[:396], "CF_Obstrucciones"] = 1   # 99 % en un valor
    dist = diagnostico.distribucion_criterios(d, COLUMNAS)
    assert dist["CF_Obstrucciones"]["inerte"]
    assert dist["CF_Obstrucciones"]["valor_dominante"] == 1
    assert not dist["CF_Diametro"]["inerte"]


def test_conclusiones_generan_texto(df):
    corr = diagnostico.correlacion_spearman(df, COLUMNAS)
    pca = diagnostico.pca(df, COLUMNAS)
    X, nombres = indices.matriz_grupos(df, GRUPOS)
    ops = diagnostico.comparar_operadores(X, indices.vector_pesos(GRUPOS, nombres))
    dist = diagnostico.distribucion_criterios(df, COLUMNAS)
    pe = indices.pesos_efectivos(GRUPOS)
    pp = indices.pesos_efectivos(GRUPOS, True)
    salida = diagnostico.conclusiones(corr, pca, ops, dist, pe, pp)
    assert salida
    assert all(niv in ("alerta", "aviso", "ok") for niv, _ in salida)
    # El aviso de columnas duplicadas tiene que estar: CF_Ubicacion está en dos.
    assert any("duplicadas" in txt for _, txt in salida)


# ──────────────────────────────── optimizacion ───────────────────────────────

@pytest.fixture
def problema():
    rng = np.random.default_rng(11)
    n = 800
    valores = rng.uniform(1, 6, n) * rng.uniform(5, 200, n)
    costos = rng.uniform(5, 200, n) * 1000
    return valores, costos, float(costos.sum() * 0.10)


def test_greedy_respeta_el_presupuesto(problema):
    valores, costos, pres = problema
    for clave in (None, valores):
        m = optimizacion.greedy(valores, costos, pres, clave=clave)
        assert costos[m].sum() <= pres + 1e-6


def test_greedy_rellena_los_huecos(problema):
    """El greedy de manual corta en el primer ítem que no entra y deja plata."""
    valores, costos, pres = problema
    m = optimizacion.greedy(valores, costos, pres)
    sobrante = pres - costos[m].sum()
    # Todo lo que quedó afuera y hubiera entrado, tendría que estar adentro.
    assert not (costos[~m] <= sobrante).any() or sobrante < costos[~m].min()


def test_cota_fraccionaria_domina_a_las_heuristicas(problema):
    valores, costos, pres = problema
    cota = optimizacion.cota_fraccionaria(valores, costos, pres)
    for clave in (None, valores):
        m = optimizacion.greedy(valores, costos, pres, clave=clave)
        assert valores[m].sum() <= cota + 1e-6


def test_mejora_local_no_empeora_ni_se_pasa(problema):
    valores, costos, pres = problema
    base = optimizacion.greedy(valores, costos, pres)
    mejor = optimizacion.mejora_local(base, valores, costos, pres)
    assert valores[mejor].sum() >= valores[base].sum() - 1e-9
    assert costos[mejor].sum() <= pres + 1e-6


def test_por_cluster_toma_zonas_enteras():
    """Una zona entra completa o no entra: es lo que la hace ejecutable como obra."""
    valores = np.array([5.0, 5.0, 5.0, 1.0, 1.0])
    costos = np.array([10.0, 10.0, 10.0, 1.0, 1.0])
    zona = np.array([0, 0, 0, -1, -1])
    m = optimizacion.por_cluster(valores, costos, 32.0, zona)
    assert m[:3].all()          # la zona 0 entera
    assert costos[m].sum() <= 32.0


def test_por_cluster_no_parte_una_zona_que_no_entra():
    valores = np.array([5.0, 5.0, 5.0])
    costos = np.array([10.0, 10.0, 10.0])
    zona = np.array([0, 0, 0])
    m = optimizacion.por_cluster(valores, costos, 25.0, zona)
    assert not m.any()          # 30 > 25: la zona no entra, y no se parte


def test_comparar_devuelve_las_tres_estrategias(problema):
    valores, costos, pres = problema
    zona = np.where(np.arange(len(valores)) % 5 == 0, 0, -1)
    tabla, masc = optimizacion.comparar(valores, costos, pres, zona)
    assert set(masc) == {"criticidad", "ratio", "cluster"}
    for m in masc.values():
        assert costos[m].sum() <= pres + 1e-6
    assert (tabla["gap"] >= -1e-9).all()


def test_greedies_equivalentes_con_costo_uniforme():
    """Con costo = longitud x constante, ratio y criticidad ordenan igual: la
    comparación entre las dos es vacía y el tablero tiene que decirlo."""
    largo = np.array([10.0, 50.0, 120.0, 7.0])
    assert optimizacion.greedies_equivalentes(largo * 15000.0, largo)
    assert not optimizacion.greedies_equivalentes(
        largo * 15000.0 * np.array([1.0, 2.0, 1.0, 3.0]), largo)


def test_costo_estimado_avisa_que_es_estimacion():
    import geopandas as gpd
    from shapely.geometry import LineString

    gdf = gpd.GeoDataFrame(
        {"Longitud": [100.0, 50.0]},
        geometry=[LineString([(0, 0), (0, 90)]), LineString([(0, 0), (0, 40)])],
        crs="EPSG:32721")
    costos, estimado = optimizacion.costo_estimado(
        gdf, costo_por_metro=1000.0, col_longitud="Longitud")
    assert estimado
    # Sale del campo Longitud, no de la geometría (90 y 40 m).
    assert costos.tolist() == [100_000.0, 50_000.0]


# ──────────────────────────────── riesgo a futuro ────────────────────────────

def test_probabilidad_de_falla_todavia_no_esta():
    """El gancho está declarado pero no implementado, y tiene que fallar claro."""
    with pytest.raises(NotImplementedError):
        indices.calcular_probabilidad_falla(None)


def test_riesgo_es_el_producto():
    assert indices.riesgo([6.0, 3.0], [0.5, 1.0]).tolist() == [3.0, 3.0]
