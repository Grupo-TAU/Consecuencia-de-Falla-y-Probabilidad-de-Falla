"""
PF Probabilidad de Falla — deriva PF desde el campo PACP_Clasificacion.

Logica portada IDENTICA a scripts/run_pf_probabilidad_falla.py.
    Vacio/NULL           -> 0
    2do char es letra    -> primer_digito + 1     (ej: "5B" -> 6.0)
    2do char es digito   -> primeros dos digitos / 10  (ej: "3222" -> 3.2)
    "0000"               -> 1.0
"""
import pandas as pd

CAMPO_PF_DEFAULT = "PF"


def detectar_campo_pacp(columnas):
    """Autodetecta la columna PACP (primero la que tenga 'pacp' y 'clasif')."""
    for c in columnas:
        if "pacp" in c.lower() and "clasif" in c.lower():
            return c
    for c in columnas:
        if "pacp" in c.lower():
            return c
    return None


def _calcular_pf(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0
    texto = str(valor).strip()
    if not texto or len(texto) < 2:
        return 0
    c1, c2 = texto[0], texto[1]
    if c1.isdigit() and c2.isalpha():
        return float(int(c1)) + 1.0
    if c1.isdigit() and c2.isdigit():
        v = int(c1 + c2) / 10.0
        return v if v > 0 else 1.0
    return 0


def calcular(df, campo_pacp=None):
    """Devuelve una Serie float con la PF. Si campo_pacp es None, autodetecta."""
    campo = campo_pacp or detectar_campo_pacp(list(df.columns))
    if not campo or campo not in df.columns:
        raise KeyError(
            f"No se encontro campo PACP_Clasificacion. Columnas: {list(df.columns)}"
        )
    return df[campo].map(_calcular_pf).astype("float64")
