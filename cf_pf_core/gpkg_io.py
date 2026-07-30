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

from cf_pf_core.claves import normalizar as normalizar_clave

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


def escribir_resultados(
    res_gdf,
    out_gpkg,
    out_layer=LAYER_SALIDA_DEFAULT,
    clave=None,
    reemplazar=False,
):
    """Escribe el GeoDataFrame de resultados en la capa de salida.

    Si la capa todavia no existe se crea tal cual. Si existe, las columnas de
    `res_gdf` se mergean por `clave` sobre lo que ya habia: asi se puede correr un
    calculo individual sin perder los anteriores. Las columnas que ya estaban se
    reemplazan por la version nueva.

    reemplazar=True escribe la capa de cero. Es lo que corresponde despues de un
    flujo completo: si quedaran columnas de una corrida anterior, serian de una
    configuracion vieja mezclada con la nueva.

    Nunca toca la capa fuente de Colectores.

    Devuelve el GeoDataFrame de salida resultante.
    """
    out_gpkg = os.path.abspath(out_gpkg)
    geom_res = res_gdf.geometry.name

    if not reemplazar and capa_existe(out_gpkg, out_layer):
        prev = gpd.read_file(out_gpkg, layer=out_layer)
        clave_uso = clave if clave in prev.columns and clave in res_gdf.columns else None
        if clave_uso is None:
            for cand in (CLAVE_DEFAULT, "ID", "id"):
                if cand in prev.columns and cand in res_gdf.columns:
                    clave_uso = cand
                    break

        if clave_uso is None:
            # Sin clave comun no hay forma de unir sin arriesgar mezclar filas.
            raise ValueError(
                f"La capa '{out_layer}' ya existe pero no comparte columna clave con "
                f"los resultados. Claves en la capa: {list(prev.columns)}."
            )

        aportadas = [c for c in res_gdf.columns if c not in (clave_uso, geom_res)]
        aporte = res_gdf[[clave_uso, *aportadas]].copy()
        aporte["__clave"] = aporte[clave_uso].map(normalizar_clave)
        aporte = aporte.drop(columns=[clave_uso])

        geom_prev = prev.geometry.name
        prev = prev.drop(columns=[c for c in aportadas if c in prev.columns])
        prev["__clave"] = prev[clave_uso].map(normalizar_clave)

        salida = prev.merge(aporte, on="__clave", how="left").drop(columns="__clave")
        salida = gpd.GeoDataFrame(salida, geometry=geom_prev, crs=prev.crs)
    else:
        salida = res_gdf

    os.makedirs(os.path.dirname(out_gpkg), exist_ok=True)
    salida.to_file(out_gpkg, layer=out_layer, driver="GPKG")
    return salida
