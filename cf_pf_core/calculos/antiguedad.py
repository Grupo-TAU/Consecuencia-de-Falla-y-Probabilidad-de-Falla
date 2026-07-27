"""
CF Antiguedad — clasifica colectores por antiguedad (anos) en tramos configurables.

Logica portada IDENTICA a scripts/run_cf_antiguedad.py. Funcion pura sobre un DataFrame.
Clasificacion por defecto:
    0-10 -> 1 | 11-20 -> 2 | 21-30 -> 3 | 31-50 -> 4 | >50 -> 6 | sin dato -> 0
"""
import re

import pandas as pd

CAMPO_EDAD_DEFAULT = "Antiguedad"
CAMPO_SALIDA_DEFAULT = "CF_Antiguedad"
LIMITES_DEFAULT = [10, 20, 30, 50]
CLASES_DEFAULT = [1, 2, 3, 4, 6]


def _to_float_or_none(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_enteros(texto, defaults):
    """Extrae la lista de enteros de un texto ('10,20,30' -> [10,20,30])."""
    if not texto or not str(texto).strip():
        return list(defaults)
    numeros = re.findall(r"\d+", str(texto))
    if not numeros:
        return list(defaults)
    return [int(n) for n in numeros]


def _clasificar(edad, limites, clases):
    for limite, clase in zip(limites, clases):
        if edad <= limite:
            return clase
    return clases[-1]


def calcular(df, campo_edad=CAMPO_EDAD_DEFAULT, limites=None, clases=None):
    """Devuelve una Serie int con la clase CF por antiguedad. Sin dato -> 0."""
    limites = LIMITES_DEFAULT if limites is None else limites
    clases = CLASES_DEFAULT if clases is None else clases
    if len(clases) != len(limites) + 1:
        raise ValueError(
            f"La cantidad de clases ({len(clases)}) debe ser uno mas que la de "
            f"limites ({len(limites)})."
        )
    if campo_edad not in df.columns:
        raise KeyError(
            f"Campo antiguedad '{campo_edad}' no esta en la capa. Columnas: {list(df.columns)}"
        )

    def _cls(v):
        edad = _to_float_or_none(v)
        return _clasificar(edad, limites, clases) if edad is not None else 0

    return df[campo_edad].map(_cls).astype("int64")
