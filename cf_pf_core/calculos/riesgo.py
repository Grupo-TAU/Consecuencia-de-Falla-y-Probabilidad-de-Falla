"""
Riesgo — Riesgo = Criticidad x PF. NULL o 0 se tratan como 1.

Logica portada IDENTICA a scripts/run_riesgo_calculo.py.
"""
import pandas as pd

CAMPO_SALIDA_DEFAULT = "Riesgo"
CAMPO_CRITICIDAD_DEFAULT = "criticidad"
CAMPO_PF_DEFAULT = "PF"


def _float(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _calcular(criticidad, pf):
    cf = _float(criticidad)
    pf_val = _float(pf)
    if cf is None and pf_val is None:
        return None
    cf = cf if (cf and cf != 0) else 1.0
    pf_val = pf_val if (pf_val and pf_val != 0) else 1.0
    return round(cf * pf_val, 2)


def _buscar(cols, candidatos):
    lower = {c.lower(): c for c in cols}
    for n in candidatos:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def calcular(df, campo_criticidad=CAMPO_CRITICIDAD_DEFAULT, campo_pf=CAMPO_PF_DEFAULT):
    """Devuelve una Serie con el Riesgo (float, o None donde ambos insumos faltan)."""
    c_ct = _buscar(df.columns, (campo_criticidad, "Criticidad", "CT"))
    c_pf = _buscar(df.columns, (campo_pf, "pf"))
    if not c_ct:
        raise KeyError(f"Campo criticidad no encontrado. Columnas: {list(df.columns)}")
    if not c_pf:
        raise KeyError(f"Campo PF no encontrado. Columnas: {list(df.columns)}")
    return df.apply(lambda r: _calcular(r[c_ct], r[c_pf]), axis=1)
