"""
Panel de pesos: un slider por grupo, el operador de agregacion y el descuento
de variables duplicadas.

Es compartido entre tabs a proposito. El tab de sensibilidad existe justamente
para mostrar que la eleccion de pesos es discutible; tener dos paneles de pesos
distintos —uno para el mapa y otro para el analisis— haria que el usuario mire
un escenario y decida sobre otro.
"""
from bokeh.layouts import column
from bokeh.models import CheckboxGroup, Div, Select, Slider

from cf_pf_core.analisis import indices

from .. import estado


def _texto_suma(total):
    """Aviso de escala. Con pesos que no suman 100 % la criticidad se sale de
    1-6 y el mapa se lee mal sin decirlo."""
    ok = abs(total - 1.0) < 1e-6
    color = estado.COLOR_OK if ok else estado.COLOR_ALERTA
    nota = "" if ok else " — el índice deja de estar en escala 1–6"
    return (f"<div style='font-size:13px;padding:2px 0'>Suma de pesos: "
            f"<b style='color:{color}'>{total * 100:.0f} %</b>"
            f"<span style='color:#8A8A8A'>{nota}</span></div>")


def _texto_duplicadas(grupos):
    """Explica el toggle solo si hay algo que descontar."""
    mult = indices.multiplicidad(grupos)
    repetidas = [c for c, m in mult.items() if m > 1]
    if not repetidas:
        return ("<div style='font-size:12px;color:#8A8A8A;padding:2px 0'>"
                "Ninguna columna participa en más de un grupo.</div>")
    lista = ", ".join(f"<b>{c}</b>" for c in repetidas)
    return ("<div style='font-size:12px;color:#8A8A8A;padding:2px 0'>"
            f"{lista} participa(n) en más de un grupo, así que pesa(n) el doble "
            "de lo que sugieren los sliders. El descuento reparte esa "
            "contribución en partes iguales.</div>")


def panel(tablero):
    """Arma el panel y engancha los callbacks. Devuelve (layout, widgets)."""
    grupos = tablero.grupos

    sliders = {}
    for nombre, g in grupos.items():
        s = Slider(start=0.0, end=1.0, step=0.01, value=float(g["peso"]),
                   title=f"Peso · {nombre}", sizing_mode="stretch_width")
        sliders[nombre] = s

    suma = Div(text=_texto_suma(tablero.suma_pesos()), sizing_mode="stretch_width")

    operador = Select(title="Operador de agregación", value=tablero.operador,
                      options=list(indices.OPERADORES.items()),
                      sizing_mode="stretch_width")

    duplicadas = CheckboxGroup(labels=["Descontar variables duplicadas"],
                               active=[], sizing_mode="stretch_width")
    nota_dup = Div(text=_texto_duplicadas(grupos), sizing_mode="stretch_width")

    def _aplicar(attr, old, new):
        for nombre, s in sliders.items():
            tablero.grupos[nombre]["peso"] = float(s.value)
        tablero.operador = operador.value
        tablero.descontar_duplicadas = 0 in duplicadas.active
        suma.text = _texto_suma(tablero.suma_pesos())
        tablero.recalcular()

    for s in sliders.values():
        s.on_change("value_throttled", _aplicar)
    operador.on_change("value", _aplicar)
    duplicadas.on_change("active", _aplicar)

    ayuda = Div(
        text="<div style='font-size:12px;color:#8A8A8A;padding:2px 0 6px'>"
             "<b>Media aritmética</b>: el índice histórico. "
             "<b>Media geométrica</b>: penaliza el desbalance entre criterios. "
             "<b>Máximo</b>: manda el peor criterio e ignora la magnitud de los "
             "pesos (sólo usa qué grupos están activos).</div>",
        sizing_mode="stretch_width")

    layout = column(*sliders.values(), suma, operador, ayuda, duplicadas,
                    nota_dup, sizing_mode="stretch_width")
    return layout, {"sliders": sliders, "suma": suma, "operador": operador,
                    "duplicadas": duplicadas}


def tabla_pesos_efectivos(grupos, descontar=False):
    """HTML con peso declarado vs. efectivo por columna. Para el tab de diagnostico."""
    efec = indices.pesos_efectivos(grupos, descontar)
    parejo = indices.pesos_efectivos(grupos, True)
    filas = "".join(
        f"<tr><td style='padding:1px 10px 1px 0'>{c}</td>"
        f"<td style='text-align:right'>{efec[c] * 100:.1f} %</td>"
        f"<td style='text-align:right;color:{'#D62728' if abs(efec[c] - parejo[c]) > 1e-6 else '#8A8A8A'}'>"
        f"{parejo[c] * 100:.1f} %</td></tr>"
        for c in sorted(efec, key=lambda k: -efec[k]))
    return ("<table style='font-size:12px;width:100%'>"
            "<tr style='color:#34495E'><th style='text-align:left'>Columna</th>"
            "<th style='text-align:right'>Efectivo</th>"
            "<th style='text-align:right'>Parejo</th></tr>"
            f"{filas}</table>")
