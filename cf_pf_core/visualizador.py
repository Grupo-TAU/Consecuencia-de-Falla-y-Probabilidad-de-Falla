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
    FactorRange,
    FixedTicker,
    HoverTool,
    LinearColorMapper,
    Select,
    Slider,
)
from bokeh.plotting import figure
from bokeh.resources import CDN

from cf_pf_core.calculos import criticidad as _crit
from cf_pf_core.calculos import proximidad as _prox
from cf_pf_core.claves import normalizar as normalizar_clave


def _cf(v):
    """Igual que criticidad._cf: acota a [1,6], NULL/invalidos -> 1."""
    try:
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return 1.0
        return max(1.0, min(6.0, float(v)))
    except (TypeError, ValueError):
        return 1.0


# Etiqueta legible y columna con el valor CRUDO que origino cada clase CF.
# El crudo se muestra entre parentesis, como en el visualizador de las entregas
# ("Profundidad: 2 (2.1)"). Si la columna cruda no esta en la capa, se muestra
# solo la clase: son columnas de la capa de Colectores y la capa de salida no
# siempre las arrastra.
ETIQUETAS_CF = {
    "CF_PosicionRelativa": ("Posición relativa", "posicionRelativa"),
    "CF_Diametro": ("Sección", "DIAMETRO"),
    "CF_Profundidad": ("Profundidad", "PROFUNDIDAD"),
    "CF_Ubicacion": ("Ubicación tubería", "TIPO"),
    "CF_Prox_MedioAmbiental": ("Características medioambientales",
                               "Dist_Prox_MedioAmbiental"),
    "CF_Acceso_Mantenimiento": ("Acceso inspección", None),
    "CF_Prox_SitiosInteres": ("Distancia clientes importantes",
                              "Dist_Prox_SitiosInteres"),
    "CF_Antiguedad": ("Antigüedad", "Antiguedad"),
    "CF_Material": ("Material", "Material"),
    "CF_Obstrucciones": ("Obstrucciones", "Obstrucciones"),
    "CF_Arboles": ("Árboles a 5 m", "nro_arbol_5m"),
}

# Nombre legible de las variables del selector que no son CF_*.
ETIQUETAS_VISTA = {
    "criticidad": "Consecuencia ajustada",
    "CF": "Consecuencia ajustada",
    "PF": "Falla general",
    "Riesgo": "Riesgo",
    "Dist_Prox_MedioAmbiental": "Distancia a curso de agua (m)",
    "Dist_Prox_SitiosInteres": "Distancia a sitio de interés (m)",
}

# Columnas sueltas que se muestran tal cual si estan presentes.
ETIQUETAS_SUELTAS = [
    ("Longitud", "Longitud", "{0.000}"),
    ("dist_arbol", "Distancia al árbol (m)", "{0.0}"),
    ("PF", "Falla general", "{0.00}"),
    ("Riesgo", "Riesgo", "{0.00}"),
]


def _col_real(nombre, columnas):
    """Nombre real de una columna, sin distinguir mayusculas. None si no esta.

    Las capas vienen de distintas intendencias y el mismo campo aparece como
    'DIAMETRO', 'Diametro' o 'diametro'. El resto del core ya es tolerante a
    esto (ver riesgo._buscar y flujo._col); el visualizador tiene que serlo
    tambien o pierde los valores crudos del tooltip sin decir nada.
    """
    if nombre is None:
        return None
    if nombre in columnas:
        return nombre
    return {str(c).lower(): c for c in columnas}.get(str(nombre).lower())


def _clave_de(columnas):
    """Columna identificadora del tramo, si alguna de las habituales esta."""
    for c in ("ELEMRED", "ID", "id"):
        real = _col_real(c, columnas)
        if real:
            return real
    return None


def adjuntar_crudos(resultados_gdf, colectores_gdf, clave=None):
    """Trae de la capa de Colectores los valores CRUDOS que el tooltip muestra
    entre parentesis, y que la capa de salida no arrastra.

    La capa DatosConsecuenciaDeFalla solo lleva clave + geometria + resultados,
    asi que DIAMETRO, PROFUNDIDAD, TIPO, Material, Antiguedad, Obstrucciones y
    Longitud hay que ir a buscarlos a la fuente. Devuelve una copia; si no hay
    clave comun o no falta nada, devuelve la capa tal cual.
    """
    if colectores_gdf is None:
        return resultados_gdf
    clave_res = _col_real(clave, resultados_gdf.columns) or _clave_de(resultados_gdf.columns)
    clave_col = _col_real(clave_res, colectores_gdf.columns) if clave_res else None
    if not clave_res or not clave_col:
        return resultados_gdf

    quiero = [c for _, c in ETIQUETAS_CF.values() if c]
    quiero += [col for col, _, _ in ETIQUETAS_SUELTAS if col not in ("PF", "Riesgo")]
    # Los nombres se resuelven sin distinguir mayusculas contra CADA capa: la
    # fuente puede traer 'diametro' donde la tabla dice 'DIAMETRO'.
    faltan = []
    for nombre in dict.fromkeys(quiero):
        real = _col_real(nombre, colectores_gdf.columns)
        if real and not _col_real(nombre, resultados_gdf.columns):
            faltan.append(real)
    if not faltan:
        return resultados_gdf

    izq = resultados_gdf.copy()
    orden = izq.index
    izq["__clave"] = izq[clave_res].map(normalizar_clave)
    aporte = colectores_gdf[[clave_col, *faltan]].copy()
    aporte["__clave"] = aporte[clave_col].map(normalizar_clave)
    # Una clave repetida en la fuente multiplicaria las filas del resultado.
    aporte = aporte.drop_duplicates(subset="__clave").drop(columns=[clave_col])

    unido = izq.merge(aporte, on="__clave", how="left").drop(columns="__clave")
    unido.index = orden
    return gpd.GeoDataFrame(unido, geometry=resultados_gdf.geometry.name,
                            crs=resultados_gdf.crs)


def _fmt_num(x):
    if x == float("inf"):
        return "∞"
    return f"{x:,.0f}".replace(",", ".") if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def _etiquetas_bins(cortes):
    """'0–25', '25–50', ..., '> 400' a partir de los limites superiores."""
    salida, previo = [], 0.0
    for c in cortes:
        salida.append(f"> {_fmt_num(previo)}" if c == float("inf")
                      else f"{_fmt_num(previo)}–{_fmt_num(c)}")
        previo = c
    return salida


def _vista_de(columna, valores, campo_crit, n_clases, paleta):
    """Como se dibuja una variable: cortes, etiquetas, colores y sentido.

    Los cortes NO son tramos iguales: son los limites que ya definen el
    significado de cada variable. Para las distancias son los mismos rangos con
    los que se calculo el CF, porque repartir 0..maximo en seis partes iguales
    amontona el 95 % de los tramos en el primer color (un par de outliers a 4 km
    estiran la escala y el mapa queda de un solo tono).

    'invertir' existe porque en las distancias MENOS es PEOR: un colector pegado
    a un curso de agua tiene que salir rojo, no verde.
    """
    col = columna.lower()
    if columna == campo_crit or columna.startswith("CF_") or col == "pf":
        cortes = [float(b) for b, _, _ in _crit.CLASES_COLOR]
        invertir = False
    elif col == "riesgo":
        cortes = [6.0, 12.0, 18.0, 24.0, 30.0, 36.0]
        invertir = False
    elif col.startswith("dist_"):
        rango = (_prox.RANGOS_MEDIOAMBIENTAL_DEFAULT if "medioamb" in col
                 else _prox.RANGOS_SITIOS_DEFAULT)
        limites = [d for d, _c in _prox.parse_rangos(rango)]
        cortes = limites[:n_clases - 1] + [float("inf")]
        invertir = True
    else:
        numeros = [v for v in valores if isinstance(v, (int, float)) and v == v]
        alto = float(max(max(numeros, default=1.0), 1.0))
        paso = alto / n_clases
        cortes = [paso * (i + 1) for i in range(n_clases)]
        invertir = False

    while len(cortes) < n_clases:
        cortes.append(float("inf"))
    cortes = cortes[:n_clases]

    # Colores en el orden NATURAL de la variable (primer bin primero). Al invertir,
    # el bin mas cercano se lleva el rojo.
    colores = list(reversed(paleta)) if invertir else list(paleta)
    # Etiquetas del ColorBar: la barra siempre va de verde (0) a rojo (n).
    bordes = [0.0] + list(cortes)
    if invertir:
        bordes = list(reversed(bordes))
    return {
        "cortes": cortes,
        "invertir": invertir,
        "etiquetas": _etiquetas_bins(cortes),
        "colores": colores,
        "barra": {str(i): _fmt_num(b) for i, b in enumerate(bordes)},
        "cero_sin_dato": col == "pf",
    }


def _clase(valor, n_clases):
    """Indice de clase de un valor de criticidad, 0..n_clases-1.

    Mismo corte que usa LinearColorMapper para colorear el mapa (tramos de 1
    arrancando en 0), para que la barra del histograma y el color de la linea
    nunca se contradigan.
    """
    k = int(valor)
    return 0 if k < 0 else (n_clases - 1 if k > n_clases - 1 else k)


def _estadisticos(valores):
    """(n, promedio, mediana, minimo, maximo) de una lista ya filtrada."""
    if not valores:
        return 0, 0.0, 0.0, 0.0, 0.0
    orden = sorted(valores)
    n = len(orden)
    mediana = orden[n // 2] if n % 2 else (orden[n // 2 - 1] + orden[n // 2]) / 2
    return n, sum(orden) / n, mediana, orden[0], orden[-1]


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

    # Columnas CF que participan. Solo se exigen las de los grupos CON peso: un
    # grupo en 0 no mueve la criticidad, asi que su columna es opcional.
    _mapa_activos, faltantes = _crit.resolver_columnas(resultados_gdf.columns, grupos)
    if faltantes:
        raise KeyError(
            f"Faltan columnas para el visualizador: {faltantes}. "
            "Corré el flujo de CdeF primero."
        )
    # Para mostrar se resuelven TODOS los grupos, aunque hoy esten en 0: asi el
    # slider aparece igual y el usuario puede subirle el peso desde el HTML.
    mapa, _ = _crit.resolver_columnas(resultados_gdf.columns, grupos,
                                      solo_activos=False)
    params = sorted(mapa.keys())

    # A Web Mercator para el fondo de tiles.
    gdf = resultados_gdf.to_crs(3857)

    # Columnas de contexto que se llevan al tooltip: la clave del tramo, los
    # crudos que acompañan a cada CF y las sueltas (Longitud/PF/Riesgo). Solo las
    # que existan realmente en la capa.
    presentes = list(gdf.columns)
    clave_col = _clave_de(presentes)
    extras = []
    if clave_col:
        extras.append(clave_col)
    # crudo_de: columna CF -> nombre REAL de su columna cruda en esta capa.
    crudo_de = {}
    for cf_col, (_, crudo) in ETIQUETAS_CF.items():
        real = _col_real(crudo, presentes) if crudo else None
        if cf_col in mapa and real:
            crudo_de[cf_col] = real
            if real not in extras:
                extras.append(real)
    sueltas = []  # (nombre_real, etiqueta, formato)
    for col, etiqueta, fmt in ETIQUETAS_SUELTAS:
        real = _col_real(col, presentes)
        if real:
            sueltas.append((real, etiqueta, fmt))
            if real not in extras:
                extras.append(real)

    xs, ys = [], []
    datos_param = {p: [] for p in params}
    crit_ini = []
    # 1 en la primera fila de cada tramo, 0 en el resto. Un MultiLineString ocupa
    # varias filas del source (una por parte) y todas comparten criticidad: sin
    # esta marca, los estadisticos contarian de mas los tramos multiparte.
    primero = []
    datos_extra = {c: [] for c in extras}
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
        for j, (xseg, yseg) in enumerate(_iter_lines(fila.geometry)):
            xs.append(xseg)
            ys.append(yseg)
            for p in params:
                datos_param[p].append(valores_cf[p])
            crit_ini.append(crit_val)
            primero.append(1 if j == 0 else 0)
            for c in extras:
                v = fila[c]
                datos_extra[c].append("" if v is None or v != v else v)

    # Nombre con el que la criticidad viaja en el source. La capa puede traerla
    # como 'CF' (ver flujo.campo_criticidad), pero aca adentro se maneja siempre
    # con un nombre fijo: lo que cambia afuera es la columna del .gpkg.
    campo_crit_col = "criticidad"

    # 'valor' es la columna que colorea el mapa. Arranca igual que criticidad y
    # el selector la reemplaza por la variable que se elija; asi el renderer no
    # tiene que cambiar de campo, que en Bokeh no se puede hacer en vivo.
    source = ColumnDataSource(data={"xs": xs, "ys": ys, "criticidad": crit_ini,
                                    "valor": [min(5.0, max(0.0, float(int(c)))) + 0.5
                                              for c in crit_ini],
                                    "primero": primero, **datos_param,
                                    **datos_extra})

    # Mismas 6 clases que el renderer de QGIS (criticidad.CLASES_COLOR): verde
    # abajo, rojo arriba. low=0/high=6 con 6 colores parte en tramos de 1, o sea
    # los mismos cortes que las reglas '"Criticidad" > N AND <= N+1' del plugin.
    paleta = [color for _, color, _ in _crit.CLASES_COLOR]
    # El mapper trabaja siempre sobre el INDICE de clase (0..n), no sobre el valor
    # crudo: asi cada variable puede tener sus propios cortes —que no son tramos
    # iguales— y hasta invertir el sentido, sin tocar el renderer.
    mapper = LinearColorMapper(palette=paleta, low=0.0,
                               high=float(len(_crit.CLASES_COLOR)),
                               nan_color="#BBBBBB")

    p = figure(
        title=titulo, x_axis_type="mercator", y_axis_type="mercator",
        sizing_mode="stretch_both", tools="pan,wheel_zoom,box_zoom,reset,save",
        active_scroll="wheel_zoom",
    )
    p.add_tile("CartoDB Positron")
    lineas = p.multi_line(
        xs="xs", ys="ys", source=source,
        line_color={"field": "valor", "transform": mapper},
        line_width=3, line_alpha=0.9,
    )
    # Tooltip: clave, cada CF con su crudo entre parentesis, las sueltas y la
    # criticidad al final (que es la que se mueve con los sliders).
    def _fmt(col):
        """Un decimal para los flotantes (distancias, profundidades); los enteros
        y los textos van tal cual, para no mostrar 'PVC{0.0}' ni '26.0'."""
        return "{0.0}" if gdf[col].dtype.kind == "f" else ""

    tooltips = []
    if clave_col:
        tooltips.append(("ID", f"@{{{clave_col}}}"))
    for real, etiqueta, fmt in sueltas:
        if etiqueta == "Longitud":
            tooltips.append((etiqueta, f"@{{{real}}}{fmt}"))
    for cf_col in params:
        etiqueta, _ = ETIQUETAS_CF.get(cf_col, (cf_col, None))
        crudo = crudo_de.get(cf_col)
        if crudo:
            tooltips.append((etiqueta, f"@{{{cf_col}}} (@{{{crudo}}}{_fmt(crudo)})"))
        else:
            tooltips.append((etiqueta, f"@{{{cf_col}}}"))
    for real, etiqueta, fmt in sueltas:
        if etiqueta != "Longitud":
            tooltips.append((etiqueta, f"@{{{real}}}{fmt}"))
    tooltips.append(("Consecuencia ajustada", "@criticidad{0.00}"))
    p.add_tools(HoverTool(renderers=[lineas], tooltips=tooltips))
    # Marcas en los cortes de clase (0..6), para que la barra se lea como la
    # leyenda de QGIS y no como un degradado continuo.
    barra = ColorBar(
        color_mapper=mapper,
        title="Criticidad",
        ticker=FixedTicker(ticks=list(range(len(_crit.CLASES_COLOR) + 1))),
        major_label_overrides={str(b): str(b) for b in
                               range(len(_crit.CLASES_COLOR) + 1)},
    )
    p.add_layout(barra, "right")

    # ── Panel de analisis: distribucion por clase + estadisticos ──────────────
    # Las clases y los colores son los mismos de la simbologia, asi la barra del
    # histograma y la linea del mapa se leen como lo mismo.
    n_clases = len(_crit.CLASES_COLOR)
    etiquetas = [f"{lim - 1}–{lim}" for lim, _, _ in _crit.CLASES_COLOR]

    valores_tramo = [c for c, pr in zip(crit_ini, primero) if pr]
    conteo_ini = [0] * n_clases
    for v in valores_tramo:
        conteo_ini[_clase(v, n_clases)] += 1

    hist_source = ColumnDataSource(data={
        "clase": etiquetas, "conteo": conteo_ini, "color": paleta,
    })
    hist = figure(
        x_range=FactorRange(*etiquetas), height=190, sizing_mode="stretch_width",
        toolbar_location=None, tools="", title="Tramos por clase",
    )
    hist.vbar(x="clase", top="conteo", width=0.8, source=hist_source,
              fill_color="color", line_color="#666666", line_width=0.5)
    hist.add_tools(HoverTool(tooltips=[("Clase", "@clase"), ("Tramos", "@conteo")]))
    hist.y_range.start = 0
    hist.xgrid.grid_line_color = None
    hist.xaxis.major_label_orientation = 0.8

    n_t, prom, med, mini, maxi = _estadisticos(valores_tramo)

    def _texto_stats(n, prom, med, mini, maxi):
        filas = (("Tramos", f"{n}"), ("Promedio", f"{prom:.2f}"),
                 ("Mediana", f"{med:.2f}"), ("Mínimo", f"{mini:.2f}"),
                 ("Máximo", f"{maxi:.2f}"))
        celdas = "".join(
            f"<tr><td style='color:#34495E;padding:1px 8px 1px 0'>{k}</td>"
            f"<td style='text-align:right;font-weight:600'>{v}</td></tr>"
            for k, v in filas
        )
        return f"<table style='font-size:13px;width:100%'>{celdas}</table>"

    stats = Div(text=_texto_stats(n_t, prom, med, mini, maxi),
                sizing_mode="stretch_width")

    # Sliders de peso por grupo + metadata para el recalculo JS.
    sliders = []
    grupos_js = []
    for i, (nombre, g) in enumerate(grupos.items()):
        ps = [p_ for p_ in g["params"] if p_ in mapa]
        if not ps:
            continue
        s = Slider(start=0.0, end=1.0, value=float(g["peso"]), step=0.01,
                   title=f"Peso · {nombre}", sizing_mode="stretch_width")
        sliders.append(s)
        grupos_js.append({"params": ps, "n": len(g["params"]), "peso_idx": len(sliders) - 1})

    # Suma de los pesos. Con los defaults da 100%; al mover los sliders el usuario
    # tiene que poder ver si se fue de escala, porque la criticidad deja de estar
    # en 1..6 y el mapa se lee mal sin avisar.
    def _texto_suma(total):
        ok = abs(total - 1.0) < 1e-9
        color = "#2CA02C" if ok else "#D62728"
        nota = "" if ok else " — la criticidad no queda en escala 1–6"
        return (f"<div style='font-size:13px;padding:2px 0'>Suma de pesos: "
                f"<b style='color:{color}'>{total * 100:.0f}%</b>"
                f"<span style='color:#8A8A8A'>{nota}</span></div>")

    suma = Div(text=_texto_suma(sum(s.value for s in sliders)),
               sizing_mode="stretch_width")

    # ── Selector de variable ──────────────────────────────────────────────────
    # Todas las columnas ya viajan en el source; lo unico que cambia al elegir
    # otra variable es cual alimenta el color, el histograma y los estadisticos.
    vistas = {}
    opciones = []
    candidatas = [campo_crit_col, *params]
    candidatas += [c for c in ("PF", "Riesgo") if c in extras]
    candidatas += [c for c in extras if c.startswith("Dist_")]
    for col in dict.fromkeys(candidatas):
        if col == campo_crit_col:
            serie = crit_ini
        elif col in datos_param:
            serie = datos_param[col]
        elif col in datos_extra:
            serie = datos_extra[col]
        else:
            continue
        etiqueta = ETIQUETAS_VISTA.get(col) or (
            ETIQUETAS_CF.get(col, (col, None))[0] if col.startswith("CF_") else col)
        vistas[col] = {**_vista_de(col, serie, campo_crit_col, n_clases, paleta),
                       "titulo": etiqueta}
        opciones.append((col, etiqueta))

    selector = Select(title="Ver en el mapa", value=campo_crit_col,
                      options=opciones, sizing_mode="stretch_width")

    callback = CustomJS(
        args={"source": source, "sliders": sliders, "escala": escala,
              "grupos": grupos_js, "hist": hist_source, "stats": stats,
              "n_clases": n_clases, "suma": suma, "selector": selector,
              "vistas": vistas, "mapper": mapper, "barra": barra,
              "hist_fig": hist, "campo_crit": campo_crit_col},
        code="""
        // Suma de pesos: en verde si da 100%, en rojo si no.
        let total_peso = 0;
        for (const s of sliders) { total_peso += s.value; }
        const ok = Math.abs(total_peso - 1.0) < 1e-9;
        suma.text = "<div style='font-size:13px;padding:2px 0'>Suma de pesos: " +
            "<b style='color:" + (ok ? "#2CA02C" : "#D62728") + "'>" +
            (total_peso * 100).toFixed(0) + "%</b>" +
            "<span style='color:#8A8A8A'>" +
            (ok ? "" : " — la criticidad no queda en escala 1–6") + "</span></div>";

        const data = source.data;
        const n = data[campo_crit].length;
        // La criticidad se recalcula SIEMPRE, se este viendo o no: si el usuario
        // mueve los pesos mirando otra variable y despues vuelve, tiene que
        // encontrarla al dia.
        for (let i = 0; i < n; i++) {
            let total = 0.0;
            for (const g of grupos) {
                let s = 0.0;
                for (const p of g.params) { s += data[p][i]; }
                total += sliders[g.peso_idx].value * (s / (g.n * escala));
            }
            data[campo_crit][i] = Math.round(total * escala * 100) / 100;
        }

        // La variable elegida pasa a 'valor', que es la que colorea el mapa.
        // 'valor' no es el numero crudo sino el indice de clase: cada variable
        // tiene sus propios cortes y las distancias van al reves (mas cerca, peor).
        const campo = selector.value;
        const vista = vistas[campo];
        const clase_de = (v) => {
            if (v === null || v === undefined || v !== v) return null;
            if (vista.cero_sin_dato && v === 0) return null;   // PF 0 = sin inspeccion
            let k = n_clases - 1;
            for (let j = 0; j < vista.cortes.length; j++) {
                if (v <= vista.cortes[j]) { k = j; break; }
            }
            return k;
        };
        for (let i = 0; i < n; i++) {
            const k = clase_de(data[campo][i]);
            data['valor'][i] = (k === null) ? null
                : (vista.invertir ? (n_clases - 1 - k) : k) + 0.5;
        }
        source.change.emit();

        barra.title = vista.titulo;
        barra.major_label_overrides = vista.barra;
        hist_fig.title.text = "Tramos por clase · " + vista.titulo;

        // Distribucion y estadisticos: solo las filas con primero=1, para contar
        // cada tramo una vez y no una vez por parte de su geometria.
        const cuentas = new Array(n_clases).fill(0);
        const vals = [];
        for (let i = 0; i < n; i++) {
            if (!data['primero'][i]) continue;
            const bruto = data[campo][i];
            const k = clase_de(bruto);
            if (k === null) continue;          // sin dato: fuera del histograma
            vals.push(bruto);                  // los estadisticos van en la unidad real
            cuentas[k] += 1;                   // el histograma, en orden natural
        }
        hist_fig.x_range.factors = vista.etiquetas;
        hist.data['clase'] = vista.etiquetas;
        hist.data['conteo'] = cuentas;
        hist.data['color'] = vista.colores;
        hist.change.emit();

        vals.sort((a, b) => a - b);
        const m = vals.length;
        let prom = 0, med = 0, mini = 0, maxi = 0;
        if (m > 0) {
            let suma = 0;
            for (const v of vals) { suma += v; }
            prom = suma / m;
            med = (m % 2) ? vals[(m - 1) / 2] : (vals[m / 2 - 1] + vals[m / 2]) / 2;
            mini = vals[0];
            maxi = vals[m - 1];
        }
        const fila = (k, v) =>
            "<tr><td style='color:#34495E;padding:1px 8px 1px 0'>" + k +
            "</td><td style='text-align:right;font-weight:600'>" + v + "</td></tr>";
        stats.text = "<table style='font-size:13px;width:100%'>" +
            fila("Tramos", m) + fila("Promedio", prom.toFixed(2)) +
            fila("Mediana", med.toFixed(2)) + fila("Mínimo", mini.toFixed(2)) +
            fila("Máximo", maxi.toFixed(2)) + "</table>";
        """,
    )
    selector.js_on_change("value", callback)
    for s in sliders:
        s.js_on_change("value", callback)

    encabezado = Div(text=f"<h2 style='margin:0;color:#990000'>{titulo}</h2>"
                          "<p style='color:#34495E;font-size:13px'>Mové los pesos para "
                          "recalcular la criticidad de cada tramo en vivo. El mapa, la "
                          "distribución y los estadísticos se actualizan juntos.</p>",
                     sizing_mode="stretch_width")
    sep = Div(text="<hr style='border:none;border-top:1px solid #DDD;margin:8px 0'>"
                   "<b style='font-size:13px'>Análisis</b>",
              sizing_mode="stretch_width")
    panel = column(encabezado, selector, *sliders, suma, sep, stats, hist,
                   width=340, sizing_mode="stretch_height")
    layout = row(panel, p, sizing_mode="stretch_both")

    html = file_html(layout, CDN, titulo)
    with open(salida_html, "w", encoding="utf-8") as f:
        f.write(html)
    return salida_html
