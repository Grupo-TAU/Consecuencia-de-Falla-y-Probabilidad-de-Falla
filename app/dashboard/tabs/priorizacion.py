"""
Tab 4 — Priorización con restricción presupuestaria.

Dos mitades:

  4a. LISA (Local Moran's I) para pasar de tramos sueltos a zonas. Una cuadrilla
      no se manda a un tramo, se manda a una zona; un ranking cuyos diez primeros
      están desparramados por toda Montevideo es inejecutable.

  4b. Knapsack 0/1 con el presupuesto disponible. El método y su optimalidad
      están documentados en cf_pf_core.analisis.optimizacion: greedy por ratio
      con relleno + intercambios, y una cota superior EXACTA por relajación
      fraccionaria, así que el gap que se reporta es una garantía y no una
      impresión.

El LISA tarda ~15 s y no se dispara solo; se cachea por firma de capa.
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
    NumberFormatter,
    NumericInput,
    Select,
    Slider,
    HoverTool,
    TabPanel,
    Tabs,
)
from bokeh.plotting import figure
from bokeh.transform import factor_cmap, linear_cmap

from cf_pf_core.analisis import espacial as sp
from cf_pf_core.analisis import optimizacion as op

from .. import data, estado


# Colores por mapper y no por columna: mandar un hexadecimal por tramo son
# 0,67 MB de payload por capa para repetir cinco valores.
ORDEN_CLUSTER = ["HH", "LL", "HL", "LH", "ns"]
COLOR_CLUSTER = factor_cmap("cluster",
                            palette=[sp.COLORES[k] for k in ORDEN_CLUSTER],
                            factors=ORDEN_CLUSTER)
COLOR_PLAN = linear_cmap("en_plan", palette=["#DDDDDD", estado.COLOR_ALERTA],
                         low=0, high=1)


def crear(tablero):
    datos = tablero.datos
    fuente = tablero.fuente
    n = len(datos)

    guardado = {"lisa": None, "zonas": None, "zona_tramo": None, "masc": None,
                "tabla": None}

    # ── controles LISA ───────────────────────────────────────────────────────
    boton_lisa = Button(label="▶ Calcular clusters espaciales (LISA)",
                        button_type="primary", sizing_mode="stretch_width")
    prog_lisa = Div(sizing_mode="stretch_width")
    moran_div = Div(sizing_mode="stretch_width")

    # ── controles presupuesto ────────────────────────────────────────────────
    costo_m = NumericInput(value=estado.COSTO_POR_METRO_DEFAULT, low=1,
                           high=10_000_000, mode="float",
                           title="Costo por metro ($)",
                           sizing_mode="stretch_width")
    columnas_costo = [c for c in datos.gdf.columns
                      if "costo" in str(c).lower() or "precio" in str(c).lower()]
    col_costo = Select(title="Columna de costo",
                       value="(estimar por longitud)",
                       options=["(estimar por longitud)"] + columnas_costo,
                       sizing_mode="stretch_width")
    presupuesto = Slider(start=0, end=100, step=1, value=5,
                         title="Presupuesto (% del costo de toda la red)",
                         sizing_mode="stretch_width")
    presupuesto.end = int(estado.FRACCION_PRESUPUESTO_MAX * 100)
    ponderar = Select(title="Qué se maximiza", value="longitud",
                      options=[("longitud", "Criticidad × longitud"),
                               ("simple", "Criticidad a secas")],
                      sizing_mode="stretch_width")
    boton_opt = Button(label="▶ Resolver plan de obra", button_type="success",
                       sizing_mode="stretch_width")
    prog_opt = Div(sizing_mode="stretch_width")
    nota_costo = Div(sizing_mode="stretch_width")
    metodo_div = Div(sizing_mode="stretch_width")

    # ── mapas ────────────────────────────────────────────────────────────────
    fig_lisa = _mapa("Clusters espaciales (LISA)", COLOR_CLUSTER, fuente, [
        ("Tramo", "@id"), ("Cluster", "@cluster"), ("Índice", "@indice{0.00}"),
        ("Zona", "@zona")])
    fig_plan = _mapa("Plan de obra seleccionado", COLOR_PLAN, fuente, [
        ("Tramo", "@id"), ("Índice", "@indice{0.00}"),
        ("Longitud", "@longitud{0,0} m"), ("Costo", "@costo{$0,0}"),
        ("Zona", "@zona")])

    # ── tabla comparativa de estrategias ─────────────────────────────────────
    comp_fuente = ColumnDataSource(data={
        "estrategia": [], "tramos": [], "longitud": [], "beneficio": [],
        "costo": [], "uso": [], "gap": []})
    comp_tabla = DataTable(
        source=comp_fuente, height=140, sizing_mode="stretch_width",
        index_position=None,
        columns=[
            TC("estrategia", "Estrategia"),
            TC("tramos", "Tramos", "0,0"),
            TC("longitud", "Longitud (km)", "0,0.0"),
            TC("beneficio", "Criticidad mitigada", "0,0"),
            TC("costo", "Costo ($ M)", "0,0.0"),
            TC("uso", "Uso del presupuesto", "0.0%"),
            TC("gap", "Gap vs. cota", "0.000%"),
        ])

    # ── tabla del plan ───────────────────────────────────────────────────────
    plan_fuente = ColumnDataSource(data={
        "id": [], "longitud": [], "indice": [], "costo": [], "cluster": [],
        "zona": []})
    plan_tabla = DataTable(
        source=plan_fuente, height=300, sizing_mode="stretch_width",
        index_position=None, sortable=True,
        columns=[
            TC("id", "Tramo"), TC("longitud", "Longitud (m)", "0,0"),
            TC("indice", "Criticidad", "0.00"), TC("costo", "Costo estimado", "$0,0"),
            TC("cluster", "Cluster"), TC("zona", "Zona"),
        ])
    exportar = Button(label="⬇ Exportar plan de obra (CSV)",
                      sizing_mode="stretch_width")
    exportar.js_on_click(CustomJS(args={"source": plan_fuente}, code="""
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
        const blob = new Blob(['\\ufeff' + filas.join('\\n')],
                              {type: 'text/csv;charset=utf-8;'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'plan_de_obra.csv';
        a.click();
        URL.revokeObjectURL(a.href);
    """))

    # ── tabla de zonas ───────────────────────────────────────────────────────
    zonas_fuente = ColumnDataSource(data={
        "zona": [], "n_tramos": [], "longitud": [], "criticidad_media": []})
    zonas_tabla = DataTable(
        source=zonas_fuente, height=260, sizing_mode="stretch_width",
        index_position=None, sortable=True,
        columns=[
            TC("zona", "Zona"), TC("n_tramos", "Tramos", "0,0"),
            TC("longitud", "Longitud (m)", "0,0"),
            TC("criticidad_media", "Criticidad media", "0.00"),
        ])

    # ── costos ───────────────────────────────────────────────────────────────
    def _costos():
        col = None if col_costo.value.startswith("(") else col_costo.value
        costos, estimado = op.costo_estimado(
            datos.gdf, col_costo=col, costo_por_metro=float(costo_m.value or 1),
            col_longitud=datos.col_longitud)
        return costos, estimado

    def _refrescar_nota_costo():
        costos, estimado = _costos()
        total = float(np.nansum(costos))
        fuente.data["costo"] = costos
        origen = (f"columna <b>{col_costo.value}</b>"
                  if not estimado else
                  f"longitud × <b>${_miles(float(costo_m.value or 0))}/m</b>")
        largo = ("del campo <b>Longitud</b> relevado"
                 if datos.col_longitud else
                 "<b style='color:#D62728'>de la geometría</b> (no se encontró el "
                 "campo Longitud relevado; difiere del dato de planos)")
        aviso = ("<br><span style='color:#D62728'>⚠ Estimación paramétrica, no un "
                 "presupuesto: es lineal en la longitud e ignora profundidad, "
                 "material, rotura de pavimento y desvío de tránsito, que en la "
                 "práctica dominan el costo.</span>" if estimado else "")
        nota_costo.text = (
            f"<div style='font-size:12px;color:#8A8A8A;padding:4px 0'>"
            f"Costo por {origen}, con la longitud tomada {largo}.<br>"
            f"Costo de intervenir <b>toda la red</b>: "
            f"<b>${_miles(total)}</b> ({_num(datos.longitud.sum() / 1000, 1)} km)."
            f"{aviso}</div>")
        return costos, total

    # ── LISA ─────────────────────────────────────────────────────────────────
    def _pintar_lisa(li, zonas, zona_tramo, moran):
        guardado.update({"lisa": li, "zonas": zonas, "zona_tramo": zona_tramo})
        fuente.data["cluster"] = li["cluster"].to_numpy()
        fuente.data["zona"] = zona_tramo.to_numpy()

        zonas_fuente.data = {
            "zona": zonas["zona"].tolist(),
            "n_tramos": zonas["n_tramos"].tolist(),
            "longitud": zonas["longitud"].tolist(),
            "criticidad_media": zonas["criticidad_media"].tolist(),
        }
        moran_div.text = _texto_moran(moran, sp.resumen_clusters(li), zonas, n)

    def _correr_lisa(desde_cache=True):
        firma = data.firma(datos.ruta, datos.capa,
                           f"lisa|{sp.K_VECINOS}|{sp.PERMUTACIONES}|"
                           f"{tablero.operador}|{tablero.descontar_duplicadas}")
        if desde_cache:
            cach = data.leer_cache("lisa", firma)
            if cach is not None and len(cach) == n:
                li = cach[["lisa_I", "lisa_p", "cluster"]]
                zona_tramo = pd.Series(cach["zona"].to_numpy(), index=datos.gdf.index)
                zonas = _zonas_desde(datos, li["cluster"].to_numpy(), zona_tramo,
                                     tablero.indice())
                moran = {"I": float(cach.attrs.get("I", np.nan)),
                         "p": float(cach.attrs.get("p", np.nan)),
                         "z": float(cach.attrs.get("z", np.nan)),
                         "permutaciones": sp.PERMUTACIONES,
                         "lectura": cach.attrs.get("lectura", "")}
                prog_lisa.text = _prog("Resultado leído del caché.", 1.0)
                _pintar_lisa(li, zonas, zona_tramo, moran)
                return

        valores = tablero.indice()
        w = sp.pesos_knn(datos.gdf)
        moran = sp.moran_global(valores, w)
        li = sp.lisa(valores, w)
        zonas, zona_tramo = sp.zonas_intervencion(
            datos.gdf, li["cluster"].to_numpy(), valores, datos.longitud)

        guardar = li.copy()
        guardar["zona"] = zona_tramo.to_numpy()
        guardar.attrs.update({k: moran[k] for k in ("I", "p", "z", "lectura")})
        data.escribir_cache(guardar, "lisa", firma)
        prog_lisa.text = _prog(
            f"Listo: {sp.PERMUTACIONES} permutaciones, {len(zonas)} zonas HH.", 1.0)
        _pintar_lisa(li, zonas, zona_tramo, moran)

    def _click_lisa():
        boton_lisa.disabled = True
        prog_lisa.text = _prog(
            f"Calculando vecindad y {sp.PERMUTACIONES} permutaciones sobre "
            f"{_miles(n)} tramos…", 0.4)

        def _luego():
            try:
                _correr_lisa(desde_cache=False)
            finally:
                boton_lisa.disabled = False

        curdoc().add_next_tick_callback(_luego)

    # ── optimizacion ─────────────────────────────────────────────────────────
    def _correr_opt():
        costos, total_red = _refrescar_nota_costo()
        pres = total_red * presupuesto.value / 100.0
        crit = tablero.indice()
        ben = op.beneficio_de(crit, datos.longitud,
                              ponderar_por_longitud=ponderar.value == "longitud")
        zona = (guardado["zona_tramo"].to_numpy()
                if guardado["zona_tramo"] is not None else None)

        tabla, masc = op.comparar(ben, costos, pres, zona, datos.longitud,
                                  criticidad=crit)
        guardado.update({"masc": masc, "tabla": tabla})

        comp_fuente.data = {
            "estrategia": tabla["estrategia"].tolist(),
            "tramos": tabla["tramos"].tolist(),
            "longitud": (tabla["longitud"] / 1000).tolist(),
            "beneficio": tabla["beneficio"].tolist(),
            "costo": (tabla["costo"] / 1e6).tolist(),
            "uso": tabla["uso_presupuesto"].tolist(),
            "gap": tabla["gap"].tolist(),
        }
        metodo_div.text = _texto_metodo(tabla, pres, zona is not None)
        _mostrar_plan(tabla.iloc[0]["key"])

    def _mostrar_plan(key):
        masc = (guardado["masc"] or {}).get(key)
        if masc is None:
            return
        fuente.data["en_plan"] = masc.astype("uint8")
        idx = np.flatnonzero(masc)
        orden = idx[np.argsort(-tablero.indice()[idx])]
        plan_fuente.data = {
            "id": np.asarray(fuente.data["id"])[orden],
            "longitud": datos.longitud[orden],
            "indice": tablero.indice()[orden],
            "costo": np.asarray(fuente.data["costo"])[orden],
            "cluster": np.asarray(fuente.data["cluster"])[orden],
            "zona": np.asarray(fuente.data["zona"])[orden],
        }

    def _click_opt():
        if guardado["zona_tramo"] is None:
            prog_opt.text = _prog(
                "Calculando sin clusters: la estrategia por zona necesita LISA.", 0.4)
        else:
            prog_opt.text = _prog("Resolviendo…", 0.4)
        boton_opt.disabled = True

        def _luego():
            try:
                _correr_opt()
                prog_opt.text = _prog("Plan resuelto.", 1.0)
            finally:
                boton_opt.disabled = False

        curdoc().add_next_tick_callback(_luego)

    boton_lisa.on_click(_click_lisa)
    boton_opt.on_click(_click_opt)
    for w in (costo_m, col_costo):
        w.on_change("value", lambda a, o, nv: _refrescar_nota_costo())

    def _elegir_estrategia(attr, old, new):
        if not new:
            return
        fila = comp_fuente.data["estrategia"][new[0]]
        key = next((k for k, v in op.ESTRATEGIAS.items() if v == fila), None)
        if key:
            _mostrar_plan(key)

    comp_fuente.selected.on_change("indices", _elegir_estrategia)

    _refrescar_nota_costo()
    _correr_lisa(desde_cache=True)
    if guardado["lisa"] is None:
        prog_lisa.text = _prog("Todavía sin calcular: apretá el botón.", 0.0)
        moran_div.text = ""

    # ── layout ───────────────────────────────────────────────────────────────
    encabezado = Div(
        text=f"<h3 style='margin:0;color:{estado.COLOR_TITULO}'>Priorización con "
             "presupuesto</h3><p style='color:#34495E;font-size:13px;margin:4px 0'>"
             "Primero se buscan las <b>zonas</b> donde los tramos críticos se "
             "agrupan (LISA); después se arma el plan de obra que más criticidad "
             "mitiga sin pasarse del presupuesto.</p>",
        sizing_mode="stretch_width")

    panel = column(
        encabezado,
        Div(text=_sep("4a · Clusters espaciales"), sizing_mode="stretch_width"),
        boton_lisa, prog_lisa, moran_div,
        sp_leyenda(),
        Div(text=_sep("4b · Presupuesto"), sizing_mode="stretch_width"),
        col_costo, costo_m, nota_costo, presupuesto, ponderar,
        boton_opt, prog_opt,
        width=380, sizing_mode="stretch_height")

    # Los dos mapas van en sub-pestañas y no lado a lado. Cada uno dibuja los
    # 60.726 tramos: mostrarlos juntos son 121.452 glifos peleando por el mismo
    # cuadro, y es el tab que peor se movia. En sub-pestañas solo uno esta
    # visible a la vez —un plot oculto no repinta— y ademas cada mapa entra con
    # el ancho completo, que es como se miran de verdad.
    mapas = Tabs(tabs=[
        TabPanel(child=fig_lisa, title="Clusters (LISA)"),
        TabPanel(child=fig_plan, title="Plan de obra"),
    ], sizing_mode="stretch_both")

    derecha = column(
        mapas,
        Div(text=_sep("Comparación de estrategias"), sizing_mode="stretch_width"),
        comp_tabla, metodo_div,
        Div(text=_sep("Zonas de intervención (HH)"), sizing_mode="stretch_width"),
        zonas_tabla,
        Div(text=_sep("Plan de obra"), sizing_mode="stretch_width"),
        exportar, plan_tabla,
        sizing_mode="stretch_both")
    return row(panel, derecha, sizing_mode="stretch_both")


# ─────────────────────────────── helpers ─────────────────────────────────────

def TC(field, title, fmt=None):
    from bokeh.models import TableColumn
    if fmt:
        return TableColumn(field=field, title=title,
                           formatter=NumberFormatter(format=fmt))
    return TableColumn(field=field, title=title)


def sp_leyenda():
    from ..componentes import colores
    return colores.leyenda_clusters(sp.ETIQUETAS, sp.COLORES)


def _mapa(titulo, campo_color, fuente, tooltips):
    fig = figure(x_axis_type="mercator", y_axis_type="mercator",
                 sizing_mode="stretch_both", height=420,
                 tools="pan,wheel_zoom,box_zoom,box_select,tap,reset,save",
                 active_scroll="wheel_zoom", title=titulo,
                 output_backend="webgl" if estado.WEBGL else "canvas")
    fig.add_tile(estado.TILE)
    fig.multi_line(xs="xs", ys="ys", source=fuente, line_color=campo_color,
                   line_width=estado.ANCHO_LINEA, line_alpha=0.9,
                   selection_line_color="#0B84A5", selection_line_width=6,
                   nonselection_line_alpha=0.25)
    fig.add_tools(HoverTool(tooltips=tooltips, mode="mouse"))
    return fig


def _zonas_desde(datos, clusters, zona_tramo, valores):
    """Rearma la tabla de zonas a partir de la asignacion cacheada.

    Evita repetir el sjoin, que es la parte cara de zonas_intervencion (20 s).
    """
    df = pd.DataFrame({"zona": zona_tramo.to_numpy(), "valor": valores,
                       "largo": datos.longitud})
    df = df[df["zona"] >= 0]
    agg = df.groupby("zona").agg(n_tramos=("valor", "size"),
                                 longitud=("largo", "sum"),
                                 criticidad_media=("valor", "mean"))
    return (agg.reset_index()
            .sort_values("criticidad_media", ascending=False)
            .reset_index(drop=True))


def _sep(titulo):
    return ("<hr style='border:none;border-top:1px solid #DDD;margin:12px 0 4px'>"
            f"<b style='font-size:13px'>{titulo}</b>")


def _num(x, dec=2):
    return f"{x:.{dec}f}".replace(".", ",")


def _miles(x):
    return f"{int(round(x)):,}".replace(",", ".")


def _prog(texto, fraccion):
    ancho = int(max(0.0, min(1.0, fraccion)) * 100)
    return (f"<div style='font-size:12px;color:#34495E;padding:4px 0'>{texto}</div>"
            "<div style='height:6px;background:#EEE;border-radius:3px'>"
            f"<div style='height:6px;width:{ancho}%;background:{estado.COLOR_OK};"
            "border-radius:3px'></div></div>")


def _texto_moran(moran, cuenta, zonas, n):
    signif = moran["p"] < sp.ALFA
    color = estado.COLOR_OK if signif else estado.COLOR_ALERTA
    # &lt; y no "<": el Div renderiza HTML, y un "<" suelto abre una etiqueta que
    # se traga el resto de la linea. Con 999 permutaciones el p-valor no puede
    # bajar de 1/1000, asi que ahi el numero exacto es un piso, no una medicion.
    p_txt = ("&lt; 0,001" if moran["p"] <= 1 / (moran["permutaciones"] + 1)
             else _num(moran["p"], 3))
    filas = "".join(
        f"<tr><td style='color:{sp.COLORES[k]};padding:1px 8px 1px 0'><b>{k}</b>"
        f"</td><td style='color:#34495E'>{sp.ETIQUETAS[k]}</td>"
        f"<td style='text-align:right;font-weight:600'>{_miles(cuenta[k])}</td>"
        f"<td style='text-align:right;color:#8A8A8A'>"
        f"{_num(cuenta[k] / n * 100, 1)} %</td></tr>"
        for k in ("HH", "LL", "HL", "LH", "ns"))
    largo_hh = zonas["longitud"].sum() if len(zonas) else 0.0
    return (
        f"<div style='font-size:13px;padding:4px 0'>"
        f"<b>Moran's I global: <span style='color:{color}'>{_num(moran['I'], 3)}"
        f"</span></b> (p {p_txt}, z {_num(moran['z'], 1)}, "
        f"{moran['permutaciones']} permutaciones)"
        f"<div style='font-size:12px;color:#8A8A8A;margin:4px 0'>"
        f"{moran['lectura']}</div>"
        f"<table style='font-size:12px;width:100%'>{filas}</table>"
        f"<div style='font-size:12px;color:#34495E;margin-top:6px'>"
        f"Los HH se agrupan en <b>{len(zonas)} zonas</b> de intervención, "
        f"<b>{_num(largo_hh / 1000, 1)} km</b> en total.</div></div>")


def _texto_metodo(tabla, presupuesto, con_zonas):
    cota = tabla.attrs.get("cota", 0.0)
    mejor = tabla.iloc[0]
    partes = [
        "<b>Método:</b> greedy por ratio beneficio/costo con relleno, más una "
        "pasada de intercambios 1-1. La columna <b>gap</b> compara contra la "
        "relajación fraccionaria del knapsack, que es una cota superior "
        "<b>exacta</b> del óptimo: el gap reportado es una garantía, y el error "
        f"real es todavía menor. La mejor estrategia queda a {_num(mejor['gap'] * 100, 3)} % "
        "de esa cota.",
    ]
    if tabla.attrs.get("greedies_equivalentes"):
        partes.append(
            "<span style='color:#D62728'>⚠ Con costo estimado por longitud, el "
            "ratio criticidad/costo es proporcional a la criticidad, así que las "
            "dos estrategias greedy ordenan igual y compararlas no dice nada. La "
            "comparación recién tiene contenido con costos reales, donde un tramo "
            "profundo bajo pavimento cuesta mucho más por metro que uno somero."
            "</span>")
    if con_zonas:
        partes.append(
            "La estrategia <b>por zona</b> puntúa peor a propósito: arrastra "
            "tramos flojos que están en el medio de una zona crítica. Lo que el "
            "modelo no ve es la movilización — mandar la cuadrilla a 40 tramos "
            "contiguos cuesta menos por tramo que a 40 desparramados —, así que "
            "su desventaja en la tabla está sobrestimada.")
    else:
        partes.append("Calculá el LISA para habilitar la estrategia por zona.")
    return ("<div style='font-size:12px;color:#8A8A8A;padding:6px 0'>" +
            "<br><br>".join(partes) + "</div>")
