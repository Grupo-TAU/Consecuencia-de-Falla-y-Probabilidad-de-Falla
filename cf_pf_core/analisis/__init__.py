"""
Analisis sobre los resultados de Consecuencia de Falla.

Separado de cf_pf_core.calculos a proposito: `calculos` produce los CF_* y la
criticidad —y lo importa el plugin de QGIS, que corre en un Python sin
dependencias extra—, mientras que `analisis` los interroga (sensibilidad,
diagnostico, autocorrelacion espacial, priorizacion) y para eso necesita scipy,
scikit-learn, libpysal/esda y un solver.

Ninguno de estos modulos importa Bokeh: la capa de dibujo vive en app/dashboard.
Asi los calculos se pueden testear sin levantar un servidor.
"""
