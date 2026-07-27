"""
CF Diametro — clasifica colectores por diametro usando rangos configurables.

Logica portada IDENTICA a scripts/run_cf_diametro.py (misma _to_mm, _parse_rango,
_clasificar) para garantizar resultados equivalentes. La diferencia es que aca es
una funcion pura sobre un DataFrame (sin sqlite ni I/O).
"""
import re

import pandas as pd

CAMPO_DIAMETRO_DEFAULT = "DIAMETRO"
CAMPO_SALIDA_DEFAULT = "CF_Diametro"
RANGO_DEFAULT = "200=1; 300=2; 400=3; 500=4; 800=5"


def _to_mm(value):
    """Extrae un diametro en mm de un valor que puede venir como numero o texto
    con separadores de miles/decimales mezclados."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    m = re.search(r"[-+]?\d[\d.,]*", text)
    if not m:
        return None
    t = m.group(0)
    if "." in t and "," in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        l, r = t.split(",", 1)
        t = l + r if len(r) == 3 else l + "." + r
    try:
        return float(t)
    except ValueError:
        return None


def parse_rango(texto):
    """'200=1; 300=2; ...' -> [(200.0, 1), (300.0, 2), ...] ordenado por limite."""
    limites = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        v, _, c = par.partition("=")
        try:
            lim = float(v.strip().replace(",", "."))
            cls = int(c.strip())
            if lim > 0:
                limites.append((lim, cls))
        except ValueError:
            continue
    return sorted(limites, key=lambda x: x[0]) or parse_rango(RANGO_DEFAULT)


def _clasificar(diam, limites):
    if diam is None:
        return 0
    for lim, cls in limites:
        if diam < lim:
            return cls
    return limites[-1][1] + 1


def calcular(df, campo_diam=CAMPO_DIAMETRO_DEFAULT, rango=RANGO_DEFAULT):
    """Devuelve una Serie int con la clasificacion CF por diametro, alineada al indice de df.

    df: DataFrame que contiene la columna `campo_diam`.
    """
    if campo_diam not in df.columns:
        raise KeyError(
            f"Campo diametro '{campo_diam}' no esta en la capa. Columnas: {list(df.columns)}"
        )
    limites = parse_rango(rango)
    return df[campo_diam].map(lambda v: _clasificar(_to_mm(v), limites)).astype("int64")
