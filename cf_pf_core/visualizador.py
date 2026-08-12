"""
Generador de un visualizador HTML autonomo (Bokeh) de Consecuencia de Falla.

Produce un .html standalone (como el que dio la otra empresa) con:
  - Mapa de colectores sobre un fondo de tiles, coloreados por criticidad.
  - Un slider de PESO por cada grupo de criticidad.
  - Recalculo CLIENT-SIDE (CustomJS): al mover un slider se recalcula la
    criticidad de cada tramo y el mapa se recolorea, sin servidor.

Se apoya en los mismos grupos configurables que cf_pf_core.calculos.criticidad.
"""
import geopandas as gpd
from bokeh.embed import file_html
from bokeh.layouts import column, row
from bokeh.models import (
    ColorBar,
    ColumnDataSource,
    CustomJS,
    Div,
    FixedTicker,
    HoverTool,
    LinearColorMapper,
    Slider,
)
from bokeh.plotting import figure
from bokeh.resources import CDN

from cf_pf_core.calculos import criticidad as _crit


def _cf(v):
    """Igual que criticidad._cf: acota a [1,6], NULL/invalidos -> 1."""
    try:
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return 1.0
        return max(1.0, min(6.0, float(v)))
    except (TypeError, ValueError):
        return 1.0


def _iter_lines(geom):
    """Devuelve [(xs, ys), ...] para LineString o MultiLineString (una por parte)."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        x, y = geom.xy
        return [(list(x), list(y))]
    if geom.geom_type == "MultiLineString":
        salida = []
        for parte in geom.geoms:
            x, y = parte.xy
            salida.append((list(x), list(y)))
        return salida
    return []


def generar_html(resultados_gdf, salida_html, grupos=None, titulo="Consecuencia de Falla"):
    """Genera el HTML del visualizador a partir del GeoDataFrame de resultados.

    resultados_gdf : capa DatosConsecuenciaDeFalla (geometria de lineas + columnas CF).
    salida_html    : ruta del .html a escribir.
    grupos         : config de criticidad (pesos + params). None = GRUPOS_DEFAULT.
    """
    grupos = grupos if grupos is not None else _crit.GRUPOS_DEFAULT

    # Columnas CF que participan (resueltas contra las presentes).
    mapa, faltantes = _crit.resolver_columnas(resultados_gdf.columns, grupos)
    if faltantes:
        raise KeyError(
            f"Faltan columnas para el visualizador: {faltantes}. "
            "Corré el flujo de CdeF primero."
        )
    params = sorted(mapa.keys())

    # A Web Mercator para el fondo de tiles.
    gdf = resultados_gdf.to_crs(3857)

    xs, ys = [], []
    datos_param = {p: [] for p in params}
    crit_ini = []
    escala = _crit.ESCALA

    for _, fila in gdf.iterrows():
        valores_cf = {p: _cf(fila[mapa[p]]) for p in params}
        # criticidad inicial con los pesos default de `grupos`
        total = 0.0
        for g in grupos.values():
            ps = [p for p in g["params"] if p in mapa]
            if not ps:
                continue
            s = sum(valores_cf[p] for p in ps)
            total += g["peso"] * (s / (len(g["params"]) * escala))
        crit_val = round(total * escala, 2)
        for xseg, yseg in _iter_lines(fila.geometry):
            xs.append(xseg)
            ys.append(yseg)
            for p in params:
                datos_param[p].append(valores_cf[p])
            crit_ini.append(crit_val)

    source = ColumnDataSource(data={"xs": xs, "ys": ys, "criticidad": crit_ini, **datos_param})

    # Mismas 6 clases que el renderer de QGIS (criticidad.CLASES_COLOR): verde
    # abajo, rojo arriba. low=0/high=6 con 6 colores parte en tramos de 1, o sea
    # los mismos cortes que las reglas '"Criticidad" > N AND <= N+1' del plugin.
    paleta = [color for _, color, _ in _crit.CLASES_COLOR]
    mapper = LinearColorMapper(palette=paleta, low=0.0, high=6.0)

    p = figure(
        title=titulo, x_axis_type="mercator", y_axis_type="mercator",
        sizing_mode="stretch_both", tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
    )
    p.add_tile("CartoDB Positron")
    lineas = p.multi_line(
        xs="xs", ys="ys", source=source,
        line_color={"field": "criticidad", "transform": mapper},
        line_width=3, line_alpha=0.9,
    )
    p.add_tools(HoverTool(renderers=[lineas], tooltips=[("Criticidad", "@criticidad{0.00}")]))
    # Marcas en los cortes de clase (0..6), para que la barra se lea como la
    # leyenda de QGIS y no como un degradado continuo.
    p.add_layout(
        ColorBar(
            color_mapper=mapper,
            title="Criticidad",
            ticker=FixedTicker(ticks=[b for b, _, _ in _crit.CLASES_COLOR] + [0]),
        ),
        "right",
    )

    # Sliders de peso por grupo + metadata para el recalculo JS.
    sliders = []
    grupos_js = []
    for i, (nombre, g) in enumerate(grupos.items()):
        ps = [p_ for p_ in g["params"] if p_ in mapa]
        if not ps:
            continue
        s = Slider(start=0.0, end=1.0, value=float(g["peso"]), step=0.05,
                   title=f"Peso · {nombre}", sizing_mode="stretch_width")
        sliders.append(s)
        grupos_js.append({"params": ps, "n": len(g["params"]), "peso_idx": len(sliders) - 1})

    callback = CustomJS(
        args={"source": source, "sliders": sliders, "escala": escala, "grupos": grupos_js},
        code="""
        const data = source.data;
        const n = data['criticidad'].length;
        for (let i = 0; i < n; i++) {
            let total = 0.0;
            for (const g of grupos) {
                let s = 0.0;
                for (const p of g.params) { s += data[p][i]; }
                total += sliders[g.peso_idx].value * (s / (g.n * escala));
            }
            data['criticidad'][i] = Math.round(total * escala * 100) / 100;
        }
        source.change.emit();
        """,
    )
    for s in sliders:
        s.js_on_change("value", callback)

    encabezado = Div(text=f"<h2 style='margin:0;color:#990000'>{titulo}</h2>"
                          "<p style='color:#34495E;font-size:13px'>Mové los pesos para "
                          "recalcular la criticidad de cada tramo en vivo.</p>")
    panel = column(encabezado, *sliders, width=320, sizing_mode="stretch_height")
    layout = row(panel, p, sizing_mode="stretch_both")

    html = file_html(layout, CDN, titulo)
    with open(salida_html, "w", encoding="utf-8") as f:
        f.write(html)
    return salida_html
