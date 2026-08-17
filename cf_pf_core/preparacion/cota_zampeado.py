"""
Actualizar Cota de Zampeado en Registros.

Dos mecanicas, que pueden correr juntas:
  1. Cota_Zampeado = Cota_Tapa_Inspeccionada - Profundidad_Inspeccionada
  2. Copia ZARRIBA del colector hacia el registro que tiene asignado como inicial,
     y de paso deduce la Profundidad_Inspeccionada de ese registro.

La mecanica 1 tiene prioridad: la 2 solo completa lo que la 1 no pudo. En ambas
se escribe unicamente donde la cota esta vacia.

Escribe sobre la capa real de Registros.
"""
from cf_pf_core.preparacion import gpkg_edit as ge

CAMPO_COTA_ZAMP_DEFAULT = "Cota_Zampeado_Calculada"
CAMPO_COTA_TAPA_DEFAULT = "Cota_Tapa_Inspeccionada"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"
CAMPO_ID_REG_DEFAULT = "ID"
CAMPO_ZARRIBA_DEFAULT = "ZARRIBA"
CAMPO_REG_INI_DEFAULT = "Registro_Inicial"


def _profundidad(cota_tapa, zampeado):
    """cota de tapa - zampeado, o None si el dato no sirve.

    Devuelve None —y NO 0— cuando alguna cota falta, viene en 0 (la forma
    habitual de anotar 'sin dato' en estas capas) o el resultado da negativo
    (tapa por debajo del zampeado: error de carga o cotas en sistemas distintos).

    Escribir 0 seria peor que no escribir nada: 0 no se lee como 'no sé' sino
    como una profundidad real, y cae en la clase menos critica de CF_Profundidad.
    """
    if cota_tapa is None or zampeado is None:
        return None
    if cota_tapa == 0 or zampeado == 0:
        return None
    prof = round(cota_tapa - zampeado, 2)
    return prof if prof >= 0 else None


def ejecutar(gpkg_col, gpkg_reg, layer_col=None, layer_reg=None,
             campo_cota_zamp=CAMPO_COTA_ZAMP_DEFAULT,
             campo_cota_tapa=CAMPO_COTA_TAPA_DEFAULT,
             campo_prof_inspec=CAMPO_PROF_INSPEC_DEFAULT,
             campo_id_reg=CAMPO_ID_REG_DEFAULT,
             campo_zarriba=CAMPO_ZARRIBA_DEFAULT,
             campo_reg_ini=CAMPO_REG_INI_DEFAULT,
             log=None):
    _log = ge.hacer_log(log)

    con_reg = ge.conectar(gpkg_reg, escritura=True)
    try:
        tabla_reg = ge.detectar_capa(con_reg, layer_reg, "registros")
        cols_reg = ge.columnas(con_reg, tabla_reg)

        c_tapa = ge.buscar_campo(cols_reg, campo_cota_tapa)
        if not c_tapa:
            raise ge.PreparacionError(
                f"El campo '{campo_cota_tapa}' no existe en Registros.")

        c_prof = ge.buscar_campo(cols_reg, campo_prof_inspec)
        c_id = ge.buscar_campo(cols_reg, campo_id_reg, "ID", "Id")
        c_zamp = ge.asegurar_campo(con_reg, tabla_reg, cols_reg, campo_cota_zamp, "REAL", log)

        hay_mec1 = c_prof is not None
        hay_mec2 = bool(gpkg_col)
        if not hay_mec1:
            _log(f"Mecanica 1 omitida: no existe '{campo_prof_inspec}' en Registros.", "warn")
        if not hay_mec2:
            _log("Mecanica 2 omitida: no se indico la capa de Colectores.", "warn")
        if not hay_mec1 and not hay_mec2:
            raise ge.PreparacionError("No hay ninguna mecanica disponible para ejecutar.")
        if hay_mec2 and not c_id:
            raise ge.PreparacionError(
                f"El campo '{campo_id_reg}' no existe en Registros (lo necesita la mecanica 2).")

        _log(f"Registros: {tabla_reg} | cota={c_zamp} tapa={c_tapa} "
             f"prof={c_prof or '(ninguna)'} id={c_id or '(ninguna)'}")

        # {fid: (id, cota_tapa, cota_zamp, prof_inspec)}
        sel_id = f'"{c_id}"' if c_id else "NULL"
        sel_prof = f'"{c_prof}"' if c_prof else "NULL"
        filas = {
            fila[0]: fila[1:] for fila in con_reg.execute(
                f'SELECT fid, {sel_id}, "{c_tapa}", "{c_zamp}", {sel_prof} FROM "{tabla_reg}"')
        }

        fids_mec1 = set()
        actualizados_mec2 = 0
        sin_profundidad = 0  # cota de tapa faltante, en 0, o profundidad negativa

        with ge.sin_triggers(con_reg, tabla_reg):
            # ── Mecanica 1: Cota_Tapa - Profundidad ───────────────────────────
            if hay_mec1:
                for fid, (_rid, tapa, zamp, prof) in filas.items():
                    if not ge.es_vacio(zamp):
                        continue
                    cota_tapa = ge.a_float(tapa)
                    prof_inspec = ge.a_float(prof)
                    if cota_tapa is None or prof_inspec is None:
                        continue
                    con_reg.execute(
                        f'UPDATE "{tabla_reg}" SET "{c_zamp}"=? WHERE fid=?',
                        (round(cota_tapa - prof_inspec, 2), fid))
                    fids_mec1.add(fid)
                _log(f"Mecanica 1: {len(fids_mec1)} registros actualizados.")

            # ── Mecanica 2: ZARRIBA desde Colectores ──────────────────────────
            if hay_mec2:
                con_col = ge.conectar(gpkg_col)
                try:
                    tabla_col = ge.detectar_capa(con_col, layer_col, "colectores")
                    cols_col = ge.columnas(con_col, tabla_col)
                    c_zarr = ge.buscar_campo(cols_col, campo_zarriba)
                    c_ri = ge.buscar_campo(cols_col, campo_reg_ini)
                    if not c_zarr:
                        raise ge.PreparacionError(
                            f"El campo '{campo_zarriba}' no existe en Colectores.")
                    if not c_ri:
                        raise ge.PreparacionError(
                            f"El campo '{campo_reg_ini}' no existe en Colectores. "
                            "Corre primero 'Asignar Registro Inicial y Final'.")
                    colectores = con_col.execute(
                        f'SELECT "{c_ri}", "{c_zarr}" FROM "{tabla_col}"').fetchall()
                finally:
                    con_col.close()

                # La mecanica 2 tambien deduce la profundidad, asi que el campo
                # tiene que existir aunque la mecanica 1 se haya omitido por eso.
                c_prof_out = ge.asegurar_campo(
                    con_reg, tabla_reg, cols_reg, campo_prof_inspec, "REAL", log)

                id_a_fid = {}
                for fid, (rid, *_resto) in filas.items():
                    clave = ge.normalizar(rid)
                    if clave:
                        id_a_fid.setdefault(clave, fid)

                for reg_ini, zarriba in colectores:
                    clave = ge.normalizar(reg_ini)
                    zarr = ge.a_float(zarriba)
                    if not clave or zarr is None:
                        continue
                    fid = id_a_fid.get(clave)
                    if fid is None or fid in fids_mec1:
                        continue
                    _rid, tapa, zamp, prof_actual = filas[fid]
                    # Dos salidas independientes: la cota de zampeado y la
                    # profundidad. Cada una se completa solo si esta vacia. Antes
                    # habia un unico `continue` sobre la cota, y eso dejaba la
                    # profundidad sin escribir para siempre en las capas que ya
                    # traian la cota cargada de un trabajo anterior.
                    falta_zamp = ge.es_vacio(zamp)
                    falta_prof = ge.es_vacio(prof_actual)
                    if not falta_zamp and not falta_prof:
                        continue

                    if falta_zamp:
                        con_reg.execute(
                            f'UPDATE "{tabla_reg}" SET "{c_zamp}"=? WHERE fid=?',
                            (zarr, fid))

                    if falta_prof:
                        # La profundidad se mide contra la cota de zampeado que
                        # vale para este registro: la que ya tenia, o ZARRIBA si
                        # la acabamos de escribir.
                        zamp_uso = zarr if falta_zamp else ge.a_float(zamp)
                        prof_calc = _profundidad(ge.a_float(tapa), zamp_uso)
                        if prof_calc is not None:
                            con_reg.execute(
                                f'UPDATE "{tabla_reg}" SET "{c_prof_out}"=? WHERE fid=?',
                                (prof_calc, fid))
                        else:
                            sin_profundidad += 1
                    actualizados_mec2 += 1
                _log(f"Mecanica 2: {actualizados_mec2} registros actualizados.")
                if sin_profundidad:
                    _log(f"{sin_profundidad} registros quedaron SIN profundidad "
                         "(cota de tapa vacía, en 0, o menor que el zampeado). "
                         "Se dejan nulos a propósito: un 0 se leería como un "
                         "tramo superficial.", "warn")

        con_reg.commit()
    finally:
        con_reg.close()

    total = len(fids_mec1) + actualizados_mec2
    _log(f"Total de registros actualizados: {total} (de {len(filas)}).", "ok")
    return {"registros": len(filas), "mecanica1": len(fids_mec1),
            "mecanica2": actualizados_mec2, "total": total}
