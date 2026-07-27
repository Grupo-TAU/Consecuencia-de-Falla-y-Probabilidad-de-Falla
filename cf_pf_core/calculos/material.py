"""
CF Material — clasifica colectores por material segun un mapeo configurable.

Logica portada IDENTICA a scripts/run_cf_material.py (misma normalizacion sin
acentos + mapeo case-insensitive). Funcion pura sobre un DataFrame.
"""
import unicodedata

import pandas as pd

CAMPO_MATERIAL_DEFAULT = "Material"
CAMPO_SALIDA_DEFAULT = "CF_Material"
MAPEO_DEFAULT = (
    "PE=1; PVC=3; PEAD=3; Otro Material=3; "
    "Hormigon Armado=4; Hormigon Simple=5; Mamposteria=6"
)


def _norm(texto):
    """Normaliza a minusculas sin acentos ni espacios sobrantes."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").strip().lower()


def parse_mapeo(texto):
    """'PVC=3; Hormigon Simple=5' -> {'pvc': 3, 'hormigon simple': 5}."""
    mapeo = {}
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        clave, _, val = par.partition("=")
        try:
            mapeo[_norm(clave)] = int(val.strip())
        except ValueError:
            continue
    return mapeo or parse_mapeo(MAPEO_DEFAULT)


def calcular(df, campo_mat=CAMPO_MATERIAL_DEFAULT, mapeo=MAPEO_DEFAULT):
    """Devuelve una Serie int con la clase CF por material. Material no reconocido -> 0."""
    if campo_mat not in df.columns:
        raise KeyError(
            f"Campo material '{campo_mat}' no esta en la capa. Columnas: {list(df.columns)}"
        )
    tabla = parse_mapeo(mapeo)
    return df[campo_mat].map(lambda v: tabla.get(_norm(v), 0)).astype("int64")


def materiales_no_reconocidos(df, campo_mat=CAMPO_MATERIAL_DEFAULT, mapeo=MAPEO_DEFAULT):
    """Lista los valores de material que no matchean el mapeo (quedarian en clase 0)."""
    tabla = parse_mapeo(mapeo)
    faltantes = set()
    for v in df[campo_mat]:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        if _norm(v) not in tabla and str(v).strip():
            faltantes.add(str(v).strip())
    return sorted(faltantes)
