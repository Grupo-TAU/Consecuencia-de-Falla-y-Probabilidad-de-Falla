"""
Autocorrelacion espacial: de tramos sueltos a zonas de intervencion.

Operativamente no se manda una cuadrilla a un tramo: se manda a una zona. Un
ranking de 60.000 tramos ordenados por criticidad es inejecutable si los diez
primeros estan repartidos por toda Montevideo. Lo que hace falta saber es donde
se AGRUPAN los tramos criticos.

Local Moran's I (LISA) contesta eso. Para cada tramo compara su valor con el
promedio de sus vecinos y dice si la coincidencia es mas fuerte de lo que daria
el azar (permutaciones):

    HH  critico rodeado de criticos      -> zona de intervencion prioritaria
    LL  tranquilo rodeado de tranquilos  -> zona que se puede postergar
    HL  critico aislado                  -> caso puntual, no justifica movilizar
    LH  tranquilo en zona critica        -> se arregla "de paso" si ya hay obra
    ns  no significativo                 -> sin patron espacial detectable

El Moran's I global dice si vale la pena mirar lo local: si diera cerca de 0, la
criticidad estaria repartida al azar y agrupar en zonas no tendria sentido.
"""
import numpy as np
import pandas as pd

# Vecinos por tramo. Queen (contigüidad por vertice compartido) es lo estandar en
# poligonos, pero en una red de lineas depende de que los extremos coincidan
# exactamente, y estas capas vienen de digitalizaciones distintas. KNN sobre el
# centroide es robusto a eso y en una red mallada da practicamente lo mismo.
K_VECINOS = 8
PERMUTACIONES = 999
ALFA = 0.05

# Etiqueta de cada cuadrante que devuelve esda (q va de 1 a 4).
CUADRANTES = {0: "ns", 1: "HH", 2: "LH", 3: "LL", 4: "HL"}
ETIQUETAS = {
    "HH": "Alto–Alto (zona crítica)",
    "LL": "Bajo–Bajo (zona tranquila)",
    "HL": "Alto–Bajo (crítico aislado)",
    "LH": "Bajo–Alto (rezagado en zona crítica)",
    "ns": "No significativo",
}
COLORES = {
    "HH": "#D62728", "LL": "#2CA02C", "HL": "#FF7F0E",
    "LH": "#9EC5E8", "ns": "#CCCCCC",
}


def geometrias_validas(gdf):
    """Mascara booleana de las filas con geometria usable.

    Esta capa trae 2 geometrias vacias sobre 60.728. libpysal no las tolera —
    revienta con un IndexError adentro de get_points_array que no dice nada del
    problema real— asi que se filtran explicitamente y el llamador decide que
    hacer con las filas descartadas.
    """
    geom = gdf.geometry
    return ~(geom.isna() | geom.is_empty)


def _centroides(gdf):
    """Coordenadas (n, 2) del centroide de cada geometria.

    Se calculan sobre el CRS de la capa, que tiene que ser proyectado (aca
    EPSG:32721). En grados el KNN mediria distancias que no son distancias.
    """
    c = gdf.geometry.centroid
    return np.column_stack([c.x.to_numpy(), c.y.to_numpy()])


def pesos_knn(gdf, k=K_VECINOS):
    """Matriz de vecindad KNN estandarizada por filas.

    La estandarizacion ('r') hace que el vecino promedio pese 1/k: sin eso, un
    tramo con mas vecinos tendria un lag mas grande solo por eso.
    """
    import libpysal

    w = libpysal.weights.KNN(_centroides(gdf), k=k)
    w.transform = "r"
    return w


def moran_global(valores, w, permutations=PERMUTACIONES, seed=42):
    """Moran's I global. Devuelve dict con I, p, z y una lectura en prosa.

    I va de -1 a 1. Cerca de 0 = distribucion al azar; positivo = los valores
    parecidos se agrupan. En redes de saneamiento se espera positivo (los barrios
    se construyeron por epoca, con el mismo material y el mismo diametro), y si
    NO diera positivo habria que sospechar de los datos antes que de la ciudad.
    """
    import esda

    np.random.seed(seed)
    mi = esda.Moran(np.asarray(valores, dtype=float), w, permutations=permutations)
    p = float(mi.p_sim)
    if p >= ALFA:
        lectura = ("No hay evidencia de estructura espacial: la criticidad está "
                   "repartida como lo estaría al azar. Agrupar en zonas no aporta.")
    elif mi.I > 0:
        lectura = ("Los tramos críticos se agrupan: la criticidad de un tramo "
                   "predice la de sus vecinos, así que tiene sentido intervenir "
                   "por zona en vez de tramo por tramo.")
    else:
        lectura = ("Los valores se alternan (tramos críticos rodeados de tramos "
                   "tranquilos). Agrupar en zonas no ayuda; hay que ir tramo a tramo.")
    return {"I": float(mi.I), "p": p, "z": float(mi.z_sim),
            "permutaciones": permutations, "lectura": lectura}


def lisa(valores, w, permutations=PERMUTACIONES, alfa=ALFA, seed=42):
    """Local Moran's I. Devuelve DataFrame con Is, p_sim, q y cluster.

    `cluster` ya tiene aplicado el filtro de significancia: un tramo con p >= alfa
    queda como 'ns' aunque su cuadrante diga HH. Es la diferencia entre "esta
    arriba y sus vecinos tambien" y "eso no pasa por casualidad".
    """
    import esda

    y = np.asarray(valores, dtype=float)
    l = esda.Moran_Local(y, w, permutations=permutations, seed=seed)
    signif = l.p_sim < alfa
    q = np.where(signif, l.q, 0)
    return pd.DataFrame({
        "lisa_I": l.Is,
        "lisa_p": l.p_sim,
        "cluster": [CUADRANTES[int(v)] for v in q],
    })


def resumen_clusters(res):
    """{cluster: cantidad} en el orden HH, LL, HL, LH, ns."""
    cuenta = res["cluster"].value_counts().to_dict()
    return {k: int(cuenta.get(k, 0)) for k in ("HH", "LL", "HL", "LH", "ns")}


def zonas_intervencion(gdf, clusters, valor, longitud=None, tipo="HH",
                       distancia=None):
    """Agrupa los tramos de un cluster en zonas contiguas y las resume.

    Los HH no forman una sola mancha: son varias, y cada una es una obra
    distinta. Se agrupan por contigüidad espacial (union de buffers) y cada zona
    sale con n de tramos, longitud total y criticidad media, que es lo que
    necesita el que arma el plan.

    distancia : radio de agrupamiento en unidades del CRS (metros). None = 50 m,
        que junta tramos de la misma cuadra sin unir barrios distintos.

    Devuelve (zonas_gdf, zona_por_tramo). zona_por_tramo es una Serie alineada
    con gdf: el id de zona de cada tramo, o -1 si no pertenece al cluster.
    """
    import geopandas as gpd
    from shapely.ops import unary_union

    distancia = 50.0 if distancia is None else float(distancia)
    mascara = np.asarray(clusters) == tipo
    zona_por_tramo = pd.Series(-1, index=gdf.index, dtype="int64")
    if not mascara.any():
        vacio = gpd.GeoDataFrame(
            {"zona": [], "n_tramos": [], "longitud": [], "criticidad_media": []},
            geometry=[], crs=gdf.crs)
        return vacio, zona_por_tramo

    sub = gdf.loc[mascara]
    # unary_union sobre los buffers colapsa los tramos que se tocan en manchas;
    # cada mancha es una zona. Es mas barato que armar el grafo de contigüidad y
    # da el mismo agrupamiento para lo que hace falta aca.
    manchas = unary_union(sub.geometry.buffer(distancia))
    partes = list(getattr(manchas, "geoms", [manchas]))
    zonas = gpd.GeoDataFrame(geometry=partes, crs=gdf.crs)
    zonas["zona"] = np.arange(len(zonas))

    # sjoin devuelve el indice de zona de cada tramo. Un tramo largo puede tocar
    # dos manchas; se queda con la primera para que la asignacion sea funcion.
    unido = gpd.sjoin(sub[[sub.geometry.name]], zonas, how="left",
                      predicate="intersects")
    unido = unido[~unido.index.duplicated(keep="first")]
    zona_por_tramo.loc[unido.index] = unido["zona"].fillna(-1).astype("int64")

    v = pd.Series(np.asarray(valor, dtype=float), index=gdf.index)
    largo = (pd.Series(np.asarray(longitud, dtype=float), index=gdf.index)
             if longitud is not None else gdf.geometry.length)
    df = pd.DataFrame({"zona": zona_por_tramo, "valor": v, "largo": largo})
    df = df[df["zona"] >= 0]
    agg = df.groupby("zona").agg(n_tramos=("valor", "size"),
                                 longitud=("largo", "sum"),
                                 criticidad_media=("valor", "mean"))
    zonas = zonas.merge(agg, on="zona", how="inner")
    zonas = zonas.sort_values("criticidad_media", ascending=False)
    zonas["zona"] = zonas["zona"].astype("int64")
    return zonas.reset_index(drop=True), zona_por_tramo
