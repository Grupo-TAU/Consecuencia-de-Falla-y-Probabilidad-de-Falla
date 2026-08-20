# Tablero de criticidad de colectores

Aplicación Bokeh de cuatro pestañas sobre la capa `DatosConsecuenciaDeFalla`.
Convierte el visualizador de siempre —mapa + sliders— en algo con lo que se puede
defender un plan de obra.

## Cómo correrlo

```bash
pip install -r app/requirements.txt

# 1. Precalcular lo pesado (Monte Carlo + LISA). Opcional pero recomendado:
#    sin esto los tabs 2 y 4 arrancan vacíos, con un botón para calcular.
python scripts/precompute.py

# 2. Levantar el tablero
bokeh serve app/dashboard --show
```

`bokeh serve` no acepta argumentos propios, así que la capa se elige por variable
de entorno:

| Variable | Qué es | Default |
|---|---|---|
| `CF_GPKG` | GeoPackage de resultados | la capa de Resto de Montevideo |
| `CF_CAPA` | capa dentro del `.gpkg` | `DatosConsecuenciaDeFalla` |
| `CF_COLECTORES` | capa de Colectores (trae `Longitud` y los crudos del tooltip) | se busca en `tramos/colectores.gpkg` al lado |
| `CF_CACHE` | carpeta del caché parquet | `cache/` en la raíz |
| `CF_NSIM` | simulaciones del Monte Carlo | `1000` |

```bash
CF_GPKG=/ruta/otra_capa.gpkg bokeh serve app/dashboard --show
```

### Esto **no** reemplaza al visualizador HTML

`cf_pf_core/visualizador.py` sigue igual y genera el `.html` autónomo y
compartible desde la app Streamlit. Son dos cosas distintas: el HTML se manda por
mail y funciona sin servidor; este tablero necesita Python corriendo porque
Monte Carlo, PCA y LISA no se pueden hacer en JavaScript en el navegador.

## Qué hay en la capa

El índice **no** son cinco columnas de 1 a 6: son cinco **grupos**, y cada grupo
promedia sus columnas `CF_*`.

```
criticidad = Σ_grupo ( peso_grupo × promedio(CF de ese grupo) )
```

| Grupo | Peso | Columnas |
|---|---|---|
| Economico | 30 % | `CF_Diametro`, `CF_Profundidad`, `CF_Ubicacion` |
| Social | 30 % | `CF_PosicionRelativa`, `CF_Prox_SitiosInteres`, **`CF_Ubicacion`** |
| Medioambiental | 15 % | `CF_Prox_MedioAmbiental` |
| Valorizacion | 25 % | `CF_Antiguedad`, `CF_Material`, `CF_Obstrucciones` |
| Arboles | 0 % | `CF_Arboles` |

La configuración **se deduce de la capa**, no se asume: `GRUPOS_DEFAULT` incluye
`CF_Acceso_Mantenimiento`, que esta capa no trae, y el denominador del promedio
depende de cuántas columnas participen de verdad. El encabezado del tablero
muestra qué proporción de tramos reproduce la columna `criticidad` guardada
(99,8 % en la capa actual). Si ese número baja del 99 %, el aviso se pone en rojo:
significa que el tablero está analizando un índice distinto del que se entregó.

## Las cuatro pestañas

### 🗺️ Mapa

El mapa de siempre, con lo que le faltaba.

- **Tooltip de un solo tramo.** Antes se apilaban todos los que caían bajo el
  cursor, justo donde hay más colectores juntos.
- **Panel de detalle**: al hacer clic, las barras muestran los cinco criterios de
  ese tramo contra la **mediana de la red**. Contra la mediana y no contra la
  escala 1–6, porque un 4 en un criterio donde todos sacan 4 no explica nada.
- **Escala de color**: cortes fijos o quintiles.
  - *Fijos* — comparables entre escenarios: un tramo cambia de clase sólo si
    cambia su índice.
  - *Quintiles* — la clase más alta es siempre el 20 % peor. Es un ranking, no
    una medida absoluta, y es lo accionable cuando hay que elegir a quién mandar
    la cuadrilla.
- **Operador de agregación**: media aritmética, geométrica o máximo.
- **Poder discriminante** junto a los estadísticos: coeficiente de variación y
  entropía. El CV se pone en rojo por debajo de 0,20.

### 🎲 Sensibilidad

Los pesos 30/30/15/25/0 son una decisión política, no un hecho. Este tab pregunta
qué tramos son críticos **decida lo que decida** quien pondera.

Se sortean vectores de peso uniformemente del simplex (Dirichlet con α = 1) y se
mira dónde queda cada tramo en cada escenario:

| Métrica | Qué significa |
|---|---|
| `pct_medio` | percentil promedio del tramo (1 = el más crítico) |
| `pct_std` | cuánto se mueve su posición según la ponderación |
| `frec_top10` | en qué proporción de escenarios queda en el 10 % peor |

| Categoría | Regla | Cómo se lee |
|---|---|---|
| **Robusto** | `frec_top10 > 0,80` | Prioridad indiscutible. Se puede defender frente a cualquier ponderación razonable: es la inversión segura. |
| **Volátil** | `pct_std` en el decil más alto | Su prioridad depende de qué criterio se privilegie. **No es ruido**: son exactamente los tramos que hay que llevar a la mesa de decisión. |
| **Descartable** | `frec_top10 = 0` | Nunca entra al top. Sale de la discusión. |

Robusto gana sobre volátil a propósito: un tramo puede oscilar mucho y aun así no
bajar nunca del top, y esa variabilidad no cambia la decisión.

El **impacto marginal** reporta dos números por criterio, y hay que mirar los dos:
`spearman` compara el ranking completo si ese criterio se llevara todo el peso;
`top_comun` cuenta cuántos de los 100 primeros sobreviven. Un criterio puede
correlacionar alto y aun así reordenar por completo la punta, que es la parte que
se ejecuta.

El Monte Carlo **no se dispara solo**: son ~15 s sobre 60.000 tramos, y además el
análisis no depende de dónde estén los sliders, así que recalcularlo al moverlos
sería contradictorio.

### 🔬 Diagnóstico

¿El índice está bien construido? Se mira en dos niveles con el selector de arriba:
las **columnas `CF_*`**, que es donde vive el problema de construcción, y los
**grupos**, que es el nivel al que se pondera.

- **Correlación de Spearman** entre criterios. Por encima de ρ = 0,80 están
  midiendo lo mismo, y el peso que los sliders reparten entre ellos se acumula
  sobre una sola señal.
- **PCA**: scree plot, varianza acumulada y loadings. Si dos componentes explican
  más del 90 %, hay más sliders que grados de libertad.
- **Comparación de operadores**: los tres histogramas con su CV y su entropía,
  medidos con los **mismos cortes** — sobre cuantiles propios cualquier operador
  daría la entropía máxima y la comparación no diría nada.
- **Peso efectivo por columna** contra el reparto parejo.
- **Distribución de cada criterio**. Un criterio con casi todos los tramos en un
  valor no aporta información y su peso es ruido.
- **Conclusiones en prosa**, autogeneradas: el punto del tab es que no haya que
  deducirlas de un heatmap.

### 💰 Priorización

**4a · Clusters espaciales (LISA).** Operativamente no se manda una cuadrilla a un
tramo suelto, se manda a una zona.

| Cluster | Qué es | Qué hacer |
|---|---|---|
| **HH** | crítico rodeado de críticos | zona de intervención prioritaria |
| **LL** | tranquilo entre tranquilos | se puede postergar |
| **HL** | crítico aislado | caso puntual, no justifica movilizar |
| **LH** | tranquilo en zona crítica | se arregla "de paso" si ya hay obra |
| **ns** | sin patrón detectable (p ≥ 0,05) | — |

El **Moran's I global** dice si vale la pena mirar lo local: cerca de 0 la
criticidad estaría repartida al azar y agrupar en zonas no tendría sentido. Los
HH se agrupan después en zonas contiguas con n de tramos, longitud y criticidad
media.

La vecindad es **KNN (k = 8)** sobre centroides y no Queen: en una red de líneas
la contigüidad por vértice depende de que los extremos coincidan exactamente, y
estas capas vienen de digitalizaciones distintas.

**4b · Presupuesto.** Knapsack 0/1: maximizar criticidad mitigada sin pasarse.

- **Método**: greedy por ratio beneficio/costo **con relleno** (el greedy de
  manual corta en el primer ítem que no entra y deja plata sin gastar) más una
  pasada de intercambios 1-1.
- **Optimalidad**: la columna *gap* compara contra la relajación fraccionaria del
  knapsack, que es una **cota superior exacta** del óptimo calculada en forma
  cerrada. El gap reportado es una garantía, no una estimación, y el error real
  es todavía menor. Sobre los datos reales da **0,000 %**. Por eso no se usa un
  solver MILP: PuLP u OR-Tools sobre 60.000 binarias tardarían minutos u horas
  para cerrar un gap que ya sabemos nulo.
- **Costo**: si la capa trae una columna de costo se usa esa; si no, se estima
  como `longitud × $/m`. **Es una estimación paramétrica, no un presupuesto**:
  es lineal en la longitud e ignora profundidad, material, rotura de pavimento y
  desvío de tránsito, que en la práctica dominan.
- La longitud sale del **campo relevado**, no de la geometría. No son lo mismo:
  en esta capa difieren en más de un metro en 26.362 tramos, con casos de 3 km, y
  como el costo se estima por metro esa diferencia se convierte en plata.

**Cómo leer la comparación de estrategias.** Con costo estimado por longitud, el
ratio criticidad/costo es proporcional a la criticidad, así que las dos
estrategias greedy ordenan igual y compararlas no dice nada — el tablero lo avisa
cuando pasa. La comparación recién tiene contenido con costos reales.

La estrategia **por zona** puntúa peor a propósito: arrastra tramos flojos que
están en el medio de una zona crítica. Lo que el modelo no ve es la movilización
—mandar la cuadrilla a 40 tramos contiguos cuesta menos por tramo que a 40
desparramados—, así que su desventaja en la tabla está sobrestimada.

## Selección vinculada entre pestañas

Las cuatro vistas dibujan sobre el **mismo** `ColumnDataSource`, así que
seleccionar tramos en el scatter de sensibilidad los prende en el mapa, y
seleccionar en el mapa los marca en la tabla del plan de obra.

La condición es que la fila `i` sea el tramo `i` en todas partes. Por eso las
partes de un `MultiLineString` se unen en un solo glifo con un `NaN` de
separación en vez de ocupar varias filas: una vista nueva tiene que respetar ese
contrato, y si necesita un subconjunto se filtra con `CDSView`, nunca armando
otra fuente.

## Rendimiento

| Operación | Tiempo (60.726 tramos) |
|---|---|
| **Abrir el tablero, primera sesión** | ~9 s |
| **Abrir el tablero, sesiones siguientes** | ~2,5 s |
| Mover un slider de peso | ~0,08 s |
| Abrir un tab por primera vez | 0,3 – 2 s |
| Panear el mapa | ~90 ms por cuadro |
| Monte Carlo, 1000 escenarios | ~16 s |
| LISA, 999 permutaciones | ~15 s |
| Agrupamiento de zonas HH | ~20 s |

El servidor usa unos **370 MB** de RAM con todo construido. Si el tablero va
lento, el problema no es la memoria de la máquina.

### De dónde salieron esos números

Cinco cambios, todos medidos sobre la capa real (antes: 16,6 s la primera
sesión, 10,4 MB de payload, 0,74 s por slider):

1. **Tabs perezosos** (`estado.TABS_PEREZOSOS`). Construir los cuatro de entrada
   mandaba al navegador **242.904 glifos** —los 60.726 tramos cuatro veces, un
   renderer de `multi_line` por mapa— cuando en pantalla se ve uno. Ahora cada
   tab se arma la primera vez que se lo abre: 899 modelos iniciales → 142.
2. **Capa cacheada entre sesiones** (`data._CACHE_CAPA`). `bokeh serve` ejecuta
   `main.py` por CADA sesión, así que cada recarga del navegador releía los 13 MB
   del GeoPackage. `Datos` es de sólo lectura y se comparte; lo mutable vive en
   `Tablero`, que sigue siendo uno por sesión. Recargar pasó de 16,6 s a 2,5 s.
3. **Colores por mapper, no por columna.** `color_categoria` eran 60.726 copias
   de uno de cuatro strings hexadecimales: 0,67 MB de payload por capa, tres
   capas. Ahora la paleta viaja una vez en un `CategoricalColorMapper` sobre la
   columna de texto que el tooltip ya necesitaba.
4. **Los crudos salen del `ColumnDataSource`.** Sólo los usa el panel de detalle,
   que se arma en el servidor: `crudo_material` eran 60.726 copias de dos strings
   que el navegador nunca leía. Y la clave del tramo viaja como entero (buffer
   binario) en vez de como texto.
5. **Coordenadas redondeadas y vectorizadas.** Dos decimales en Web Mercator son
   centésimas de metro: −34 % de payload sin perder nada dibujable. Y armarlas
   con un `np.split` en vez de 60.000 llamadas a shapely bajó de 2,2 s a 0,7 s.

Con eso el payload inicial quedó en **4,5 MB** (era 10,4 MB).

Aparte, el tab de Diagnóstico cacheaba mal: recalculaba Spearman (1,8 s) y PCA
(0,7 s) en **cada** movimiento de slider, y ninguno de los dos depende de los
pesos. Ahora se cachean por (nivel, descuento de duplicadas), que es de lo único
que dependen.

### El backend de render: canvas, nunca WebGL

Medido en Chromium con GPU real (NVIDIA GTX 1050 Ti, verificada con
`WEBGL_debug_renderer_info` en cada corrida — en headless por defecto Chromium
cae a SwiftShader y cualquier medición de WebGL es basura). Paneando los 60.726
tramos, mediana de 40 cuadros:

| Backend | ms por cuadro | FPS |
|---|---|---|
| **canvas** | **71 ms** | ~14 |
| webgl | 2.431 ms | ~0,4 |

**Unas 27 veces más lento**, y no mejora sacando los tiles, la transparencia ni
los estilos de selección: las cuatro variantes de WebGL dieron lo mismo.

El motivo es la forma de la capa: **58.647 de los 60.726 tramos son segmentos de
dos puntos**. El backend WebGL de Bokeh arma estado por línea —unas 60.000 draw
calls— donde canvas traza paths de corrido. WebGL rinde con pocas líneas largas,
que es exactamente lo contrario de una red de colectores.

Es también por qué el visualizador HTML de siempre se movía mejor que este
tablero: nunca declaró `output_backend`, así que quedó en canvas.

| Escenario | ms por cuadro |
|---|---|
| HTML autónomo (visualizador) | 71 ms |
| `bokeh serve` con canvas | 90 ms |

Esos 19 ms de diferencia son el websocket sincronizando el rango en cada cuadro,
y son inevitables en una app servida.

### Sobre la simplificación de geometrías

Está disponible (`estado.TOLERANCIA_SIMPLIFY`) pero en esta capa **no es de donde
sale la fluidez**: los tramos promedian **2,25 vértices** y simplificar a 1 m
recorta apenas un 8 %. El cuello de botella es la cantidad de glifos, no su
complejidad.

## Riesgo (todavía no)

**Consecuencia de falla ≠ riesgo.** Todo este tablero mide consecuencia: qué tan
grave es que un tramo falle. Cuán probable es que falle es otra cosa, y priorizar
por consecuencia sola manda cuadrillas a colectores enormes recién construidos.

```
riesgo = consecuencia × probabilidad
```

`cf_pf_core/analisis/indices.py` tiene la firma de `calcular_probabilidad_falla`
documentada y sin implementar, y `riesgo()` ya escrita. Los insumos —antigüedad,
material, diámetro, obstrucciones, profundidad, pendiente— ya están en la capa de
Colectores; lo que falta no es código sino el **modelo de deterioro**: una curva
de supervivencia por material calibrada contra fallas observadas.

El `PF` que ya existe en el core sale de inspecciones PACP, así que sólo hay dato
donde pasó una cámara: cubre una fracción de la red y no sirve para priorizar
dónde nadie miró todavía.

## Estructura

```
app/dashboard/
  main.py              arma los Tabs; nada de lógica
  data.py              carga la capa, deduce los grupos, arma xs/ys, caché
  nucleo.py            Tablero: el ColumnDataSource compartido y los parámetros
  estado.py            configuración (rutas, umbrales, colores)
  tabs/                mapa · sensibilidad · diagnostico · priorizacion
  componentes/         colores · pesos · panel_detalle

cf_pf_core/analisis/   lógica pura, sin Bokeh — testeable sin levantar servidor
  indices.py           el índice como álgebra; operadores; CV y entropía
  sensibilidad.py      Monte Carlo Dirichlet
  diagnostico.py       Spearman, PCA, conclusiones en prosa
  espacial.py          Moran global, LISA, zonas de intervención
  optimizacion.py      knapsack y cota fraccionaria

scripts/precompute.py  genera el caché parquet
tests/test_analisis.py 35 tests
```

`cf_pf_core/analisis/` no importa Bokeh a propósito: el plugin de QGIS importa el
core vía `core_bridge.py` y ese entorno no puede arrastrar dependencias de
dibujo.
