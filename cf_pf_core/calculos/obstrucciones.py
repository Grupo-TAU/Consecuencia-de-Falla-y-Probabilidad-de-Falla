"""
CF Obstrucciones — clasifica por cantidad de obstrucciones.

Logica portada IDENTICA a scripts/run_cf_obstrucciones.py.
    0 obstrucciones -> 1 (Baja) | 1 -> 3 (Media) | >=2 -> 6 (Alta) | sin dato -> 1
"""
import pandas as pd

CAMPO_OBS_DEFAULT = "Obstrucciones"
CAMPO_SALIDA_DEFAULT = "CF_Obstrucciones"


def _clasificar(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 1
    try:
        obs = int(float(valor))
    except (TypeError, ValueError):
        return 1
    if obs == 0:
        return 1
    if obs == 1:
        return 3
    return 6


def calcular(df, campo_obs=CAMPO_OBS_DEFAULT):
    """Devuelve una Serie int con la clase CF por obstrucciones."""
    if campo_obs not in df.columns:
        raise KeyError(
            f"Campo obstrucciones '{campo_obs}' no esta en la capa. Columnas: {list(df.columns)}"
        )
    return df[campo_obs].map(_clasificar).astype("int64")
