"""
Criticidad del Tramo — combina los campos CF en un puntaje ponderado 1..6.

Configurable por GRUPOS: cada grupo tiene un peso y una lista de parametros (columnas
CF). El puntaje de un grupo es (suma de sus CF) / (cantidad_params * escala), y la
criticidad es sum(peso_grupo * puntaje_grupo) * escala.

El default reproduce EXACTO la logica de scripts/run_criticidad.py:
    Economico      (30%): CF_Diametro + CF_Profundidad + CF_Acceso_Mantenimiento + CF_Ubicacion
    Social         (30%): CF_PosicionRelativa + CF_Prox_SitiosInteres + CF_Ubicacion
    Medioambiental (15%): CF_Prox_MedioAmbiental
    Valorizacion   (25%): CF_Antiguedad + CF_Material + CF_Obstrucciones
    Criticidad = SUMA(peso * puntaje_grupo) * 6
"""
import pandas as pd

CAMPO_SALIDA_DEFAULT = "criticidad"
ESCALA = 6.0

# Grupo -> {peso, params}. CF_Ubicacion participa en Economico y Social (a proposito).
GRUPOS_DEFAULT = {
    "Economico": {
        "peso": 0.30,
        "params": ["CF_Diametro", "CF_Profundidad", "CF_Acceso_Mantenimiento", "CF_Ubicacion"],
    },
    "Social": {
        "peso": 0.30,
        "params": ["CF_PosicionRelativa", "CF_Prox_SitiosInteres", "CF_Ubicacion"],
    },
    "Medioambiental": {
        "peso": 0.15,
        "params": ["CF_Prox_MedioAmbiental"],
    },
    "Valorizacion": {
        "peso": 0.25,
        "params": ["CF_Antiguedad", "CF_Material", "CF_Obstrucciones"],
    },
}

# Nombres alternativos aceptados para algunas columnas.
ALIASES = {
    "CF_Prox_SitiosInteres": ["CF_Prox_SitiosInteres", "CF_Prox_ClienteImportante"],
    "CF_Acceso_Mantenimiento": ["CF_Acceso_Mantenimiento", "CF_AccesoMantenimiento"],
}

# Todos los parametros posibles (para que la app arme la lista de opciones).
PARAMS_DISPONIBLES = [
    "CF_Diametro", "CF_Profundidad", "CF_Acceso_Mantenimiento", "CF_Ubicacion",
    "CF_PosicionRelativa", "CF_Prox_SitiosInteres", "CF_Prox_MedioAmbiental",
    "CF_Antiguedad", "CF_Material", "CF_Obstrucciones",
]


def _cf(v):
    """Acota el valor CF al rango [1, 6]; NULL/invalidos -> 1."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 1.0
    try:
        return max(1.0, min(6.0, float(v)))
    except (TypeError, ValueError):
        return 1.0


def _resolver(columnas, nombre):
    lower = {c.lower(): c for c in columnas}
    for cand in ALIASES.get(nombre, [nombre]):
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def resolver_columnas(columnas, grupos):
    """Devuelve (mapa param->columna_real, faltantes)."""
    mapa, faltantes = {}, []
    vistos = set()
    for g in grupos.values():
        for p in g["params"]:
            if p in vistos:
                continue
            vistos.add(p)
            col = _resolver(columnas, p)
            if col:
                mapa[p] = col
            else:
                faltantes.append(p)
    return mapa, faltantes


def calcular(df, grupos=None, escala=ESCALA):
    """Devuelve una Serie float con la criticidad (redondeada a 2).

    grupos: dict {nombre: {'peso': float, 'params': [cols]}}. None = GRUPOS_DEFAULT.
    Lanza KeyError listando las columnas de parametros que falten.
    """
    grupos = grupos if grupos is not None else GRUPOS_DEFAULT
    mapa, faltantes = resolver_columnas(df.columns, grupos)
    if faltantes:
        raise KeyError(
            f"Faltan columnas para Criticidad: {faltantes}. "
            f"Calculalas primero o quitalas de los parametros. Disponibles: {list(df.columns)}"
        )

    def _fila(row):
        total = 0.0
        for g in grupos.values():
            params = g["params"]
            if not params:
                continue
            suma = sum(_cf(row[mapa[p]]) for p in params)
            total += (suma / (len(params) * escala)) * g["peso"]
        return round(total * escala, 2)

    return df.apply(_fila, axis=1).astype("float64")
