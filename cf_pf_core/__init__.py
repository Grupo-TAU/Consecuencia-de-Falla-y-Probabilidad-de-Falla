"""
cf_pf_core — logica compartida de Consecuencia y Probabilidad de Falla.

Objetivo: UNA sola copia de la logica de calculo, importable desde:
  - el plugin QGIS
  - los scripts standalone (scripts/run_*.py)
  - la app Streamlit (app/streamlit_app.py)

Principios:
  - Los calculos (cf_pf_core.calculos.*) son funciones PURAS sobre DataFrames:
    reciben columnas, devuelven una Serie de resultado. No hacen I/O.
  - El I/O (cf_pf_core.gpkg_io) LEE la capa de Colectores (solo lectura) y
    ESCRIBE los resultados en una capa aparte 'DatosConsecuenciaDeFalla',
    unida por ELEMRED. Nunca sobreescribe la capa fuente.
"""

__version__ = "0.1.0"
