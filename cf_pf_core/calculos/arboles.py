"""
CF Arboles — clasifica los colectores por la presencia de arboles cercanos.

Es BINARIO a pedido: un tramo con al menos un arbol a 5 m es clase 6, y uno sin
ninguno es clase 1. No hay grados intermedios aunque la capa traiga la cantidad
y la distancia, asi que un tramo con 29 arboles a 0,5 m y otro con 1 arbol a
4,9 m salen iguales. Si algun dia se quiere graduar, los insumos ya estan: las
clases son parametros y alcanza con reemplazar _tiene_arbol por un rango.

El NULL significa "no hay arboles", no "no se sabe": asi viene generada la capa
(los tramos sin arbol no tienen fila en el conteo, no tienen un 0).
"""
import pandas as pd

CAMPO_NRO_DEFAULT = "nro_arbol_5m"
CAMPO_DIST_DEFAULT = "dist_arbol"
CAMPO_SALIDA_DEFAULT = "CF_Arboles"
CLASE_CON_DEFAULT = 6
CLASE_SIN_DEFAULT = 1


def _col(df, *candidatos):
    """Columna real, sin distinguir mayusculas."""
    lower = {str(c).lower(): c for c in df.columns}
    for nombre in candidatos:
        if nombre and str(nombre).lower() in lower:
            return lower[str(nombre).lower()]
    return None


def _vacio(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or v != v


def _a_float(v):
    if _vacio(v):
        return None
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def calcular(df, campo_nro=CAMPO_NRO_DEFAULT, campo_dist=CAMPO_DIST_DEFAULT,
             clase_con=CLASE_CON_DEFAULT, clase_sin=CLASE_SIN_DEFAULT):
    """Serie int con CF_Arboles, alineada al indice de df.

    Manda la cantidad de arboles: hay arbol si es un numero mayor que cero. Si esa
    columna no esta, se cae a la distancia, donde un valor cargado ya implica que
    se encontro un arbol.
    """
    c_nro = _col(df, campo_nro)
    c_dist = _col(df, campo_dist)
    if not c_nro and not c_dist:
        raise KeyError(
            f"No hay datos de arboles: se busco '{campo_nro}' y '{campo_dist}'. "
            f"Columnas de la capa: {list(df.columns)}"
        )

    def _clase(row):
        if c_nro:
            n = _a_float(row[c_nro])
            return clase_con if (n is not None and n > 0) else clase_sin
        return clase_sin if _vacio(row[c_dist]) else clase_con

    return df.apply(_clase, axis=1).astype("int64")


def resumen(df, campo_nro=CAMPO_NRO_DEFAULT, campo_dist=CAMPO_DIST_DEFAULT):
    """(con_arbol, sin_arbol) — para saber a cuantos tramos afecta antes de sumarlo
    a la criticidad."""
    serie = calcular(df, campo_nro, campo_dist, clase_con=1, clase_sin=0)
    con = int(serie.sum())
    return con, len(serie) - con
