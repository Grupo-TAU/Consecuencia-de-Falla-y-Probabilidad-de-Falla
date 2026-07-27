"""
Deteccion de capas de un proyecto a partir de una carpeta.

Escanea .gpkg/.shp y los asocia a los "roles" que usan los calculos
(registros, vias, sitios, cursos, construcciones, etc.) segun patrones de nombre.
Devuelve sugerencias; el usuario siempre puede corregirlas en la app.
"""
import os

# rol -> lista de patrones (substrings en minusculas) que sugieren ese rol.
PATRONES = {
    "colectores": ["colectoress", "colector", "tramo"],
    "registros": ["registross", "registro", "puntos", "vspuntos"],
    "vias": ["calles", "vias", "v_sig_vias", "via"],
    "calles": ["calles", "calle"],
    "sitios": ["clientes importantes", "clientes_importantes", "sitios", "interes"],
    "cursos": ["cursos", "curso_de_agua", "cursos_de_agua", "hidro"],
    "construcciones": ["construcciones", "construccion", "edificaciones"],
    "asentamientos": ["asentamientos", "asentamiento"],
    "padrones": ["padrones_limitado", "padrones", "padron"],
    "peatonales": ["peatonales", "peatonal"],
    "verde": ["espacios_verdes", "espacios verdes", "verde"],
}

# Roles que suelen ser buffers ya calculados: se evitan para no doble-bufferizar.
_EVITAR = ["buffer"]


def _listar_fuentes(carpeta):
    """Lista (ruta) de todos los .gpkg y .shp bajo la carpeta (recursivo)."""
    fuentes = []
    for root, _dirs, files in os.walk(carpeta):
        for f in files:
            if f.lower().endswith((".gpkg", ".shp")):
                fuentes.append(os.path.join(root, f))
    return fuentes


def detectar_capas(carpeta):
    """Devuelve {rol: ruta} con la mejor coincidencia por nombre de archivo.

    No abre los archivos: solo mira nombres. Para roles con varios candidatos,
    elige el patron mas especifico (aparece antes en la lista de patrones) y,
    a igualdad, el archivo mas grande (suele ser el mas completo).
    """
    fuentes = _listar_fuentes(carpeta)
    sugerencias = {}
    for rol, patrones in PATRONES.items():
        mejor = None
        mejor_rank = None
        for ruta in fuentes:
            nombre = os.path.basename(ruta).lower()
            if any(ev in nombre for ev in _EVITAR):
                continue
            for i, pat in enumerate(patrones):
                if pat in nombre:
                    try:
                        tam = os.path.getsize(ruta)
                    except OSError:
                        tam = 0
                    rank = (i, -tam)  # patron mas especifico primero, luego mas grande
                    if mejor_rank is None or rank < mejor_rank:
                        mejor_rank, mejor = rank, ruta
                    break
        if mejor:
            sugerencias[rol] = mejor
    return sugerencias
