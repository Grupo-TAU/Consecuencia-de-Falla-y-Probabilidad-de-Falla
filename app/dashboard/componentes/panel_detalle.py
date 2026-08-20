"""
Panel de detalle del tramo seleccionado: por que ESTE tramo es crítico.

El mapa dice cuales son los tramos criticos; no dice por que. Un tramo con
indice 3,8 puede llegar ahi por antiguedad, por estar al lado de un curso de agua
o por ser un colector de 800 mm bajo una avenida, y la obra que corresponde es
distinta en cada caso.

Las barras horizontales comparan el valor de cada criterio de ese tramo contra la
MEDIANA de la capa. Contra la mediana y no contra la escala 1-6 porque lo que
importa es el desvio respecto del resto de la red: un 4 en un criterio donde
todos los tramos sacan 4 no explica nada.
"""
import numpy as np
from bokeh.models import ColumnDataSource, Div, FactorRange, HoverTool
from bokeh.plotting import figure

from .. import estado

ALTO = 240


def crear(tablero):
    """Devuelve (layout_div, figura, actualizar) — actualizar(indices) redibuja."""
    datos = tablero.datos
    criterios = list(datos.criterios)
    X, _ = tablero.matriz()
    medianas = np.median(X, axis=0)

    fuente = ColumnDataSource(data={
        "criterio": criterios,
        "valor": [0.0] * len(criterios),
        "mediana": medianas.tolist(),
        "color": ["#DDDDDD"] * len(criterios),
        "desvio": [0.0] * len(criterios),
    })

    fig = figure(
        y_range=FactorRange(*reversed(criterios)), height=ALTO,
        sizing_mode="stretch_width", toolbar_location=None, tools="",
        title="Criterios del tramo (barra) vs. mediana de la red (marca)",
        x_range=(0, 6.4),
    )
    fig.hbar(y="criterio", right="valor", height=0.62, source=fuente,
             fill_color="color", line_color="#666666", line_width=0.5)
    # La mediana como marca vertical sobre cada barra: la comparacion se lee de
    # un vistazo, sin tener que buscar un segundo grafico.
    fig.scatter(x="mediana", y="criterio", source=fuente, marker="dash",
                size=22, angle=np.pi / 2, line_color="#34495E", line_width=2)
    fig.add_tools(HoverTool(tooltips=[
        ("Criterio", "@criterio"),
        ("Este tramo", "@valor{0.00}"),
        ("Mediana de la red", "@mediana{0.00}"),
        ("Desvío", "@desvio{+0.00}"),
    ]))
    fig.xaxis.axis_label = "Puntaje del criterio (1–6)"
    fig.ygrid.grid_line_color = None
    fig.x_range.start = 0

    encabezado = Div(text=_texto_vacio(), sizing_mode="stretch_width")

    def actualizar(seleccion):
        """seleccion: lista de indices de fila. Se usa el primero."""
        if not seleccion:
            encabezado.text = _texto_vacio()
            fuente.data["valor"] = [0.0] * len(criterios)
            fuente.data["color"] = ["#DDDDDD"] * len(criterios)
            fuente.data["desvio"] = [0.0] * len(criterios)
            return

        i = int(seleccion[0])
        Xi, _ = tablero.matriz()
        med = np.median(Xi, axis=0)
        valores = Xi[i]
        desvio = valores - med
        # Rojo lo que esta por encima de la mediana, verde lo que esta por debajo:
        # el color responde "¿esto es lo que lo hace critico?", no la magnitud.
        colores = [estado.COLOR_ALERTA if d > 0.25 else
                   (estado.COLOR_OK if d < -0.25 else "#BBBBBB") for d in desvio]

        fuente.data.update({
            "valor": valores.tolist(),
            "mediana": med.tolist(),
            "color": colores,
            "desvio": desvio.tolist(),
        })
        encabezado.text = _texto_tramo(tablero, i, criterios, valores, desvio)

    return encabezado, fig, actualizar


def _texto_vacio():
    return ("<div style='font-size:13px;color:#8A8A8A;padding:6px 0'>"
            "Hacé clic en un tramo del mapa para ver por qué puntúa como puntúa."
            "</div>")


def _num(x, dec=2, signo=False):
    """Numero con coma decimal. Se formatea el numero y no la frase: aplicar
    .replace('.', ',') sobre el HTML entero rompe las etiquetas y los estilos."""
    return f"{x:{'+' if signo else ''}.{dec}f}".replace(".", ",")


def _miles(x):
    """Separador de miles con punto, como se escribe en Uruguay."""
    return f"{x:,.0f}".replace(",", ".")


def _texto_tramo(tablero, i, criterios, valores, desvio):
    datos = tablero.datos
    fuente = tablero.fuente.data
    idx = float(np.asarray(fuente["indice"])[i])
    largo = float(np.asarray(fuente["longitud"])[i])
    ident = fuente["id"][i]

    # El criterio que mas lo aleja de la mediana es la respuesta corta a "por que".
    j = int(np.argmax(desvio))
    culpable = (f"El criterio que más lo separa del resto es "
                f"<b>{criterios[j]}</b> ({_num(valores[j])}, "
                f"{_num(desvio[j], signo=True)} respecto de la mediana)."
                if desvio[j] > 0 else
                "Ningún criterio lo pone por encima de la mediana de la red.")

    # Los crudos se leen del GeoDataFrame, no del ColumnDataSource: este texto se
    # arma en el servidor, asi que no hay motivo para que el dato haya viajado.
    crudos = []
    for col, etiqueta, dec in (("diametro", "Sección", 0),
                               ("antiguedad", "Antigüedad", 0),
                               ("material", "Material", None),
                               ("obstrucciones", "Obstrucciones", 0),
                               ("nro_arbol_5m", "Árboles a 5 m", 0),
                               ("dist_arbol", "Distancia al árbol", 1)):
        v = datos.crudo(col, i)
        if v is None:
            continue
        texto = v if dec is None else _num(float(v), dec)
        crudos.append(f"{etiqueta}: <b>{texto}</b>")

    detalle = " · ".join(crudos)
    return (
        "<div style='font-size:13px;padding:4px 0'>"
        f"<b style='color:{estado.COLOR_TITULO};font-size:15px'>Tramo {ident}</b>"
        f"<span style='color:#8A8A8A'> · {_miles(largo)} m</span>"
        f"<br><b>{tablero.etiqueta_operador()}: {_num(idx)}</b>"
        f"<br><span style='color:{estado.COLOR_TEXTO}'>{culpable}</span>" +
        (f"<br><span style='color:#8A8A8A;font-size:12px'>{detalle}</span>"
         if detalle else "") +
        "</div>")
