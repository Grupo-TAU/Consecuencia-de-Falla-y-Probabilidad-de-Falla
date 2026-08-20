"""
Carga de la capa y armado del ColumnDataSource compartido.

Dos decisiones estructurales viven aca:

1. UNA FILA POR TRAMO. El visualizador HTML existente parte cada MultiLineString
   en una fila por parte y lleva un flag `primero` para no contar de mas en los
   estadisticos. Eso rompe el linked brushing: el indice de una fila del scatter
   no seria el mismo que el de la linea del mapa. Aca las partes se unen en un
   solo glifo con un NaN de separacion —Bokeh corta el trazo en el NaN— asi que
   la fila i del source es el tramo i en todas las vistas y una seleccion se
   propaga sola.

2. LA CONFIG DE GRUPOS SE DEDUCE DE LA CAPA, no se asume. GRUPOS_DEFAULT lista
   parametros que esta capa no tiene (CF_Acceso_Mantenimiento), y el denominador
   del promedio de un grupo depende de cuantos parametros participen de verdad.
   `detectar_grupos` restringe cada grupo a sus columnas presentes, y
   `verificar_reproduccion` compara el resultado contra la columna `criticidad`
   ya guardada: si no reproduce, el tablero lo dice en vez de mostrar numeros que
   no son los que se entregaron.
"""
import hashlib
import os

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely import get_coordinates, get_parts

from cf_pf_core.analisis import espacial, indices
from cf_pf_core.calculos import criticidad as crit
from cf_pf_core.visualizador import ETIQUETAS_CF

from . import estado


# ──────────────────────────────── columnas ───────────────────────────────────

def _col_real(nombre, columnas):
    """Nombre real de una columna sin distinguir mayusculas. None si no esta.

    Las capas vienen de distintas intendencias: 'elemred', 'ELEMRED' y 'Elemred'
    son la misma columna. El resto del core ya es tolerante a esto.
    """
    if nombre is None:
        return None
    if nombre in columnas:
        return nombre
    return {str(c).lower(): c for c in columnas}.get(str(nombre).lower())


def clave_de(columnas):
    """Columna identificadora del tramo."""
    for c in ("ELEMRED", "ID", "id", "gid"):
        real = _col_real(c, columnas)
        if real:
            return real
    return None


def campo_criticidad(columnas):
    """Como se llama la criticidad en esta capa ('criticidad' o 'CF')."""
    for c in ("criticidad", "CF"):
        real = _col_real(c, columnas)
        if real:
            return real
    return None


def detectar_grupos(columnas, grupos_base=None):
    """Los grupos de criticidad restringidos a las columnas que la capa trae.

    Devuelve (grupos, faltantes). Un grupo que se queda sin ninguna columna se
    descarta entero: mantenerlo con peso pero sin parametros haria que los pesos
    dejen de sumar 1 y la criticidad se saldria de la escala 1-6 sin avisar.
    """
    grupos_base = grupos_base if grupos_base is not None else crit.GRUPOS_DEFAULT
    grupos, faltantes = {}, []
    for nombre, g in grupos_base.items():
        presentes = []
        for p in g["params"]:
            real = _col_real(p, columnas)
            if real:
                presentes.append(real)
            else:
                faltantes.append(p)
        if presentes:
            grupos[nombre] = {"peso": float(g["peso"]), "params": presentes}
    return grupos, faltantes


def renormalizar(grupos):
    """Escala los pesos para que sumen 1, conservando las proporciones.

    Hace falta cuando se cae un grupo entero por falta de columnas: sin esto los
    pesos sumarian menos de 1 y toda la criticidad quedaria comprimida hacia
    abajo, que es un error dificil de ver mirando el mapa.
    """
    total = sum(float(g.get("peso") or 0.0) for g in grupos.values())
    if total <= 0 or abs(total - 1.0) < 1e-9:
        return grupos
    return {n: {**g, "peso": float(g["peso"]) / total} for n, g in grupos.items()}


# ──────────────────────────────── geometria ──────────────────────────────────

def coordenadas_para_dibujo(gdf, tolerancia=None, crs=None):
    """(xs, ys): una lista de coordenadas por tramo, con NaN entre partes.

    Bokeh interrumpe el trazo al encontrar un NaN, asi que un MultiLineString
    entra como un solo glifo y no como varios. Es lo que permite que la fila del
    source y el tramo sean la misma cosa.

    La simplificacion es SOLO para dibujar. La geometria original queda intacta
    en el GeoDataFrame porque es la que usan los centroides del LISA y las
    longitudes. En esta capa la simplificacion recorta apenas un 8 % de los
    vertices (los tramos promedian 2,25 puntos: ya son rectas), asi que no es de
    donde sale la fluidez — eso lo da el backend WebGL.
    """
    crs = crs if crs is not None else estado.CRS_MAPA
    geo = gdf.to_crs(crs).geometry
    if tolerancia:
        geo = geo.simplify(tolerancia)
    valores = geo.values

    # Redondeo a DECIMALES_COORD: las coordenadas son listas de largo variable,
    # asi que Bokeh no las puede mandar como buffer binario y viajan al navegador
    # como JSON. Un float sin redondear ocupa 17 caracteres
    # ("-6256909.79054747") donde con dos decimales ocupa 11, y son 250.000
    # numeros. Dos decimales en Web Mercator es precision sub-centimetrica.
    coords = np.round(shapely.get_coordinates(valores), estado.DECIMALES_COORD)
    cuentas = shapely.get_num_coordinates(valores)
    cortes = np.cumsum(cuentas)[:-1]
    # np.split de una sola vez en vez de un get_coordinates por geometria: son
    # 60.000 llamadas a shapely que tardan 2,2 s contra 0,7 s asi. La diferencia
    # se paga en cada arranque en frio del servidor.
    xs = [a.tolist() for a in np.split(coords[:, 0], cortes)]
    ys = [a.tolist() for a in np.split(coords[:, 1], cortes)]

    # Las multiparte necesitan un NaN entre partes para que Bokeh corte el trazo,
    # y el camino rapido las concatenaria de corrido dibujando un salto falso.
    # Se rehacen una por una: en esta capa no hay ninguna, y donde las haya son
    # pocas.
    multi = np.flatnonzero(shapely.get_num_geometries(valores) > 1)
    for i in multi:
        px, py = [], []
        for j, parte in enumerate(get_parts(valores[i])):
            c = np.round(get_coordinates(parte), estado.DECIMALES_COORD)
            if j:
                px.append(np.nan)
                py.append(np.nan)
            px.extend(c[:, 0].tolist())
            py.extend(c[:, 1].tolist())
        xs[i], ys[i] = px, py
    return xs, ys


def longitudes(gdf, col=None):
    """Longitud de cada tramo, del campo si existe y de la geometria si no.

    El campo Longitud es un dato RELEVADO y es el que hay que usar: no coincide
    con la longitud de la geometria. En esta capa difieren en mas de un metro en
    26.362 tramos, con casos de 3 km — recalcular desde la geometria no es una
    aproximacion, es otro numero. Y como el costo se estima por metro, arrastrar
    esa diferencia al presupuesto la convierte en plata.

    Devuelve (longitudes, nombre_columna). nombre_columna None avisa que se cayo
    a la geometria, para que la interfaz lo pueda decir.
    """
    real = _col_real(col or "Longitud", gdf.columns)
    if real:
        v = gdf[real].to_numpy(dtype=float)
        if np.isfinite(v).any():
            geom = gdf.geometry.length.to_numpy(dtype=float)
            return np.where(np.isfinite(v) & (v > 0), v, geom), real
    return gdf.geometry.length.to_numpy(dtype=float), None


# ──────────────────────────────── cache ──────────────────────────────────────

def firma(ruta, capa, extra=""):
    """Hash corto que identifica capa + version en disco + parametros.

    Incluye el mtime a proposito: si alguien recalcula el flujo y reescribe el
    .gpkg, el cache viejo deja de matchear solo y no hay que acordarse de
    borrarlo. Un cache silenciosamente desactualizado seria peor que no tenerlo.
    """
    try:
        marca = str(os.path.getmtime(ruta))
    except OSError:
        marca = "0"
    crudo = f"{os.path.abspath(ruta)}|{capa}|{marca}|{extra}"
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:12]


def ruta_cache(nombre, firma_):
    os.makedirs(estado.CACHE, exist_ok=True)
    return os.path.join(estado.CACHE, f"{nombre}_{firma_}.parquet")


def leer_cache(nombre, firma_):
    """DataFrame cacheado, o None si no esta."""
    ruta = ruta_cache(nombre, firma_)
    if not os.path.isfile(ruta):
        return None
    try:
        return pd.read_parquet(ruta)
    except Exception:  # noqa: BLE001 — un cache ilegible no puede tumbar la app
        return None


def escribir_cache(df, nombre, firma_):
    ruta = ruta_cache(nombre, firma_)
    try:
        df.to_parquet(ruta, index=False)
    except Exception:  # noqa: BLE001
        return None
    return ruta


# ──────────────────────────────── carga ──────────────────────────────────────

class Datos:
    """Todo lo que el tablero necesita saber de la capa, cargado una sola vez.

    Es deliberadamente un objeto de datos y no un modelo con logica: los calculos
    viven en cf_pf_core.analisis y los tabs los llaman. Lo unico que hace aca es
    resolver nombres de columnas y dejar todo alineado por posicion.
    """

    def __init__(self, gdf, ruta, capa):
        self.ruta = ruta
        self.capa = capa
        self.crs_original = gdf.crs

        # Las geometrias vacias se descartan ANTES de indexar: libpysal no las
        # tolera y, mas importante, un tramo sin geometria no se puede intervenir.
        validas = espacial.geometrias_validas(gdf)
        self.descartados = int((~validas).sum())
        self.gdf = gdf.loc[validas].reset_index(drop=True)

        cols = list(self.gdf.columns)
        self.col_clave = clave_de(cols)
        self.col_crit = campo_criticidad(cols)
        self.grupos, self.faltantes = detectar_grupos(cols)
        self.grupos = renormalizar(self.grupos)
        self.criterios = list(self.grupos)
        self.cf_cols = sorted({p for g in self.grupos.values() for p in g["params"]})
        self.longitud, self.col_longitud = longitudes(self.gdf)

        # La clave viaja como numero cuando lo es (ELEMRED es un entero). Un
        # array numpy va al navegador como buffer binario; el mismo dato pasado a
        # texto son 60.726 strings en JSON, medio mega de payload para mostrar
        # exactamente lo mismo en el tooltip.
        self.ids = self._resolver_ids()

        # La criticidad guardada, para poder contrastar contra la recalculada.
        self.criticidad_guardada = (
            self.gdf[self.col_crit].to_numpy(dtype=float)
            if self.col_crit else None)

        self.xs, self.ys = coordenadas_para_dibujo(
            self.gdf, estado.TOLERANCIA_SIMPLIFY)
        self.firma = firma(ruta, capa)

    def __len__(self):
        return len(self.gdf)

    def _resolver_ids(self):
        """La clave del tramo: numerica si se puede, texto si no."""
        if not self.col_clave:
            return np.arange(len(self.gdf), dtype="int64")
        serie = self.gdf[self.col_clave]
        if serie.dtype.kind in "iu":
            return serie.to_numpy()
        if serie.dtype.kind == "f":
            # Enteros leidos como float por culpa de algun NULL (ver claves.py):
            # se recuperan como enteros si no hay decimales de verdad.
            v = serie.to_numpy(dtype=float)
            finitos = v[np.isfinite(v)]
            if finitos.size and np.all(finitos == np.floor(finitos)):
                return np.where(np.isfinite(v), v, -1).astype("int64")
        return serie.astype(str).to_numpy()

    def crudo(self, nombre, i):
        """Valor crudo de la columna `nombre` en la fila i, o None si no está.

        Los crudos NO viajan en el ColumnDataSource: sólo los usa el panel de
        detalle, que se arma en el servidor. Mandarlos al navegador era casi un
        mega de payload (crudo_material son 60.726 copias de dos strings) para un
        dato que el navegador nunca lee.
        """
        real = _col_real(nombre, self.gdf.columns)
        if real is None:
            return None
        v = self.gdf[real].iloc[i]
        return None if v is None or (isinstance(v, float) and v != v) else v

    # ── matrices ─────────────────────────────────────────────────────────────

    def matriz(self, descontar_duplicadas=False):
        """(X, nombres) de los puntajes por grupo."""
        return indices.matriz_grupos(self.gdf, self.grupos, descontar_duplicadas)

    def pesos(self, grupos=None):
        g = grupos if grupos is not None else self.grupos
        return indices.vector_pesos(g, self.criterios)

    def etiqueta_cf(self, col):
        """Nombre legible de una columna CF, reusando el diccionario del
        visualizador HTML para que las dos vistas nombren igual las cosas."""
        real = _col_real(col, ETIQUETAS_CF)
        if real:
            return ETIQUETAS_CF[real][0]
        return col.replace("CF_", "").replace("_", " ")

    # ── verificacion ─────────────────────────────────────────────────────────

    def verificar_reproduccion(self, tolerancia=0.011):
        """Que proporcion de tramos reproduce la criticidad guardada.

        Devuelve (proporcion, mensaje) o (None, mensaje) si no hay con que
        comparar. Es la unica garantia de que la config deducida es la que se uso
        para generar la capa: sin esto el tablero podria estar analizando un
        indice distinto del que se entrego, y nadie se enteraria.
        """
        if self.criticidad_guardada is None:
            return None, ("La capa no trae columna de criticidad: el índice se "
                          "calcula acá y no hay contra qué contrastarlo.")
        calc = indices.criticidad_vectorizada(self.gdf, self.grupos).to_numpy()
        prop = float((np.abs(calc - self.criticidad_guardada) <= tolerancia).mean())
        pct = f"{prop * 100:.1f}".replace(".", ",")
        if prop >= 0.99:
            msg = (f"El índice recalculado reproduce la columna guardada en el "
                   f"{pct} % de los tramos.")
        else:
            msg = (f"⚠ El índice recalculado sólo coincide con la columna guardada "
                   f"en el {pct} % de los tramos. La configuración de grupos "
                   "deducida no es la que generó esta capa: revisá pesos y "
                   "parámetros antes de usar los resultados.")
        return prop, msg


def _buscar_colectores(ruta_resultados):
    """Adivina donde esta la capa de Colectores a partir de la de resultados.

    La capa DatosConsecuenciaDeFalla solo lleva clave + geometria + resultados;
    Longitud y los valores crudos del tooltip (diametro, material, antiguedad,
    obstrucciones, arboles) viven en la capa fuente. El layout habitual la deja
    en un subdirectorio 'tramos' al lado. Si no aparece, no es un error: el
    tablero funciona igual, avisando que la longitud sale de la geometria.
    """
    carpeta = os.path.dirname(os.path.abspath(ruta_resultados))
    candidatos = [
        os.path.join(carpeta, "tramos", "colectores.gpkg"),
        os.path.join(carpeta, "colectores.gpkg"),
        os.path.join(carpeta, "tramos", "colectores_corregidos.gpkg"),
    ]
    return next((c for c in candidatos if os.path.isfile(c)), None)


# Datos ya cargados, por (ruta, capa, mtime). Ver cargar().
_CACHE_CAPA = {}


def _leer_crudos(ruta, capa=None):
    """Lee de la capa de Colectores solo lo que el tablero usa.

    Sin geometria y sin las 20 columnas que no se miran: leer el archivo entero
    tarda 5,3 s contra 2,8 s asi, y la geometria de Colectores no se usa para
    nada —el join es por clave y la que se dibuja es la de resultados—.

    Devuelve un DataFrame comun (no Geo), que es todo lo que necesita
    visualizador.adjuntar_crudos: hace merge por columnas, no operaciones
    espaciales.
    """
    import pyogrio

    from cf_pf_core.visualizador import ETIQUETAS_CF, ETIQUETAS_SUELTAS

    quiero = {"ELEMRED", "ID", "gid"}
    quiero |= {c for _, c in ETIQUETAS_CF.values() if c}
    quiero |= {c for c, _, _ in ETIQUETAS_SUELTAS}
    disponibles = list(pyogrio.read_info(ruta, layer=capa)["fields"])
    # Los nombres se resuelven sin distinguir mayusculas: la misma columna llega
    # como 'DIAMETRO' o 'diametro' segun de que intendencia venga la capa.
    buscados = {q.lower() for q in quiero}
    cols = [c for c in disponibles if str(c).lower() in buscados]
    return pyogrio.read_dataframe(ruta, layer=capa, read_geometry=False,
                                  columns=cols)


def cargar(ruta=None, capa=None, ruta_colectores=None, capa_colectores=None):
    """Lee la capa y arma el objeto Datos. Lanza FileNotFoundError si no esta.

    EL RESULTADO SE CACHEA EN MEMORIA a nivel de proceso. `bokeh serve` corre
    main.py entero por CADA sesion —o sea, cada pestaña del navegador y cada
    recarga—, y sin esto cada visita releia los 13 MB del GeoPackage y volvia a
    construir las 60.726 listas de coordenadas: seis segundos de espera para
    llegar exactamente al mismo objeto.

    Compartirlo entre sesiones es seguro porque `Datos` es de solo lectura: lo
    mutable —pesos, operador, seleccion, ColumnDataSource— vive en Tablero, que
    sigue siendo uno por sesion. La clave incluye el mtime del archivo, asi que
    si alguien recalcula el flujo y reescribe el .gpkg, la proxima sesion lo
    relee sola.

    Si encuentra la capa de Colectores le engancha las columnas crudas con
    `visualizador.adjuntar_crudos` —el mismo camino que usa el HTML autonomo, asi
    las dos vistas muestran exactamente los mismos valores— y con eso llegan
    Longitud y los datos del tooltip.
    """
    from cf_pf_core import visualizador

    ruta = ruta or estado.GPKG_DEFAULT
    capa = capa or estado.CAPA_DEFAULT
    if not os.path.isfile(ruta):
        raise FileNotFoundError(
            f"No existe el GeoPackage: {ruta}\n"
            "Indicá otro con la variable de entorno CF_GPKG.")

    clave = (os.path.abspath(ruta), capa, os.path.getmtime(ruta),
             ruta_colectores, capa_colectores)
    if clave in _CACHE_CAPA:
        return _CACHE_CAPA[clave]

    gdf = gpd.read_file(ruta, layer=capa)

    ruta_col = ruta_colectores or os.environ.get("CF_COLECTORES") or \
        _buscar_colectores(ruta)
    aviso_col = None
    if ruta_col and os.path.isfile(ruta_col):
        try:
            col_gdf = _leer_crudos(ruta_col, capa_colectores)
            antes = set(gdf.columns)
            gdf = visualizador.adjuntar_crudos(gdf, col_gdf, clave_de(gdf.columns))
            nuevas = [c for c in gdf.columns if c not in antes]
            aviso_col = (f"Datos de Colectores enganchados desde "
                         f"{os.path.basename(ruta_col)}: {', '.join(nuevas)}"
                         if nuevas else None)
        except Exception as e:  # noqa: BLE001 — sin crudos el tablero igual sirve
            aviso_col = f"No se pudo leer la capa de Colectores ({ruta_col}): {e}"
    else:
        aviso_col = ("No se encontró la capa de Colectores: la longitud sale de "
                     "la geometría, que no es el dato relevado.")

    datos = Datos(gdf, ruta, capa)
    datos.ruta_colectores = ruta_col
    datos.aviso_colectores = aviso_col
    # Una sola capa en memoria: dos capas distintas en el mismo proceso serian
    # ~250 MB cada una, y el caso normal es servir siempre la misma.
    _CACHE_CAPA.clear()
    _CACHE_CAPA[clave] = datos
    return datos
