"""
Tab 1 — Mapa: la vista de siempre, con lo que le faltaba.

Cambios respecto del visualizador HTML:

  * El tooltip muestra UN tramo, no la pila de todos los que caen bajo el cursor.
  * Al hacer clic aparece el desglose de los criterios de ese tramo.
  * Los cortes de color se pueden pasar a quintiles, porque el indice real vive
    entre 1,27 y 5,15 y con cortes fijos sobran las dos clases de las puntas.
  * Se puede cambiar el operador de agregacion y ver el efecto en vivo.
  * Junto a los estadisticos van el CV y la entropia, que dicen si el indice
    separa algo o no.
"""
import numpy as np
from bokeh.layouts import column, row
from bokeh.models import (
    ColumnDataSource,
    Div,
    FactorRange,
    HoverTool,
    RadioButtonGroup,
    TapTool,
)
from bokeh.plotting import figure

from cf_pf_core.analisis import indices

from .. import estado
from ..componentes import colores, panel_detalle, pesos

MODOS_CORTE = ["Cortes fijos (1–6)", "Quintiles (20 % peor siempre en rojo)"]


def crear(tablero):
    datos = tablero.datos
    fuente = tablero.fuente

    # ── mapa ─────────────────────────────────────────────────────────────────
    mapper = colores.mapper()
    fig = figure(
        x_axis_type="mercator", y_axis_type="mercator",
        sizing_mode="stretch_both",
        tools="pan,wheel_zoom,box_zoom,box_select,tap,reset,save",
        active_scroll="wheel_zoom",
        title="Consecuencia de falla por tramo",
        output_backend="webgl" if estado.WEBGL else "canvas",
    )
    fig.add_tile(estado.TILE)
    lineas = fig.multi_line(
        xs="xs", ys="ys", source=fuente,
        line_color={"field": "valor", "transform": mapper},
        line_width=estado.ANCHO_LINEA, line_alpha=0.9,
        selection_line_color="#0B84A5", selection_line_width=6,
        nonselection_line_alpha=0.25,
    )

    # Un solo tramo en el tooltip. multi_line devuelve TODAS las lineas que caen
    # bajo el cursor y Bokeh las apila; el hover queda ilegible justo donde mas
    # se lo necesita, que es donde hay muchos colectores juntos. Con
    # HoverTool.mode='mouse' + un solo renderer se limita a la entidad mas
    # cercana. El detalle completo va por TapTool, que es explicito y no depende
    # de cuan quieto se tenga el mouse.
    tooltips = [("Tramo", "@id"), ("Longitud", "@longitud{0,0} m"),
                ("Índice", "@indice{0.00}")]
    for col in datos.cf_cols:
        tooltips.append((datos.etiqueta_cf(col), f"@{{{col}}}"))
    fig.add_tools(HoverTool(renderers=[lineas], tooltips=tooltips, mode="mouse",
                            point_policy="snap_to_data"))
    tap = fig.select_one(TapTool)
    if tap:
        tap.renderers = [lineas]

    barra = colores.barra(mapper, "Consecuencia", tablero.cortes)
    fig.add_layout(barra, "right")

    # ── histograma ───────────────────────────────────────────────────────────
    etiquetas = colores.etiquetas_clases(tablero.cortes)
    hist_fuente = ColumnDataSource(data={
        "clase": etiquetas, "conteo": [0] * estado.N_CLASES,
        "color": colores.PALETA[:estado.N_CLASES],
    })
    hist = figure(x_range=FactorRange(*etiquetas), height=200,
                  sizing_mode="stretch_width", toolbar_location=None, tools="",
                  title="Tramos por clase")
    hist.vbar(x="clase", top="conteo", width=0.8, source=hist_fuente,
              fill_color="color", line_color="#666666", line_width=0.5)
    hist.add_tools(HoverTool(tooltips=[("Clase", "@clase"), ("Tramos", "@conteo")]))
    hist.y_range.start = 0
    hist.xgrid.grid_line_color = None
    hist.xaxis.major_label_orientation = 0.8

    stats = Div(sizing_mode="stretch_width")

    # ── controles ────────────────────────────────────────────────────────────
    modo = RadioButtonGroup(labels=MODOS_CORTE, active=0,
                            sizing_mode="stretch_width")
    nota_modo = Div(
        text="<div style='font-size:12px;color:#8A8A8A;padding:2px 0 8px'>"
             "Los <b>cortes fijos</b> son comparables entre escenarios de peso: "
             "un tramo cambia de clase sólo si cambia su índice. Los "
             "<b>quintiles</b> garantizan que la clase más alta sea siempre el "
             "20 % peor, aunque el índice entero se mueva.</div>",
        sizing_mode="stretch_width")

    detalle_txt, detalle_fig, actualizar_detalle = panel_detalle.crear(tablero)
    panel_pesos, _widgets = pesos.panel(tablero)

    # ── refresco ─────────────────────────────────────────────────────────────
    def refrescar(_tablero=None):
        valores = tablero.indice()
        cortes = tablero.cortes

        etiquetas = colores.etiquetas_clases(cortes)
        k = indices.clasificar(valores, cortes)
        conteo = np.bincount(k[k >= 0], minlength=estado.N_CLASES)
        hist.x_range.factors = etiquetas
        hist_fuente.data = {"clase": etiquetas,
                            "conteo": conteo[:estado.N_CLASES].tolist(),
                            "color": colores.PALETA[:estado.N_CLASES]}
        barra.major_label_overrides = colores.etiquetas_barra(cortes)
        barra.title = f"Consecuencia · {tablero.etiqueta_operador()}"
        hist.title.text = f"Tramos por clase · {tablero.etiqueta_operador()}"
        stats.text = _texto_stats(valores, cortes)
        actualizar_detalle(tablero.seleccion())

    def _cambiar_modo(attr, old, new):
        tablero.modo_cortes = "cuantiles" if modo.active == 1 else "fijos"
        tablero.recalcular()

    modo.on_change("active", _cambiar_modo)
    fuente.selected.on_change(
        "indices", lambda attr, old, new: actualizar_detalle(list(new)))
    tablero.on_cambio(refrescar)
    refrescar()

    # ── layout ───────────────────────────────────────────────────────────────
    encabezado = Div(
        text=f"<h3 style='margin:0;color:{estado.COLOR_TITULO}'>Mapa</h3>"
             "<p style='color:#34495E;font-size:13px;margin:4px 0'>Mové los pesos "
             "y el mapa, la distribución y los estadísticos se recalculan juntos. "
             "Hacé clic en un tramo para ver por qué puntúa como puntúa.</p>",
        sizing_mode="stretch_width")

    panel = column(encabezado, panel_pesos,
                   Div(text=_sep("Escala de color"), sizing_mode="stretch_width"),
                   modo, nota_modo,
                   Div(text=_sep("Estadísticos"), sizing_mode="stretch_width"),
                   stats, hist,
                   width=360, sizing_mode="stretch_height")
    derecha = column(fig, detalle_txt, detalle_fig, sizing_mode="stretch_both")
    return row(panel, derecha, sizing_mode="stretch_both")


def _sep(titulo):
    return ("<hr style='border:none;border-top:1px solid #DDD;margin:10px 0 4px'>"
            f"<b style='font-size:13px'>{titulo}</b>")


def _texto_stats(valores, cortes):
    n, prom, med, mini, maxi = indices.estadisticos(valores)
    cv, h, alerta = indices.discrimina(valores, cortes)
    hmax = indices.entropia_maxima(estado.N_CLASES)

    def fila(k, v, color=None, ayuda=""):
        estilo = f";color:{color}" if color else ""
        titulo = f" title='{ayuda}'" if ayuda else ""
        return (f"<tr{titulo}><td style='color:#34495E;padding:1px 8px 1px 0'>{k}</td>"
                f"<td style='text-align:right;font-weight:600{estilo}'>{v}</td></tr>")

    color_cv = estado.COLOR_ALERTA if alerta else estado.COLOR_OK
    filas = (
        fila("Tramos", f"{n:,}".replace(",", ".")) +
        fila("Promedio", _num(prom)) +
        fila("Mediana", _num(med)) +
        fila("Mínimo", _num(mini)) +
        fila("Máximo", _num(maxi)) +
        fila("Coef. de variación", _num(cv, 3), color_cv,
             "std/mean. Por debajo de 0,20 el índice no separa tramos.") +
        fila("Entropía (bits)", f"{_num(h)} / {_num(hmax)}", None,
             "Qué tan repartidos quedan los tramos entre las clases. "
             "El máximo con 6 clases es 2,58.")
    )
    aviso = ""
    if alerta:
        aviso = (f"<div style='font-size:12px;color:{estado.COLOR_ALERTA};"
                 "padding:4px 0'>⚠ El índice casi no discrimina: la mayoría de "
                 "los tramos cae en la misma clase. Probá otro operador de "
                 "agregación o mirá el tab de Diagnóstico.</div>")
    return f"<table style='font-size:13px;width:100%'>{filas}</table>{aviso}"


def _num(x, dec=2):
    return f"{x:.{dec}f}".replace(".", ",")
