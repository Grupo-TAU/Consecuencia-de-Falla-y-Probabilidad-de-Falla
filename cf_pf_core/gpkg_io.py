"""
I/O de GeoPackage para cf_pf_core.

Regla de oro: la capa de Colectores (fuente) se LEE, nunca se escribe.
Todos los resultados calculados se acumulan en una capa APARTE
'DatosConsecuenciaDeFalla', unida a Colectores por la clave ELEMRED.
Asi los datos de la intendencia/campo quedan intactos y la capa de resultados
se puede regenerar cuando se quiera.
"""
import os
import sqlite3

import geopandas as gpd

LAYER_SALIDA_DEFAULT = "DatosConsecuenciaDeFalla"
CLAVE_DEFAULT = "ELEMRED"


def listar_capas(gpkg_path):
    """Lista las capas de features de un GeoPackage (via el catalogo gpkg_contents).

    Devuelve [] si el archivo no existe todavia o no es un GeoPackage valido.
    """
    if not os.path.isfile(gpkg_path):
        return []
    con = sqlite3.connect(gpkg_path)
    try:
        return [
            r[0]
            for r in con.execute(
                "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
            ).fetchall()
        ]
    except sqlite3.OperationalError:
        # Archivo que existe pero no tiene estructura de GeoPackage.
        return []
    finally:
        con.close()


def resolver_capa(gpkg_path, layer=None):
    """Devuelve el nombre de capa a usar: la indicada, o la unica si hay una sola."""
    capas = listar_capas(gpkg_path)
    if not capas:
        raise ValueError(f"El GeoPackage '{gpkg_path}' no tiene capas de features.")
    if layer:
        if layer not in capas:
            raise ValueError(f"La capa '{layer}' no existe. Disponibles: {capas}")
        return layer
    if len(capas) == 1:
        return capas[0]
    raise ValueError(f"Hay varias capas {capas}. Especifica cual usar.")


def leer_capa(gpkg_path, layer=None):
    """Lee una capa como GeoDataFrame (autodetecta si hay una sola)."""
    layer = resolver_capa(gpkg_path, layer)
    return gpd.read_file(gpkg_path, layer=layer)


def capa_existe(gpkg_path, layer):
    return layer in listar_capas(gpkg_path)


def escribir_resultado(
    colectores_gdf,
    serie_resultado,
    nombre_campo,
    out_gpkg,
    out_layer=LAYER_SALIDA_DEFAULT,
    clave=CLAVE_DEFAULT,
):
    """Acumula una columna de resultado en la capa de salida.

    - colectores_gdf: GeoDataFrame fuente (aporta clave + geometria). No se modifica.
    - serie_resultado: Serie alineada al indice de colectores_gdf con el valor calculado.
    - nombre_campo: nombre de la columna de resultado en la capa de salida.
    - out_gpkg / out_layer: destino. Si la capa ya existe, se actualiza la columna
      (merge por clave); si no, se crea con clave + geometria + la columna.

    Devuelve el GeoDataFrame de salida resultante.
    """
    if clave not in colectores_gdf.columns:
        raise KeyError(f"La clave '{clave}' no esta en Colectores.")

    geom_col = colectores_gdf.geometry.name
    base = colectores_gdf[[clave, geom_col]].copy()
    base[nombre_campo] = serie_resultado.values

    if capa_existe(out_gpkg, out_layer):
        prev = gpd.read_file(out_gpkg, layer=out_layer)
        # Quitar la columna si ya existia (para reemplazarla) y volver a unir por clave.
        if nombre_campo in prev.columns:
            prev = prev.drop(columns=[nombre_campo])
        salida = prev.merge(
            base[[clave, nombre_campo]], on=clave, how="left"
        )
        salida = gpd.GeoDataFrame(salida, geometry=prev.geometry.name, crs=prev.crs)
    else:
        salida = base

    out_dir = os.path.dirname(os.path.abspath(out_gpkg))
    os.makedirs(out_dir, exist_ok=True)
    salida.to_file(out_gpkg, layer=out_layer, driver="GPKG")
    return salida
