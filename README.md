# Consecuencia y Probabilidad de Falla

Herramientas para calcular la **Consecuencia de Falla** de colectores de
saneamiento y analizar los resultados. Tres piezas que comparten el mismo núcleo
(`cf_pf_core`):

| Pieza | Qué es | Cómo se corre |
|---|---|---|
| **Plugin de QGIS** | los cálculos como algoritmos de Processing | `Plugin_CF_Y_PF/` — se empaqueta con `scripts/deploy_plugin.py` |
| **App Streamlit** | preparación de datos, cálculo del flujo y export del visualizador HTML | `streamlit run app/streamlit_app.py` |
| **Tablero Bokeh** | análisis: sensibilidad de pesos, diagnóstico del índice y plan de obra | `bokeh serve app/dashboard --show` |

```bash
pip install -r app/requirements.txt
pytest tests/
```

## El tablero de análisis

Cuatro pestañas sobre la capa `DatosConsecuenciaDeFalla`: **Mapa**,
**Sensibilidad de pesos**, **Diagnóstico del índice** y **Priorización con
presupuesto**.

```bash
python scripts/precompute.py        # cachea Monte Carlo y LISA (opcional)
bokeh serve app/dashboard --show
```

📖 **[Documentación completa del tablero →](app/dashboard/README.md)** — qué hace
cada tab, qué significa cada métrica y cómo interpretar los resultados.

No reemplaza al visualizador HTML autónomo (`cf_pf_core/visualizador.py`), que
sigue generándose desde la app Streamlit y funciona sin servidor.

## Estructura

```
cf_pf_core/            núcleo compartido
  calculos/            los CF_* y la criticidad (lo que escribe la capa)
  analisis/            sensibilidad, diagnóstico, LISA, optimización
  preparacion/         pasos que modifican las capas fuente
  flujo.py             orquestador
  visualizador.py      generador del HTML autónomo
app/
  streamlit_app.py     app de preparación y cálculo
  dashboard/           tablero Bokeh de análisis
Plugin_CF_Y_PF/        plugin de QGIS
scripts/               CLI de cada paso, empaquetado y precómputo
tests/                 146 tests
```
