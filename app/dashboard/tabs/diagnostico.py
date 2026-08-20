"""
Tab 3 — Diagnóstico: ¿el índice está bien construido?

Se mira en dos niveles a propósito:

  * las 10 columnas CF_* individuales, que es donde vive el problema real de
    construcción (ahí se ve que Antigüedad y Material son casi la misma variable
    y que Obstrucciones no varía);
  * los 5 grupos, que es el nivel al que se pondera y se discute.

Un PCA sobre los grupos y otro sobre las columnas contestan preguntas distintas:
el primero dice cuántos sliders son de verdad independientes, el segundo dice
cuánta información hay realmente en los datos de origen.

Las conclusiones se escriben solas (analisis.diagnostico.conclusiones): el punto
del tab es que el usuario no tenga que deducirlas de un heatmap.
"""
import numpy as np
from bokeh.layouts import column, gridplot, row
from bokeh.models import (
    BasicTicker,
    ColorBar,
    ColumnDataSource,
    Div,
    FactorRange,
    HoverTool,
    LinearColorMapper,
    RadioButtonGroup,
)
from bokeh.palettes import RdBu11
from bokeh.plotting import figure

from cf_pf_core.analisis import diagnostico as dg
from cf_pf_core.analisis import indices

from .. import estado
from ..componentes import colores, pesos

NIVELES = ["Columnas CF (insumos)", "Grupos (los 5 sliders)"]
COLOR_NIVEL = {"alerta": estado.COLOR_ALERTA, "aviso": estado.COLOR_AVISO,
               "ok": estado.COLOR_OK}
ICONO_NIVEL = {"alerta": "⚠", "aviso": "•", "ok": "✓"}


def crear(tablero):
    datos = tablero.datos

    nivel = RadioButtonGroup(labels=NIVELES, active=0, sizing_mode="stretch_width")

    # ── heatmap de correlacion ───────────────────────────────────────────────
    heat_fuente = ColumnDataSource(data={"x": [], "y": [], "rho": [], "texto": []})
    heat_mapper = LinearColorMapper(palette=list(reversed(RdBu11)), low=-1, high=1)
    heat = figure(x_range=FactorRange(), y_range=FactorRange(), height=420,
                  sizing_mode="stretch_width", toolbar_location=None, tools="",
                  title="Correlación de Spearman entre criterios")
    heat.rect(x="x", y="y", width=1, height=1, source=heat_fuente,
              fill_color={"field": "rho", "transform": heat_mapper},
              line_color="#FFFFFF", line_width=1)
    heat.text(x="x", y="y", text="texto", source=heat_fuente,
              text_align="center", text_baseline="middle", text_font_size="9px",
              text_color="#222222")
    heat.add_tools(HoverTool(tooltips=[("Par", "@x / @y"), ("ρ", "@rho{0.000}")]))
    heat.xaxis.major_label_orientation = 0.9
    heat.add_layout(ColorBar(color_mapper=heat_mapper, ticker=BasicTicker(desired_num_ticks=5),
                             title="ρ"), "right")
    nota_heat = Div(sizing_mode="stretch_width")

    # ── PCA ──────────────────────────────────────────────────────────────────
    scree_fuente = ColumnDataSource(data={"comp": [], "var": [], "acum": []})
    scree = figure(x_range=FactorRange(), height=280, sizing_mode="stretch_width",
                   toolbar_location=None, tools="",
                   title="PCA — varianza explicada por componente")
    scree.vbar(x="comp", top="var", width=0.75, source=scree_fuente,
               fill_color="#7FA9C9", line_color="#666666", line_width=0.5)
    scree.line(x="comp", y="acum", source=scree_fuente, line_width=2,
               color=estado.COLOR_TITULO)
    scree.scatter(x="comp", y="acum", source=scree_fuente, size=6,
                  color=estado.COLOR_TITULO)
    scree.add_tools(HoverTool(tooltips=[("Componente", "@comp"),
                                        ("Varianza", "@var{0.0%}"),
                                        ("Acumulada", "@acum{0.0%}")]))
    scree.y_range.start = 0
    scree.yaxis.axis_label = "Proporción de varianza"
    load_div = Div(sizing_mode="stretch_width")

    # ── comparacion de operadores ────────────────────────────────────────────
    ops_fuentes = {}
    ops_figs = []
    for key, etiqueta in indices.OPERADORES.items():
        f = ColumnDataSource(data={"clase": [], "conteo": [], "color": []})
        fig = figure(x_range=FactorRange(), height=230,
                     sizing_mode="stretch_width", toolbar_location=None, tools="",
                     title=etiqueta)
        fig.vbar(x="clase", top="conteo", width=0.8, source=f, fill_color="color",
                 line_color="#666666", line_width=0.5)
        fig.add_tools(HoverTool(tooltips=[("Clase", "@clase"), ("Tramos", "@conteo")]))
        fig.y_range.start = 0
        fig.xgrid.grid_line_color = None
        fig.xaxis.major_label_orientation = 0.8
        ops_fuentes[key] = f
        ops_figs.append(fig)
    ops_div = Div(sizing_mode="stretch_width")

    # ── distribucion de cada criterio ────────────────────────────────────────
    dist_holder = column(sizing_mode="stretch_width")

    # ── conclusiones y pesos ─────────────────────────────────────────────────
    conclusiones_div = Div(sizing_mode="stretch_width")
    pesos_div = Div(sizing_mode="stretch_width")

    # ── refresco ─────────────────────────────────────────────────────────────
    # La correlacion de Spearman (1,8 s) y el PCA (0,7 s) NO dependen de los
    # pesos: las columnas CF_* son fijas y la matriz de grupos solo cambia si se
    # activa el descuento de duplicadas. Recalcularlos en cada movimiento de
    # slider agregaba 2,5 s a cada click sin que el resultado cambiara nunca.
    # Se cachean por (nivel, descuento), que es de lo unico que dependen.
    cache = {}

    def _estructura(por_columnas, descontar):
        clave = (por_columnas, descontar)
        if clave in cache:
            return cache[clave]
        if por_columnas:
            cols = list(datos.cf_cols)
            marco = datos.gdf
            etiquetas = {c: datos.etiqueta_cf(c) for c in cols}
        else:
            import pandas as pd
            X, nombres = tablero.matriz()
            marco = pd.DataFrame(X, columns=nombres)
            cols = nombres
            etiquetas = {c: c for c in cols}
        cache[clave] = (cols, etiquetas,
                        dg.correlacion_spearman(marco, cols),
                        dg.pca(marco, cols))
        return cache[clave]

    # Las distribuciones por criterio tampoco dependen de nada que se pueda mover
    # desde la interfaz, y reconstruir sus diez figuras en cada refresco era
    # crear diez objetos Bokeh nuevos por click.
    distrib = dg.distribucion_criterios(datos.gdf, datos.cf_cols)
    dist_holder.children = [_grilla_distribuciones(distrib, datos)]

    def refrescar(_t=None):
        por_columnas = nivel.active == 0
        cols, etiquetas, corr, pca = _estructura(por_columnas,
                                                 tablero.descontar_duplicadas)

        # Heatmap.
        cortos = [etiquetas[c] for c in cols]
        xs, ys, rhos, textos = [], [], [], []
        for i, a in enumerate(cols):
            for j, b in enumerate(cols):
                xs.append(cortos[i])
                ys.append(cortos[j])
                r = float(corr.iloc[i, j])
                rhos.append(r)
                textos.append(f"{r:.2f}".replace(".", ",") if i != j else "")
        heat.x_range.factors = cortos
        heat.y_range.factors = list(reversed(cortos))
        heat_fuente.data = {"x": xs, "y": ys, "rho": rhos, "texto": textos}
        nota_heat.text = _texto_heat(dg.pares_redundantes(corr), etiquetas)

        # PCA (viene del cache: no depende de los pesos).
        scree.x_range.factors = pca["componentes"]
        scree_fuente.data = {"comp": pca["componentes"],
                             "var": pca["varianza"].tolist(),
                             "acum": pca["acumulada"].tolist()}
        load_div.text = _tabla_loadings(pca["loadings"], etiquetas)

        # Operadores: siempre sobre los grupos, que es donde se agrega.
        X, nombres = tablero.matriz()
        ops = dg.comparar_operadores(X, tablero.pesos(), tablero.cortes)
        etiquetas_clase = colores.etiquetas_clases(tablero.cortes)
        for key, fig in zip(indices.OPERADORES, ops_figs):
            k = indices.clasificar(ops[key]["valores"], tablero.cortes)
            conteo = np.bincount(k[k >= 0], minlength=estado.N_CLASES)
            fig.x_range.factors = etiquetas_clase
            ops_fuentes[key].data = {
                "clase": etiquetas_clase,
                "conteo": conteo[:estado.N_CLASES].tolist(),
                "color": colores.PALETA[:estado.N_CLASES]}
            fig.title.text = (f"{indices.OPERADORES[key]} · CV "
                              f"{_num(ops[key]['cv'], 3)} · "
                              f"H {_num(ops[key]['entropia'])}")
        ops_div.text = _tabla_operadores(ops)

        # Conclusiones. Son lo unico de esta seccion que si depende de los pesos,
        # porque incorporan que operador separa mejor con la ponderacion vigente.
        pe = indices.pesos_efectivos(tablero.grupos, tablero.descontar_duplicadas)
        pp = indices.pesos_efectivos(tablero.grupos, True)
        textos = dg.conclusiones(corr, pca, ops, distrib, pe, pp)
        conclusiones_div.text = _texto_conclusiones(textos)
        pesos_div.text = pesos.tabla_pesos_efectivos(tablero.grupos,
                                                     tablero.descontar_duplicadas)

    nivel.on_change("active", lambda a, o, n: refrescar())
    tablero.on_cambio(refrescar)
    refrescar()

    encabezado = Div(
        text=f"<h3 style='margin:0;color:{estado.COLOR_TITULO}'>Diagnóstico del "
             "índice</h3><p style='color:#34495E;font-size:13px;margin:4px 0'>Si "
             "dos criterios miden lo mismo, el peso que los sliders reparten "
             "entre ellos se acumula sobre una sola señal. Si un criterio no "
             "varía, su peso es ruido. Este tab busca las dos cosas y las dice.</p>",
        sizing_mode="stretch_width")

    return column(
        encabezado,
        conclusiones_div,
        Div(text=_sep("Nivel de análisis"), sizing_mode="stretch_width"),
        nivel,
        row(column(heat, nota_heat, sizing_mode="stretch_width"),
            column(scree, load_div, sizing_mode="stretch_width"),
            sizing_mode="stretch_width"),
        Div(text=_sep("Operadores de agregación"), sizing_mode="stretch_width"),
        row(*ops_figs, sizing_mode="stretch_width"),
        ops_div,
        Div(text=_sep("Peso efectivo por columna"), sizing_mode="stretch_width"),
        pesos_div,
        Div(text=_sep("Distribución de cada criterio"), sizing_mode="stretch_width"),
        dist_holder,
        sizing_mode="stretch_width",
    )


# ─────────────────────────────── textos ──────────────────────────────────────

def _sep(titulo):
    return ("<hr style='border:none;border-top:1px solid #DDD;margin:14px 0 4px'>"
            f"<b style='font-size:14px'>{titulo}</b>")


def _num(x, dec=2):
    return f"{x:.{dec}f}".replace(".", ",")


def _texto_conclusiones(textos):
    items = "".join(
        f"<li style='margin:6px 0;color:{COLOR_NIVEL.get(niv, '#34495E')}'>"
        f"<b>{ICONO_NIVEL.get(niv, '')}</b> "
        f"<span style='color:#34495E'>{txt}</span></li>"
        for niv, txt in textos)
    return ("<div style='background:#FAFAFA;border-left:3px solid #DDD;"
            "padding:8px 12px;font-size:13px'>"
            "<b style='font-size:13px'>Conclusiones</b>"
            f"<ul style='margin:4px 0 0;padding-left:18px'>{items}</ul></div>")


def _texto_heat(pares, etiquetas):
    if not pares:
        return ("<div style='font-size:12px;color:#8A8A8A'>Ningún par supera "
                f"ρ = {_num(dg.UMBRAL_REDUNDANCIA)}.</div>")
    detalle = "; ".join(
        f"<b>{etiquetas.get(a, a)}</b> ↔ <b>{etiquetas.get(b, b)}</b> "
        f"(ρ = {_num(r)})" for a, b, r in pares)
    return (f"<div style='font-size:12px;color:{estado.COLOR_ALERTA}'>⚠ Miden lo "
            f"mismo: {detalle}. Contarlos como criterios separados le da a esa "
            "dimensión el doble del peso que figura en los sliders.</div>")


def _tabla_loadings(loadings, etiquetas):
    """Loadings de las dos primeras componentes: mas columnas no se leen."""
    comps = list(loadings.columns)[:2]
    filas = "".join(
        f"<tr><td style='padding:1px 10px 1px 0'>{etiquetas.get(i, i)}</td>" +
        "".join(f"<td style='text-align:right;color:"
                f"{estado.COLOR_ALERTA if abs(loadings.loc[i, c]) > 0.4 else '#8A8A8A'}'>"
                f"{_num(loadings.loc[i, c])}</td>" for c in comps) + "</tr>"
        for i in loadings.index)
    cabeceras = "".join(f"<th style='text-align:right'>{c}</th>" for c in comps)
    return ("<div style='font-size:12px'><b>Loadings</b> — cuánto pesa cada "
            "criterio en cada componente. En rojo, los que dominan."
            "<table style='font-size:12px;width:100%;margin-top:4px'>"
            f"<tr style='color:#34495E'><th style='text-align:left'>Criterio</th>"
            f"{cabeceras}</tr>{filas}</table></div>")


def _tabla_operadores(ops):
    filas = "".join(
        f"<tr><td style='padding:1px 10px 1px 0'>{indices.OPERADORES[k]}</td>"
        f"<td style='text-align:right;color:"
        f"{estado.COLOR_ALERTA if v['alerta'] else estado.COLOR_OK}'>"
        f"{_num(v['cv'], 3)}</td>"
        f"<td style='text-align:right'>{_num(v['entropia'])}</td>"
        f"<td style='text-align:right'>{_num(v['promedio'])}</td>"
        f"<td style='text-align:right'>{_num(v['minimo'])}–{_num(v['maximo'])}</td>"
        "</tr>"
        for k, v in ops.items())
    return ("<table style='font-size:12px;width:100%'>"
            "<tr style='color:#34495E'><th style='text-align:left'>Operador</th>"
            "<th style='text-align:right'>CV</th>"
            "<th style='text-align:right'>Entropía</th>"
            "<th style='text-align:right'>Promedio</th>"
            "<th style='text-align:right'>Rango</th></tr>"
            f"{filas}</table>"
            "<div style='font-size:12px;color:#8A8A8A;margin-top:4px'>Los tres se "
            "miden con los <b>mismos cortes</b>: sobre cuantiles propios cualquier "
            "operador daría la entropía máxima y la comparación no diría nada.</div>")


def _grilla_distribuciones(distrib, datos):
    """Un histograma chico por criterio, en grilla."""
    figs = []
    for col, d in distrib.items():
        f = ColumnDataSource(data={
            "valor": d["valores"], "conteo": d["conteos"],
            "color": colores.PALETA[:len(d["valores"])]})
        alerta = d["inerte"]
        titulo = datos.etiqueta_cf(col)
        if alerta:
            titulo = f"⚠ {titulo} ({_num(d['concentracion'] * 100, 1)} % en un valor)"
        fig = figure(x_range=FactorRange(*d["valores"]), height=190, width=300,
                     toolbar_location=None, tools="", title=titulo)
        fig.vbar(x="valor", top="conteo", width=0.8, source=f, fill_color="color",
                 line_color="#666666", line_width=0.5)
        fig.add_tools(HoverTool(tooltips=[("Valor", "@valor"), ("Tramos", "@conteo")]))
        fig.y_range.start = 0
        fig.xgrid.grid_line_color = None
        fig.title.text_color = estado.COLOR_ALERTA if alerta else "#333333"
        figs.append(fig)
    return gridplot([figs[i:i + 4] for i in range(0, len(figs), 4)],
                    toolbar_location=None, sizing_mode="stretch_width")
