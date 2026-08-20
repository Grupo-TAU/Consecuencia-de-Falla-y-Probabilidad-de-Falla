"""
Paleta, mapper y leyenda. Una sola definicion de colores para todo el tablero.

La paleta sale de criticidad.CLASES_COLOR, que es la misma que usa el renderer
de QGIS y el visualizador HTML. No se define otra aca a proposito: si el mapa del
tablero pintara con colores distintos que la capa de QGIS, el mismo tramo se
veria de dos colores segun donde se lo mire.
"""
from bokeh.models import ColorBar, Div, FixedTicker, LinearColorMapper

from cf_pf_core.analisis import indices
from cf_pf_core.calculos import criticidad as crit

from .. import estado

PALETA = [color for _, color, _ in crit.CLASES_COLOR]


def mapper(n_clases=None):
    """Mapper sobre el INDICE DE CLASE (0..n), no sobre el valor crudo.

    Trabajar sobre la clase y no sobre el numero permite cambiar de cortes fijos
    a cuantiles sin tocar el renderer: lo unico que cambia es que clase le toca a
    cada tramo, y eso se recalcula en la columna 'valor'.
    """
    n = n_clases or estado.N_CLASES
    return LinearColorMapper(palette=PALETA[:n], low=0.0, high=float(n),
                             nan_color="#BBBBBB")


def barra(color_mapper, titulo="Consecuencia", cortes=None):
    """ColorBar con marcas en los cortes de clase.

    Las etiquetas muestran el valor real de cada corte, asi que con cortes por
    cuantiles la barra dice donde caen los percentiles y no 1-2-3-4-5-6. Sin eso,
    cambiar a cuantiles dejaria una barra que miente.
    """
    n = len(color_mapper.palette)
    b = ColorBar(color_mapper=color_mapper, title=titulo,
                 ticker=FixedTicker(ticks=list(range(n + 1))))
    if cortes is not None:
        b.major_label_overrides = etiquetas_barra(cortes)
    return b


def etiquetas_barra(cortes):
    """{posicion: etiqueta} para el ColorBar, a partir de los limites superiores."""
    bordes = [0.0] + list(cortes)
    return {str(i): _fmt(v) for i, v in enumerate(bordes)}


def _fmt(x):
    if x is None or x != x:
        return ""
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".replace(".", ",")


def etiquetas_clases(cortes):
    """['≤ 1,00', '1,00–2,00', ...] para el eje del histograma."""
    salida, previo = [], None
    for c in cortes:
        salida.append(f"≤ {_fmt(c)}" if previo is None
                      else f"{_fmt(previo)}–{_fmt(c)}")
        previo = c
    return salida


def cortes_de(valores, modo, n_clases=None):
    """Cortes segun el modo elegido en el RadioButtonGroup."""
    n = n_clases or estado.N_CLASES
    if modo == "cuantiles":
        return indices.cortes_cuantiles(valores, n)
    return indices.cortes_fijos(n)


# ─────────────────────────────── leyendas HTML ───────────────────────────────

def _chips(items):
    fila = "".join(
        f"<span style='display:inline-flex;align-items:center;margin:0 10px 4px 0;"
        f"font-size:12px'><span style='width:12px;height:12px;background:{color};"
        f"border:1px solid #999;display:inline-block;margin-right:5px'></span>"
        f"{texto}</span>"
        for texto, color in items)
    return f"<div style='line-height:1.6'>{fila}</div>"


def leyenda_categorias():
    """Leyenda de las categorias de robustez del tab de sensibilidad."""
    return Div(text=_chips([(k, v) for k, v in estado.COLOR_CATEGORIA.items()]),
               sizing_mode="stretch_width")


def leyenda_clusters(etiquetas, colores):
    return Div(text=_chips([(etiquetas[k], colores[k])
                            for k in ("HH", "LL", "HL", "LH", "ns")]),
               sizing_mode="stretch_width")
