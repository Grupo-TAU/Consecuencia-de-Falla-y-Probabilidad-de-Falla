"""
Punto de entrada del tablero.

    bokeh serve app/dashboard --show

Lo unico que hace este archivo es cargar la capa una vez, armar el Tablero
—dueño del ColumnDataSource compartido— y colgarle los cuatro tabs. Toda la
logica vive en los modulos: si esto crece, algo se puso en el lugar equivocado.

`bokeh serve` no pasa argumentos al script, asi que la capa se elige por variable
de entorno (ver estado.py):

    CF_GPKG=... CF_CAPA=... bokeh serve app/dashboard --show
"""
import os
import sys
import traceback

# bokeh serve ejecuta este archivo con el directorio de la app como raiz, asi que
# cf_pf_core no esta en el path a menos que se lo agregue.
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from bokeh.io import curdoc  # noqa: E402
from bokeh.layouts import column  # noqa: E402
from bokeh.models import Div, TabPanel, Tabs  # noqa: E402

from app.dashboard import data, estado, nucleo  # noqa: E402
from app.dashboard.tabs import diagnostico, mapa, priorizacion, sensibilidad  # noqa: E402

TITULO = "Consecuencia de Falla — Colectores"


def _encabezado(datos):
    """Franja superior: que capa se esta mirando y si el indice reproduce."""
    _prop, msg_repro = datos.verificar_reproduccion()
    avisos = [msg_repro]
    if datos.descartados:
        avisos.append(f"{datos.descartados} tramo(s) sin geometría descartados.")
    if datos.faltantes:
        avisos.append("Columnas ausentes en la capa (sus grupos se ajustaron): "
                      + ", ".join(sorted(set(datos.faltantes))) + ".")
    if getattr(datos, "aviso_colectores", None):
        avisos.append(datos.aviso_colectores)

    pesos_txt = " · ".join(f"{n} {g['peso'] * 100:.0f} %"
                           for n, g in datos.grupos.items())
    return Div(
        text=(f"<h2 style='margin:0;color:{estado.COLOR_TITULO}'>{TITULO}</h2>"
              f"<div style='font-size:12px;color:#8A8A8A;margin:2px 0'>"
              f"{len(datos):,}".replace(",", ".") +
              f" tramos · {os.path.basename(datos.ruta)} · capa {datos.capa} · "
              f"CRS {datos.crs_original}</div>"
              f"<div style='font-size:12px;color:#34495E'>Pesos iniciales: "
              f"{pesos_txt}</div>"
              "<div style='font-size:11px;color:#8A8A8A;margin-top:2px'>" +
              " ".join(avisos) + "</div>"),
        sizing_mode="stretch_width")


def _error(exc):
    return column(Div(
        text=("<h2 style='color:#D62728'>No se pudo iniciar el tablero</h2>"
              f"<pre style='font-size:12px;white-space:pre-wrap'>{exc}</pre>"
              "<p style='font-size:13px'>Indicá la capa con las variables de "
              "entorno <code>CF_GPKG</code> y <code>CF_CAPA</code>, o corré "
              "<code>python scripts/precompute.py --ayuda</code>.</p>"),
        sizing_mode="stretch_width"))


def armar():
    datos = data.cargar()
    tablero = nucleo.Tablero(datos)

    definiciones = [
        ("🗺️ Mapa", mapa.crear),
        ("🎲 Sensibilidad", sensibilidad.crear),
        ("🔬 Diagnóstico", diagnostico.crear),
        ("💰 Priorización", priorizacion.crear),
    ]

    if not estado.TABS_PEREZOSOS:
        tabs = Tabs(tabs=[TabPanel(child=fn(tablero), title=t)
                          for t, fn in definiciones],
                    sizing_mode="stretch_both")
        return column(_encabezado(datos), tabs, sizing_mode="stretch_both")

    # Construccion perezosa. Armar los cuatro tabs de entrada manda al navegador
    # los 60.726 tramos CUATRO veces —un renderer de multi_line por mapa, casi un
    # cuarto de millon de glifos— cuando en pantalla se ve uno solo. El costo no
    # es del servidor (que usa ~350 MB) sino del navegador, que tiene que crear y
    # mantener todos los glifos aunque esten en un tab oculto.
    #
    # Cada tab se arma la primera vez que se lo abre. El primero se arma ya,
    # porque es el que se ve al cargar la pagina.
    contenedores = [column(_cargando(t), sizing_mode="stretch_both")
                    for t, _ in definiciones]
    tabs = Tabs(tabs=[TabPanel(child=c, title=t)
                      for c, (t, _) in zip(contenedores, definiciones)],
                sizing_mode="stretch_both")
    construidos = set()

    def _construir(i):
        if i in construidos:
            return
        construidos.add(i)
        _titulo, fn = definiciones[i]
        contenedores[i].children = [fn(tablero)]

    def _al_cambiar(attr, old, new):
        if new in construidos:
            return
        # El Div de "armando…" ya esta en pantalla; el tab se construye en el
        # tick siguiente para que el navegador alcance a pintarlo. Si no, la
        # pagina se queda muda los segundos que tarda y parece colgada.
        curdoc().add_next_tick_callback(lambda: _construir(new))

    tabs.on_change("active", _al_cambiar)
    _construir(0)

    return column(_encabezado(datos), tabs, sizing_mode="stretch_both")


def _cargando(titulo):
    return Div(text=f"<div style='padding:24px;color:#8A8A8A;font-size:14px'>"
                    f"Armando <b>{titulo}</b>…</div>",
               sizing_mode="stretch_width")


try:
    raiz = armar()
except Exception as e:  # noqa: BLE001 — un error de carga tiene que verse en el
    # navegador y no solo en la consola del servidor: si la pagina queda en blanco
    # nadie sabe si el problema es la ruta del .gpkg o que el server no arranco.
    traceback.print_exc()
    raiz = _error(traceback.format_exc())

curdoc().add_root(raiz)
curdoc().title = TITULO
