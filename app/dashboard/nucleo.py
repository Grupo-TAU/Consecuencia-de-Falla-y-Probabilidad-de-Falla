"""
Estado compartido del tablero: un solo ColumnDataSource para las cuatro vistas.

Es la pieza que hace que el tablero sea un tablero y no cuatro graficos juntos.
Todas las vistas dibujan sobre la MISMA fuente, asi que:

  - seleccionar tramos en el scatter de sensibilidad los prende en el mapa;
  - seleccionar en el mapa los marca en la tabla del plan de obra;
  - y no hay que sincronizar nada a mano, porque no hay nada que sincronizar.

La condicion para que eso funcione es que la fila i sea el tramo i en todas
partes (ver data.coordenadas_para_dibujo). Cualquier vista nueva tiene que
respetar ese contrato: si necesita un subconjunto, se filtra con CDSView, nunca
armando otra fuente.

`Tablero` guarda ademas los parametros que comparten los tabs (pesos, operador,
descuento de duplicadas, modo de cortes) y avisa a quien se suscriba cuando el
indice cambia. Los tabs no se conocen entre si: se enganchan aca.
"""
import copy

import numpy as np
from bokeh.models import ColumnDataSource

from cf_pf_core.analisis import indices

from . import estado


class Tablero:
    """Datos + fuente compartida + parametros del indice."""

    def __init__(self, datos):
        self.datos = datos
        self.grupos = copy.deepcopy(datos.grupos)
        self.operador = "media_aritmetica"
        self.descontar_duplicadas = False
        self.modo_cortes = "fijos"          # 'fijos' | 'cuantiles'
        self._suscriptores = []
        self._matrices = {}                 # cache de matriz(): ver matriz()

        n = len(datos)
        valores = self._calcular()
        self.cortes = indices.cortes_fijos(estado.N_CLASES)

        datos_fuente = {
            "xs": datos.xs,
            "ys": datos.ys,
            "id": datos.ids,
            "indice": valores,
            "longitud": datos.longitud,
            # 'valor' es lo que colorea: el INDICE DE CLASE, no el numero crudo.
            # Asi el mismo renderer sirve para cortes fijos y por cuantiles sin
            # tener que cambiarle el campo, que en Bokeh no se puede hacer en vivo.
            "valor": self._clases(valores),
            # Columnas que llenan los tabs 2 y 4. Arrancan neutras para que el
            # source tenga desde el principio todas las columnas que algun glifo
            # va a pedir: agregar claves despues obliga a reemplazar .data entero
            # y eso descarta la seleccion activa.
            "pct_medio": np.zeros(n),
            "pct_std": np.zeros(n),
            "frec_top10": np.zeros(n),
            # categoria y cluster viajan como texto porque los muestra el tooltip.
            # Los COLORES, en cambio, no se mandan: 60.726 copias de uno de cuatro
            # strings hexadecimales son 0,67 MB de payload por columna, y el mismo
            # dibujo sale de un CategoricalColorMapper que manda la paleta una vez.
            "categoria": np.array(["—"] * n, dtype=object),
            "cluster": np.array(["ns"] * n, dtype=object),
            "zona": np.full(n, -1, dtype="int64"),
            # uint8 y no bool: los numpy numericos viajan como buffer binario y
            # sirven de entrada al mapper de dos colores del plan de obra.
            "en_plan": np.zeros(n, dtype="uint8"),
            "costo": np.zeros(n),
        }
        for col in datos.cf_cols:
            datos_fuente[col] = datos.gdf[col].to_numpy(dtype=float)

        self.fuente = ColumnDataSource(data=datos_fuente)

    # ── indice ───────────────────────────────────────────────────────────────

    def _calcular(self):
        X, nombres = self.matriz()
        pesos = indices.vector_pesos(self.grupos, nombres)
        return indices.agregar(X, pesos, self.operador)

    def _clases(self, valores):
        """Indice de clase + 0.5, que es lo que espera el LinearColorMapper.

        El +0.5 pone el valor en el medio del tramo de color: con low=0, high=6 y
        6 colores, la clase k va del corte k al k+1, y k+0.5 cae siempre adentro
        sin depender de como redondee el mapper en los bordes.
        """
        k = indices.clasificar(valores, self.cortes)
        return np.where(k >= 0, k + 0.5, np.nan)

    def indice(self):
        """El indice vigente, ya calculado, como array."""
        return np.asarray(self.fuente.data["indice"], dtype=float)

    def matriz(self):
        """(X, nombres) de los puntajes por grupo, memoizado.

        Solo hay dos matrices posibles —con descuento de duplicadas y sin él— y
        no dependen de los pesos. Sin memoizar se recalculaba en cada movimiento
        de slider, en cada click del mapa y en cada refresco de cada tab: son
        60.000 x 10 valores copiados y multiplicados para devolver siempre uno de
        dos resultados.
        """
        clave = bool(self.descontar_duplicadas)
        if clave not in self._matrices:
            self._matrices[clave] = self.datos.matriz(clave)
        return self._matrices[clave]

    def pesos(self):
        return indices.vector_pesos(self.grupos, self.datos.criterios)

    def recalcular(self):
        """Recalcula indice, cortes y colores, y avisa a los suscriptores.

        Se escribe en source.data[...] por columna en vez de reemplazar el dict
        entero: reemplazarlo resetea la seleccion, y perder la seleccion cada vez
        que alguien mueve un slider haria inutil el linked brushing.
        """
        valores = self._calcular()
        self.cortes = (indices.cortes_cuantiles(valores, estado.N_CLASES)
                       if self.modo_cortes == "cuantiles"
                       else indices.cortes_fijos(estado.N_CLASES))
        self.fuente.data["indice"] = valores
        self.fuente.data["valor"] = self._clases(valores)
        for fn in self._suscriptores:
            fn(self)

    # ── suscripciones ────────────────────────────────────────────────────────

    def on_cambio(self, fn):
        """Registra un callback que corre cada vez que el indice cambia."""
        self._suscriptores.append(fn)
        return fn

    # ── utilidades ───────────────────────────────────────────────────────────

    def seleccion(self):
        """Indices de las filas seleccionadas en cualquier vista."""
        return list(self.fuente.selected.indices)

    def etiqueta_operador(self):
        return indices.OPERADORES[self.operador]

    def suma_pesos(self):
        return sum(float(g.get("peso") or 0.0) for g in self.grupos.values())
