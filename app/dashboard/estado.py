"""
Configuracion del tablero: rutas, parametros y todo lo que se toca sin recompilar.

Se lee de variables de entorno para que `bokeh serve` no necesite argumentos
propios (no los pasa al script) y para que la misma app sirva otra capa sin tocar
codigo:

    CF_GPKG    ruta al GeoPackage de resultados (DatosConsecuenciaDeFalla)
    CF_CAPA    nombre de la capa dentro del .gpkg
    CF_CACHE   carpeta donde viven los parquet precalculados
    CF_NSIM    simulaciones del Monte Carlo al arrancar
"""
import os

# Ruta por defecto: la capa de Resto de Montevideo. Se pisa con CF_GPKG.
GPKG_DEFAULT = os.environ.get(
    "CF_GPKG",
    r"G:\Unidades compartidas\GRUPO TAU\02 - EQUIPO TAU\NA\Resto de Montevideo"
    r"\Datos\colectores_ConsecuenciaDeFalla.gpkg",
)
CAPA_DEFAULT = os.environ.get("CF_CAPA", "DatosConsecuenciaDeFalla")

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.environ.get("CF_CACHE", os.path.join(RAIZ, "cache"))

# ── Monte Carlo ──────────────────────────────────────────────────────────────
N_SIM_DEFAULT = int(os.environ.get("CF_NSIM", "1000"))
N_SIM_MIN, N_SIM_MAX, N_SIM_PASO = 100, 5000, 100
SEED = 42

# ── Render ───────────────────────────────────────────────────────────────────
# Tolerancia de simplificacion en metros, para el dibujo (los calculos van sobre
# la geometria original). En esta capa compra poco —los tramos tienen 2,25
# vertices promedio, o sea que ya son casi rectas— pero no cuesta nada y sirve
# para capas con geometria mas detallada. Lo que si mueve la aguja es WEBGL.
TOLERANCIA_SIMPLIFY = 1.0
# NO PRENDER WEBGL EN ESTA CAPA. Medido en Chromium con GPU real (NVIDIA
# GTX 1050 Ti, verificado con WEBGL_debug_renderer_info en cada corrida para no
# estar midiendo SwiftShader por accidente). Paneando los 60.726 tramos, mediana
# de 40 cuadros:
#
#     canvas     71 ms por cuadro   (~14 FPS)
#     webgl   2.431 ms por cuadro   (~0,4 FPS)
#
# Unas 27 veces mas lento, y no mejora sacando los tiles, la transparencia ni los
# estilos de seleccion: las cuatro variantes de WebGL dieron lo mismo. El motivo
# es la forma de la capa: 58.647 de los 60.726 tramos son segmentos de DOS
# puntos, y el backend WebGL de Bokeh arma estado por linea —60.000 draw calls—
# donde canvas traza paths de corrido. WebGL rinde con pocas lineas largas, que
# es exactamente lo contrario de una red de colectores.
#
# Es tambien la razon por la que el visualizador HTML de siempre se movia mejor
# que este tablero: nunca declaro output_backend, asi que quedo en canvas. Con
# canvas el tablero servido queda en 90 ms contra los 71 ms del HTML; esos 19 ms
# son el websocket de bokeh serve sincronizando el rango, y son inevitables en
# una app servida.
WEBGL = False
ANCHO_LINEA = 2.5
# Decimales de las coordenadas que viajan al navegador. Ver
# data.coordenadas_para_dibujo: van como JSON, no como buffer binario, y
# redondear a 2 decimales recorta un 34 % del payload sin perder precision
# dibujable (2 decimales en Web Mercator son centesimas de metro).
DECIMALES_COORD = 2
# Construir los cuatro tabs al arrancar manda 242.904 glifos al navegador cuando
# solo se ve uno. Con esto, cada tab se arma la primera vez que se lo abre.
TABS_PEREZOSOS = True

N_CLASES = 6
CRS_MAPA = 3857          # Web Mercator, obligatorio para los tiles
TILE = "CartoDB Positron"

# ── Priorizacion ─────────────────────────────────────────────────────────────
COSTO_POR_METRO_DEFAULT = 15000.0     # $/m — parametro, no presupuesto
PRESUPUESTO_PASOS = 40                # posiciones del slider (0 a 20 % de la red)
FRACCION_PRESUPUESTO_MAX = 0.20

# ── Tablas ───────────────────────────────────────────────────────────────────
TOP_N_DEFAULT = 200
TOP_N_IMPACTO = 100

# ── Paleta de categorias de robustez ─────────────────────────────────────────
COLOR_CATEGORIA = {
    "Robusto": "#D62728",       # rojo: intervenir si o si
    "Volátil": "#FF7F0E",       # naranja: llevar a discusion
    "Intermedio": "#FFD92F",
    "Descartable": "#BBBBBB",
}

# Colores de la interfaz, alineados con el visualizador HTML existente.
COLOR_TITULO = "#990000"
COLOR_TEXTO = "#34495E"
COLOR_OK = "#2CA02C"
COLOR_ALERTA = "#D62728"
COLOR_AVISO = "#E08A1E"
