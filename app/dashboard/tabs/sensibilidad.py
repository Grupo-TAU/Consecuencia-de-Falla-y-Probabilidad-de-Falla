"""
Tab 2 — Sensibilidad de pesos.

Convierte los sliders en analisis: en vez de preguntar "que pasa con ESTOS
pesos", pregunta "que tramos aguantan CUALQUIER ponderacion razonable".

El Monte Carlo no se dispara solo. Son ~15 s sobre 60.000 tramos y engancharlo a
un slider haria el tablero inusable; ademas el punto del analisis es que NO
depende de donde esten los sliders, asi que recalcularlo al moverlos seria
contradictorio. El resultado se cachea en parquet por firma de capa.
"""
import numpy as np
import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import (
    Button,
    ColumnDataSource,
    CustomJS,
    DataTable,
    Div,
    FactorRange,
    HoverTool,
    NumberFormatter,
    Slider,
    TableColumn,
)
from bokeh.plotting import figure
from bokeh.transform import factor_cmap

from cf_pf_core.analisis import sensibilidad as sn

from .. import data, estado
from ..componentes import colores

# Muestra del scatter. 60.000 puntos en canvas hacen el hover inutilizable y
# tapan la estructura; la muestra es aleatoria con semilla fija, asi que la nube
# es representativa y estable entre recargas. Los tramos ROBUSTOS van todos, sin
# muestrear: son pocos y son justo los que hay que poder señalar.
MUESTRA_SCATTER = 6000

# Factores del mapper de color. Incluye el guion del estado inicial: un factor
# que no este en la lista se dibuja del color por defecto y el mapa aparecería
# todo de un color hasta que se corra el Monte Carlo.
FACTORES_CATEGORIA = ["—", *estado.COLOR_CATEGORIA]
PALETA_CATEGORIA = ["#DDDDDD", *estado.COLOR_CATEGORIA.values()]


def crear(tablero):
    datos = tablero.datos
    fuente = tablero.fuente
    n = len(datos)

    # ── controles ────────────────────────────────────────────────────────────
    n_sim = Slider(start=estado.N_SIM_MIN, end=estado.N_SIM_MAX,
                   step=estado.N_SIM_PASO, value=estado.N_SIM_DEFAULT,
                   title="Simulaciones", sizing_mode="stretch_width")
    boton = Button(label="▶ Recalcular sensibilidad", button_type="primary",
                   sizing_mode="stretch_width")
    progreso = Div(sizing_mode="stretch_width")
    resumen = Div(sizing_mode="stretch_width")

    # ── mapa por categoria ───────────────────────────────────────────────────
    fig = figure(x_axis_type="mercator", y_axis_type="mercator",
                 sizing_mode="stretch_both",
                 tools="pan,wheel_zoom,box_zoom,box_select,tap,reset,save",
                 active_scroll="wheel_zoom",
                 title="Robustez del ranking frente a la ponderación",
                 output_backend="webgl" if estado.WEBGL else "canvas")
    fig.add_tile(estado.TILE)
    # El color sale de un mapper sobre la columna de texto que el tooltip ya
    # necesita, en vez de una columna de colores paralela: la paleta viaja una
    # sola vez y no 60.726 veces.
    fig.multi_line(xs="xs", ys="ys", source=fuente,
                   line_color=factor_cmap("categoria",
                                          palette=PALETA_CATEGORIA,
                                          factors=FACTORES_CATEGORIA),
                   line_width=estado.ANCHO_LINEA, line_alpha=0.9,
                   selection_line_color="#0B84A5", selection_line_width=6,
                   nonselection_line_alpha=0.25)
    fig.add_tools(HoverTool(tooltips=[
        ("Tramo", "@id"), ("Categoría", "@categoria"),
        ("Percentil medio", "@pct_medio{0.000}"),
        ("Volatilidad", "@pct_std{0.000}"),
        ("Frecuencia en top 10 %", "@frec_top10{0.00}"),
    ], mode="mouse"))

    # ── scatter pct_medio vs pct_std ─────────────────────────────────────────
    disp_fuente = ColumnDataSource(data={
        "pct_medio": [], "pct_std": [], "frec_top10": [], "categoria": [],
        "color": [], "id": [], "fila": [],
    })
    disp = figure(height=330, sizing_mode="stretch_width",
                  tools="pan,wheel_zoom,box_zoom,box_select,tap,reset",
                  active_scroll="wheel_zoom",
                  title="Percentil medio vs. volatilidad del ranking",
                  x_axis_label="Percentil medio (1 = el más crítico)",
                  y_axis_label="Desvío del percentil")
    disp.scatter(x="pct_medio", y="pct_std", source=disp_fuente, size=4,
                 fill_color="color", line_color=None, fill_alpha=0.55,
                 selection_fill_color="#0B84A5", nonselection_fill_alpha=0.12)
    disp.add_tools(HoverTool(tooltips=[
        ("Tramo", "@id"), ("Categoría", "@categoria"),
        ("Percentil medio", "@pct_medio{0.000}"),
        ("Volatilidad", "@pct_std{0.000}"),
    ]))
    nota_disp = Div(
        text="<div style='font-size:12px;color:#8A8A8A'>Cada punto es un tramo. "
             "Abajo a la derecha, los <b>robustos</b>: siempre arriba y sin "
             "moverse. Arriba al medio, los <b>volátiles</b>: su prioridad "
             "depende de qué criterio se privilegie, y son los que hay que "
             "llevar a la mesa de decisión.</div>",
        sizing_mode="stretch_width")

    # ── impacto marginal ─────────────────────────────────────────────────────
    imp_fuente = ColumnDataSource(data={"criterio": [], "spearman": [],
                                        "top_comun": [], "color": []})
    imp = figure(y_range=FactorRange(), height=260, sizing_mode="stretch_width",
                 toolbar_location=None, tools="",
                 title="Impacto marginal: si este criterio se llevara todo el peso",
                 x_axis_label="Correlación de Spearman con el ranking actual")
    imp.hbar(y="criterio", right="spearman", height=0.6, source=imp_fuente,
             fill_color="color", line_color="#666666", line_width=0.5)
    imp.add_tools(HoverTool(tooltips=[
        ("Criterio", "@criterio"),
        ("Spearman con el ranking actual", "@spearman{0.000}"),
        ("Del top 100 sobreviven", "@top_comun de 100"),
    ]))
    nota_imp = Div(sizing_mode="stretch_width")

    # ── tabla de robustos ────────────────────────────────────────────────────
    tabla_fuente = ColumnDataSource(data={
        "id": [], "pct_medio": [], "pct_std": [], "frec_top10": [],
        "indice": [], "longitud": [], "categoria": [],
    })
    pct = NumberFormatter(format="0.000")
    tabla = DataTable(
        source=tabla_fuente, sizing_mode="stretch_width", height=300,
        index_position=None, sortable=True,
        columns=[
            TableColumn(field="id", title="Tramo"),
            TableColumn(field="indice", title="Índice",
                        formatter=NumberFormatter(format="0.00")),
            TableColumn(field="longitud", title="Longitud (m)",
                        formatter=NumberFormatter(format="0,0")),
            TableColumn(field="pct_medio", title="Percentil medio", formatter=pct),
            TableColumn(field="pct_std", title="Volatilidad", formatter=pct),
            TableColumn(field="frec_top10", title="Frec. top 10 %", formatter=pct),
            TableColumn(field="categoria", title="Categoría"),
        ])
    top_n = Slider(start=20, end=1000, step=20, value=estado.TOP_N_DEFAULT,
                   title="Filas en la tabla", sizing_mode="stretch_width")
    exportar = Button(label="⬇ Exportar CSV", sizing_mode="stretch_width")
    # La descarga se arma en el navegador: Bokeh server no tiene endpoint de
    # archivos y mandar el CSV por websocket para despues escribirlo seria dar
    # una vuelta larga para lo mismo.
    exportar.js_on_click(CustomJS(args={"source": tabla_fuente}, code="""
        const data = source.data;
        const cols = Object.keys(data);
        const filas = [cols.join(';')];
        const n = data[cols[0]] ? data[cols[0]].length : 0;
        for (let i = 0; i < n; i++) {
            filas.push(cols.map(c => {
                const v = data[c][i];
                return (typeof v === 'number') ? String(v).replace('.', ',') : v;
            }).join(';'));
        }
        const blob = new Blob(['﻿' + filas.join('\\n')],
                              {type: 'text/csv;charset=utf-8;'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'tramos_robustos.csv';
        a.click();
        URL.revokeObjectURL(a.href);
    """))

    # ── calculo ──────────────────────────────────────────────────────────────
    estado_calculo = {"res": None}

    def _pintar(res):
        """Vuelca el resultado del Monte Carlo en la fuente compartida."""
        estado_calculo["res"] = res
        cat = res["categoria"].to_numpy()
        fuente.data["pct_medio"] = res["pct_medio"].to_numpy()
        fuente.data["pct_std"] = res["pct_std"].to_numpy()
        fuente.data["frec_top10"] = res["frec_top10"].to_numpy()
        fuente.data["categoria"] = cat

        cuenta = sn.resumen_categorias(res)
        resumen.text = _texto_resumen(cuenta, n)

        # Scatter: todos los robustos + una muestra del resto.
        rng = np.random.default_rng(estado.SEED)
        robustos = np.flatnonzero(cat == "Robusto")
        resto = np.flatnonzero(cat != "Robusto")
        cupo = max(0, MUESTRA_SCATTER - len(robustos))
        if len(resto) > cupo:
            resto = rng.choice(resto, size=cupo, replace=False)
        sel = np.sort(np.concatenate([robustos, resto]))
        disp_fuente.data = {
            "pct_medio": res["pct_medio"].to_numpy()[sel],
            "pct_std": res["pct_std"].to_numpy()[sel],
            "frec_top10": res["frec_top10"].to_numpy()[sel],
            "categoria": cat[sel],
            "color": [estado.COLOR_CATEGORIA.get(c, "#DDDDDD") for c in cat[sel]],
            "id": np.asarray(fuente.data["id"])[sel],
            "fila": sel,
        }
        _refrescar_tabla()

        # Impacto marginal: se recalcula siempre, porque depende de los pesos
        # actuales (el ranking base contra el que se compara).
        X, nombres = tablero.matriz()
        im = sn.impacto_marginal(X, nombres, tablero.pesos(), estado.TOP_N_IMPACTO)
        im = im.sort_values("spearman")
        imp.y_range.factors = im["criterio"].tolist()
        imp_fuente.data = {
            "criterio": im["criterio"].tolist(),
            "spearman": im["spearman"].tolist(),
            "top_comun": im["top_comun"].tolist(),
            "color": [estado.COLOR_ALERTA if s >= 0.7 else
                      (estado.COLOR_AVISO if s >= 0.3 else "#7FA9C9")
                      for s in im["spearman"]],
        }
        nota_imp.text = _texto_impacto(im)

    def _refrescar_tabla():
        res = estado_calculo["res"]
        if res is None:
            return
        k = int(top_n.value)
        orden = res.sort_values(["frec_top10", "pct_medio"],
                                ascending=False).head(k).index.to_numpy()
        tabla_fuente.data = {
            "id": np.asarray(fuente.data["id"])[orden],
            "pct_medio": res["pct_medio"].to_numpy()[orden],
            "pct_std": res["pct_std"].to_numpy()[orden],
            "frec_top10": res["frec_top10"].to_numpy()[orden],
            "indice": tablero.indice()[orden],
            "longitud": np.asarray(fuente.data["longitud"])[orden],
            "categoria": res["categoria"].to_numpy()[orden],
        }

    def _correr(desde_cache=True):
        sims = int(n_sim.value)
        firma = data.firma(datos.ruta, datos.capa,
                           f"mc|{sims}|{estado.SEED}|{tablero.descontar_duplicadas}")
        if desde_cache:
            cacheado = data.leer_cache("sensibilidad", firma)
            if cacheado is not None and len(cacheado) == n:
                progreso.text = _prog("Resultado leído del caché.", 1.0)
                _pintar(cacheado)
                return

        X, _nombres = tablero.matriz()
        res = sn.monte_carlo(X, n_sim=sims, seed=estado.SEED)
        res = sn.clasificar_robustez(res)
        data.escribir_cache(res, "sensibilidad", firma)
        progreso.text = _prog(f"Listo: {sims} escenarios simulados.", 1.0)
        _pintar(res)

    def _click():
        # El Div se actualiza en este tick y el calculo corre en el siguiente:
        # si se hiciera todo junto, el navegador recien veria el mensaje cuando
        # el calculo ya termino y la barra de progreso no serviria de nada.
        boton.disabled = True
        progreso.text = _prog(f"Simulando {int(n_sim.value)} escenarios sobre "
                              f"{_miles(n)} tramos…", 0.35)

        def _luego():
            try:
                _correr(desde_cache=False)
            finally:
                boton.disabled = False

        curdoc().add_next_tick_callback(_luego)

    boton.on_click(_click)
    top_n.on_change("value_throttled", lambda a, o, n_: _refrescar_tabla())
    tablero.on_cambio(lambda _t: _refrescar_tabla())
    # Al arrancar se intenta el cache: si el precompute ya corrio, el tab aparece
    # lleno; si no, queda el boton.
    _correr(desde_cache=True)
    if estado_calculo["res"] is None:
        progreso.text = _prog("Todavía sin calcular: apretá «Recalcular».", 0.0)
        resumen.text = ""

    # ── layout ───────────────────────────────────────────────────────────────
    encabezado = Div(
        text=f"<h3 style='margin:0;color:{estado.COLOR_TITULO}'>Sensibilidad de "
             "pesos</h3><p style='color:#34495E;font-size:13px;margin:4px 0'>Se "
             "sortean miles de vectores de peso al azar (Dirichlet uniforme sobre "
             "el simplex) y se mira dónde queda cada tramo en cada escenario. La "
             "pregunta no es cuál es el más crítico con estos pesos, sino cuáles "
             "lo son <b>decida lo que decida</b> el que pondera.</p>",
        sizing_mode="stretch_width")

    panel = column(encabezado, n_sim, boton, progreso, resumen,
                   colores.leyenda_categorias(),
                   Div(text="<hr style='border:none;border-top:1px solid #DDD;"
                            "margin:10px 0 4px'><b style='font-size:13px'>"
                            "Top robustos</b>", sizing_mode="stretch_width"),
                   top_n, exportar,
                   width=360, sizing_mode="stretch_height")
    derecha = column(fig, row(column(disp, nota_disp, sizing_mode="stretch_width"),
                              column(imp, nota_imp, sizing_mode="stretch_width"),
                              sizing_mode="stretch_width"),
                     tabla, sizing_mode="stretch_both")
    return row(panel, derecha, sizing_mode="stretch_both")


# ─────────────────────────────── textos ──────────────────────────────────────

def _prog(texto, fraccion):
    ancho = int(max(0.0, min(1.0, fraccion)) * 100)
    return (f"<div style='font-size:12px;color:#34495E;padding:4px 0'>{texto}</div>"
            "<div style='height:6px;background:#EEE;border-radius:3px'>"
            f"<div style='height:6px;width:{ancho}%;background:{estado.COLOR_OK};"
            "border-radius:3px'></div></div>")


def _num(x, dec=2):
    """Numero con coma decimal. Se formatea el numero, nunca la frase: un
    .replace('.', ',') sobre el HTML entero rompe estilos y etiquetas."""
    return f"{x:.{dec}f}".replace(".", ",")


def _miles(x):
    return f"{int(x):,}".replace(",", ".")


def _texto_resumen(cuenta, n):
    def fila(k, v, color, ayuda):
        return (
            f"<tr title='{ayuda}'>"
            f"<td style='color:{color};padding:1px 8px 1px 0'><b>{k}</b></td>"
            f"<td style='text-align:right;font-weight:600'>{_miles(v)}</td>"
            f"<td style='text-align:right;color:#8A8A8A'>"
            f"{_num(v / n * 100, 1)} %</td></tr>")

    filas = (
        fila("Robustos", cuenta["Robusto"], estado.COLOR_CATEGORIA["Robusto"],
             "Entran al top 10 % en más del 80 % de los escenarios. "
             "Prioridad defendible frente a cualquier ponderación.") +
        fila("Volátiles", cuenta["Volátil"], estado.COLOR_CATEGORIA["Volátil"],
             "Su posición depende de qué criterio se privilegie. "
             "Son los que hay que discutir con el decisor.") +
        fila("Intermedios", cuenta["Intermedio"], "#8A8A8A",
             "Ni una cosa ni la otra.") +
        fila("Descartables", cuenta["Descartable"],
             estado.COLOR_CATEGORIA["Descartable"],
             "No entran al top en ningún escenario simulado.")
    )
    return f"<table style='font-size:13px;width:100%'>{filas}</table>"


def _texto_impacto(im):
    if im.empty:
        return ""
    fuerte = im.sort_values("spearman", ascending=False).iloc[0]
    partes = [f"<b>{fuerte['criterio']}</b> es el que más se parece al ranking "
              f"actual (ρ = {_num(fuerte['spearman'])})."]
    # El caso interesante: correlacion global alta pero poca supervivencia en la
    # punta. El promedio se parece y la lista de obra no.
    for _, f in im.iterrows():
        if f["spearman"] >= 0.7 and f["top_comun"] <= f["top_n"] * 0.3:
            partes.append(
                f"Ojo con <b>{f['criterio']}</b>: correlaciona "
                f"{_num(f['spearman'])} con el ranking global pero sólo "
                f"{int(f['top_comun'])} de los {int(f['top_n'])} primeros "
                "sobreviven. Reordena justo la punta, que es la parte que se "
                "ejecuta.")
            break
    return ("<div style='font-size:12px;color:#8A8A8A'>" + " ".join(partes) +
            "</div>")
