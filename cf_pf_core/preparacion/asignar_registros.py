"""
Asignar Registro Inicial y Final en Colectores.

Para cada colector busca el registro mas cercano a cada extremo de su geometria,
dentro de una tolerancia. Solo asigna donde el campo esta vacio: lo que ya vino
cargado desde la intendencia no se pisa.

Escribe sobre la capa real de Colectores.
"""
from shapely.geometry import Point
from shapely.strtree import STRtree

from cf_pf_core.preparacion import gpkg_edit as ge

CAMPO_REG_INI_DEFAULT = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT = "Registro_Final"
CAMPO_ID_REG_DEFAULT = "ID"
TOLERANCIA_DEFAULT = 0.5


def _mas_cercano(tree, ids, punto, tolerancia):
    """ID del registro mas cercano al punto dentro de la tolerancia, o None.

    Ante empate se queda con el primero en el orden de la capa, igual que la
    busqueda lineal del script original.
    """
    idxs, dists = tree.query_nearest(
        Point(punto), max_distance=tolerancia, return_distance=True
    )
    if len(idxs) == 0 or dists[0] > tolerancia:
        return None
    return ids[min(int(i) for i in idxs)]


def ejecutar(gpkg_col, gpkg_reg, layer_col=None, layer_reg=None,
             campo_reg_ini=CAMPO_REG_INI_DEFAULT,
             campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
             campo_id_reg=CAMPO_ID_REG_DEFAULT,
             tolerancia=TOLERANCIA_DEFAULT,
             log=None):
    _log = ge.hacer_log(log)
    tolerancia = float(tolerancia)

    con_col = ge.conectar(gpkg_col, escritura=True)
    try:
        tabla_col = ge.detectar_capa(con_col, layer_col, "colectores")
        cols_col = ge.columnas(con_col, tabla_col)
        geom_col = ge.columna_geometria(con_col, tabla_col)

        con_reg = con_col if ge.misma_ruta(gpkg_col, gpkg_reg) else ge.conectar(gpkg_reg)
        try:
            tabla_reg = ge.detectar_capa(con_reg, layer_reg, "registros")
            cols_reg = ge.columnas(con_reg, tabla_reg)
            geom_reg = ge.columna_geometria(con_reg, tabla_reg)

            c_id_reg = ge.buscar_campo(cols_reg, campo_id_reg, "ID", "Id")
            if not c_id_reg:
                raise ge.PreparacionError(
                    f"El campo '{campo_id_reg}' no existe en Registros.")

            # Los campos destino se crean si la capa todavia no los tiene.
            c_ini = ge.asegurar_campo(con_col, tabla_col, cols_col, campo_reg_ini, "TEXT", log)
            c_fin = ge.buscar_campo(cols_col, campo_reg_fin, "Registro_FInal")
            if not c_fin:
                c_fin = ge.asegurar_campo(con_col, tabla_col, cols_col, campo_reg_fin, "TEXT", log)

            _log(f"Colectores: {tabla_col} | Registros: {tabla_reg}")
            _log(f"Campos: {c_ini} / {c_fin} desde {c_id_reg} (tolerancia {tolerancia} m)")

            # Indice espacial de los registros.
            ids, puntos = [], []
            for rid_raw, blob in con_reg.execute(
                f'SELECT "{c_id_reg}", "{geom_reg}" FROM "{tabla_reg}"'
            ):
                rid = ge.normalizar(rid_raw)
                geom = ge.geometria_de_blob(blob)
                if not rid or geom is None or geom.is_empty or geom.geom_type != "Point":
                    continue
                ids.append(rid)
                puntos.append(geom)
            if not puntos:
                raise ge.PreparacionError("Ningun registro tiene ID y geometria de punto validos.")
            tree = STRtree(puntos)
            _log(f"Registros cargados: {len(puntos)}")

            filas = con_col.execute(
                f'SELECT fid, "{geom_col}", "{c_ini}", "{c_fin}" FROM "{tabla_col}"'
            ).fetchall()
        finally:
            if con_reg is not con_col:
                con_reg.close()

        asignados_ini = asignados_fin = 0
        with ge.sin_triggers(con_col, tabla_col):
            for fid, blob, ini_actual, fin_actual in filas:
                pt_ini, pt_fin = ge.extremos(ge.geometria_de_blob(blob))
                if pt_ini is None:
                    continue

                if not ge.normalizar(ini_actual):
                    rid = _mas_cercano(tree, ids, pt_ini, tolerancia)
                    if rid:
                        con_col.execute(
                            f'UPDATE "{tabla_col}" SET "{c_ini}"=? WHERE fid=?', (rid, fid))
                        asignados_ini += 1

                if not ge.normalizar(fin_actual):
                    rid = _mas_cercano(tree, ids, pt_fin, tolerancia)
                    if rid:
                        con_col.execute(
                            f'UPDATE "{tabla_col}" SET "{c_fin}"=? WHERE fid=?', (rid, fid))
                        asignados_fin += 1

        con_col.commit()
    finally:
        con_col.close()

    _log(f"Registro_Inicial asignados: {asignados_ini}, "
         f"Registro_Final asignados: {asignados_fin} (de {len(filas)} colectores).", "ok")
    return {"colectores": len(filas), "registros": len(ids),
            "asignados_ini": asignados_ini, "asignados_fin": asignados_fin}
