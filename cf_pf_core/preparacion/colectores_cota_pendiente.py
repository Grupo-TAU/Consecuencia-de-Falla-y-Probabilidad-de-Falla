"""
Completar cotas de zampeado y recalcular la Pendiente en Colectores.

Pasos:
  1. Copia la Cota_Zampeado_Calculada de cada Registro hacia la cota inicial /
     final del colector que lo tiene asignado (solo si la del colector esta
     vacia o en 0).
  2. Si la cota final se acaba de copiar y el colector tiene Prof_Salto, la
     corrige por el salto: cota_fin += (Prof_Inspeccionada_registro - Prof_Salto).
  3. Recalcula Pendiente = ((cota_ini - cota_fin) / Longitud) * 100.

Requisito previo: correr 'asignar_registros' y 'cota_zampeado'.

Sobre la Longitud: este paso NO la escribe. El valor de `Longitud` viene medido
por la intendencia y es el bueno; la version vieja lo pisaba con la longitud de
la geometria en cada corrida. Aca se usa tal cual, y solo si falta o vale 0 se
cae a la longitud geometrica — en memoria, para poder calcular la pendiente.

Escribe sobre la capa real de Colectores.
"""
from cf_pf_core.preparacion import gpkg_edit as ge

# Colectores
CAMPO_LONGITUD_DEFAULT = "Longitud"
CAMPO_REG_INI_DEFAULT = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT = "Registro_Final"
CAMPO_COTA_INI_DEFAULT = "Registro_Inicial_Cota_Zampeado"
CAMPO_COTA_FIN_DEFAULT = "Registro_Final_Cota_Zampeado"
CAMPO_PENDIENTE_DEFAULT = "Pendiente"
CAMPO_PROF_SALTO_DEFAULT = "Prof_Salto"
# Registros
CAMPO_ID_REG_DEFAULT = "ID"
CAMPO_COTA_ZAMP_DEFAULT = "Cota_Zampeado_Calculada"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"

DECIMALES_PENDIENTE = 6


def _sel(col):
    return f'"{col}"' if col else "NULL"


def ejecutar(gpkg_col, gpkg_reg=None, layer_col=None, layer_reg=None,
             campo_longitud=CAMPO_LONGITUD_DEFAULT,
             campo_reg_ini=CAMPO_REG_INI_DEFAULT,
             campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
             campo_cota_ini=CAMPO_COTA_INI_DEFAULT,
             campo_cota_fin=CAMPO_COTA_FIN_DEFAULT,
             campo_pendiente=CAMPO_PENDIENTE_DEFAULT,
             campo_prof_salto=CAMPO_PROF_SALTO_DEFAULT,
             campo_id_reg=CAMPO_ID_REG_DEFAULT,
             campo_cota_zamp=CAMPO_COTA_ZAMP_DEFAULT,
             campo_prof_inspec=CAMPO_PROF_INSPEC_DEFAULT,
             log=None):
    _log = ge.hacer_log(log)

    con_col = ge.conectar(gpkg_col, escritura=True)
    try:
        tabla_col = ge.detectar_capa(con_col, layer_col, "colectores")
        cols_col = ge.columnas(con_col, tabla_col)
        geom_col = ge.columna_geometria(con_col, tabla_col)

        copiar_cotas = bool(gpkg_reg)

        # Longitud: solo lectura. Si la capa no la tiene, se usa la geometria.
        c_long = ge.buscar_campo(cols_col, campo_longitud)
        if not c_long:
            _log(f"'{campo_longitud}' no existe en Colectores: se usara la longitud "
                 "de la geometria para la pendiente (no se escribe).", "warn")

        c_pend = ge.buscar_campo(cols_col, campo_pendiente, "Slope", "slope")
        if not c_pend:
            c_pend = ge.asegurar_campo(con_col, tabla_col, cols_col, campo_pendiente, "REAL", log)

        c_ci = ge.buscar_campo(cols_col, campo_cota_ini)
        c_cf = ge.buscar_campo(cols_col, campo_cota_fin)
        c_ini = ge.buscar_campo(cols_col, campo_reg_ini)
        c_fin = ge.buscar_campo(cols_col, campo_reg_fin, "Registro_FInal")
        c_salto = ge.buscar_campo(cols_col, campo_prof_salto) if campo_prof_salto else None

        if copiar_cotas:
            for nombre, actual in ((campo_reg_ini, c_ini), (campo_reg_fin, c_fin)):
                if not actual:
                    raise ge.PreparacionError(
                        f"El campo '{nombre}' no existe en Colectores. "
                        "Corre primero 'Asignar Registro Inicial y Final'.")
            c_ci = ge.asegurar_campo(con_col, tabla_col, cols_col, campo_cota_ini, "REAL", log)
            c_cf = ge.asegurar_campo(con_col, tabla_col, cols_col, campo_cota_fin, "REAL", log)
        else:
            _log("No se indico la capa de Registros: se omite el copiado de cotas; "
                 "la pendiente se recalcula con las cotas que ya tenga la capa.", "warn")

        if campo_prof_salto and not c_salto:
            _log(f"'{campo_prof_salto}' no existe en Colectores: no se aplica el "
                 "ajuste por salto.", "warn")

        _log(f"Colectores: {tabla_col} | longitud={c_long or '(geometria)'} "
             f"pendiente={c_pend} cotas={c_ci or '-'}/{c_cf or '-'} "
             f"salto={c_salto or '-'}")

        # ── Lookup de cotas y profundidades desde Registros ───────────────────
        mapa_cota, mapa_prof = {}, {}
        if copiar_cotas:
            con_reg = ge.conectar(gpkg_reg)
            try:
                tabla_reg = ge.detectar_capa(con_reg, layer_reg, "registros")
                cols_reg = ge.columnas(con_reg, tabla_reg)
                c_id_reg = ge.buscar_campo(cols_reg, campo_id_reg, "ID", "Id")
                c_cz_reg = ge.buscar_campo(cols_reg, campo_cota_zamp)
                c_pi_reg = ge.buscar_campo(cols_reg, campo_prof_inspec)
                if not c_id_reg or not c_cz_reg:
                    raise ge.PreparacionError(
                        f"Faltan '{campo_id_reg}' o '{campo_cota_zamp}' en Registros. "
                        "Corre primero 'Actualizar Cota Zampeado'.")
                for rid_raw, cota_raw, prof_raw in con_reg.execute(
                    f'SELECT "{c_id_reg}", "{c_cz_reg}", {_sel(c_pi_reg)} FROM "{tabla_reg}"'
                ):
                    rid = ge.normalizar(rid_raw)
                    if not rid:
                        continue
                    cota = ge.a_float(cota_raw)
                    if cota is not None:
                        mapa_cota.setdefault(rid, cota)
                    prof = ge.a_float(prof_raw)
                    if prof is not None:
                        mapa_prof.setdefault(rid, prof)
            finally:
                con_reg.close()
            _log(f"Registros con cota de zampeado: {len(mapa_cota)}")

        filas = con_col.execute(
            f'SELECT fid, "{geom_col}", {_sel(c_long)}, {_sel(c_ini)}, {_sel(c_fin)}, '
            f'{_sel(c_ci)}, {_sel(c_cf)}, "{c_pend}", {_sel(c_salto)} FROM "{tabla_col}"'
        ).fetchall()

        actualizados = 0
        sin_longitud = 0
        with ge.sin_triggers(con_col, tabla_col):
            for (fid, blob, long_act, reg_ini, reg_fin,
                 cota_ini_act, cota_fin_act, pend_act, salto_act) in filas:
                cambios = {}

                # Longitud de referencia: la de la capa; si no hay, la geometrica.
                longitud = ge.a_float(long_act)
                if longitud is None or longitud == 0:
                    geom = ge.geometria_de_blob(blob)
                    longitud = round(geom.length, 2) if geom is not None else None
                    sin_longitud += 1

                ci_val = ge.a_float(cota_ini_act)
                cf_val = ge.a_float(cota_fin_act)

                # ── Copiado de cotas desde los registros asignados ────────────
                if copiar_cotas:
                    if ge.es_vacio(cota_ini_act) or ci_val == 0:
                        nueva = mapa_cota.get(ge.normalizar(reg_ini))
                        if nueva is not None:
                            cambios[c_ci] = ci_val = nueva

                    if ge.es_vacio(cota_fin_act) or cf_val == 0:
                        nueva = mapa_cota.get(ge.normalizar(reg_fin))
                        if nueva is not None:
                            # Ajuste por salto: la cota del registro esta en su fondo,
                            # el colector llega mas arriba si hay salto.
                            prof_salto = ge.a_float(salto_act) if c_salto else None
                            prof_reg = mapa_prof.get(ge.normalizar(reg_fin))
                            if prof_salto is not None and prof_reg is not None:
                                nueva = round(nueva + (prof_reg - prof_salto), 2)
                            cambios[c_cf] = cf_val = nueva

                # ── Pendiente ────────────────────────────────────────────────
                if (ci_val is not None and cf_val is not None
                        and longitud is not None and abs(longitud) > 1e-12):
                    pend_calc = 0.0 if (ci_val == 0 or cf_val == 0) else round(
                        ((ci_val - cf_val) / longitud) * 100.0, DECIMALES_PENDIENTE)
                    pa = ge.a_float(pend_act)
                    if pa is None or round(pa, DECIMALES_PENDIENTE) != pend_calc:
                        cambios[c_pend] = pend_calc

                if cambios:
                    sets = ", ".join(f'"{k}"=?' for k in cambios)
                    con_col.execute(
                        f'UPDATE "{tabla_col}" SET {sets} WHERE fid=?',
                        [*cambios.values(), fid])
                    actualizados += 1

        con_col.commit()
    finally:
        con_col.close()

    if sin_longitud:
        _log(f"{sin_longitud} colectores sin Longitud cargada: se uso la longitud "
             "de la geometria solo para la pendiente.", "warn")
    _log(f"Colectores actualizados: {actualizados}/{len(filas)}.", "ok")
    return {"colectores": len(filas), "actualizados": actualizados,
            "sin_longitud": sin_longitud, "registros_con_cota": len(mapa_cota)}
