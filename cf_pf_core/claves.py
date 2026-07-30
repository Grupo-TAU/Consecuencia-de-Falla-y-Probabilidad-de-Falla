"""
Normalizacion de la clave de join (ELEMRED / ID).

Vive aparte porque la usan tanto el orquestador (para reenganchar resultados ya
calculados) como el I/O (para unir con la capa de salida), y ninguno de los dos
deberia depender del otro.
"""


def normalizar(v):
    """Clave de join como texto estable.

    geopandas lee una columna de enteros que tenga algun NULL como float, asi que
    el mismo ELEMRED puede llegar como 123 o como 123.0 segun de que capa venga.
    Sin esto el merge entre capas falla en silencio y deja todo en NaN.
    """
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        if v.is_integer():
            return str(int(v))
    return str(v).strip()
