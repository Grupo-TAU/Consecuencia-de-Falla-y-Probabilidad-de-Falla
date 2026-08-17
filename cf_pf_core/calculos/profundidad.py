"""
CF Profundidad — clasifica colectores por la profundidad maxima de sus registros
inicial/final.

Logica portada IDENTICA a scripts/run_cf_profundidad.py:
  - Por cada registro: prof = max(PROFUNDIDAD, Profundidad_Inspeccionada).
  - Por cada colector: prof_max = max(prof_reg_inicial, prof_reg_final).
  - Clasifica por rango (default 1.5=1; 2.5=2; 3.5=3; 4.5=4; 6=5); sin dato -> NULL.
"""
import pandas as pd

CAMPO_SALIDA_DEFAULT = "CF_Profundidad"
CAMPO_REG_INI_DEFAULT = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT = "Registro_Final"
CAMPO_ID_REG_DEFAULT = "ID"
CAMPO_PROF_DEFAULT = "PROFUNDIDAD"
CAMPO_PROF_INSPEC_DEFAULT = "Profundidad_Inspeccionada"
RANGO_DEFAULT = "1.5=1; 2.5=2; 3.5=3; 4.5=4; 6=5"

# Clase que se asigna a un tramo del que no se conoce la profundidad. Es un
# SUPUESTO explicito, no un dato: 2 corresponde al tramo de 1,5 a 2,5 m, la
# profundidad tipica de un colector domiciliario. Poner None para dejarlo NULL.
CLASE_SIN_DATO_DEFAULT = 2


def _to_float(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except ValueError:
        return None


def _norm_id(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_rango(texto):
    limites = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        v, _, c = par.partition("=")
        try:
            lim = float(v.strip().replace(",", "."))
            cls = int(c.strip())
            if lim > 0:
                limites.append((lim, cls))
        except ValueError:
            continue
    return sorted(limites, key=lambda x: x[0]) if limites else []


def _clasificar(prof, limites, clase_sin_dato=CLASE_SIN_DATO_DEFAULT):
    if prof is None:
        return clase_sin_dato
    for lim, cls in limites:
        if prof < lim:
            return cls
    return limites[-1][1] + 1 if limites else None


def _col(gdf, *cands):
    lower = {c.lower(): c for c in gdf.columns}
    for n in cands:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def calcular(
    colectores_gdf,
    registros_gdf,
    campo_reg_ini=CAMPO_REG_INI_DEFAULT,
    campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
    campo_id_reg=CAMPO_ID_REG_DEFAULT,
    campo_prof=CAMPO_PROF_DEFAULT,
    campo_prof_inspec=CAMPO_PROF_INSPEC_DEFAULT,
    rango=RANGO_DEFAULT,
    clase_sin_dato=CLASE_SIN_DATO_DEFAULT,
):
    """Devuelve una Serie (indexada como colectores_gdf) con CF_Profundidad (NA sin dato)."""
    c_ini = _col(colectores_gdf, campo_reg_ini)
    c_fin = _col(colectores_gdf, campo_reg_fin)
    c_id = _col(registros_gdf, campo_id_reg, "ID", "Id")
    c_prof = _col(registros_gdf, campo_prof)
    c_prof_i = _col(registros_gdf, campo_prof_inspec)
    for nombre, val in [("Registro_Inicial", c_ini), ("Registro_Final", c_fin),
                        ("ID registros", c_id)]:
        if not val:
            raise KeyError(f"Campo '{nombre}' no encontrado.")
    # Alcanza con UNA de las dos columnas de profundidad: el calculo de mas abajo
    # ya toma el maximo de las que haya. Exigir las dos frenaba capas donde la
    # profundidad la dedujo la preparacion (que escribe solo Profundidad_Inspeccionada).
    if not c_prof and not c_prof_i:
        raise KeyError(
            f"No hay columna de profundidad en Registros: se busco '{campo_prof}' y "
            f"'{campo_prof_inspec}'. Corré el paso de preparación "
            "'Actualizar Cota Zampeado', que la deduce de la cota de tapa y ZARRIBA."
        )
    limites = parse_rango(rango)

    mapa_prof = {}
    for _, row in registros_gdf.iterrows():
        rid = _norm_id(row[c_id])
        if not rid:
            continue
        prof = _to_float(row[c_prof]) if c_prof else None
        if c_prof_i:
            prof_i = _to_float(row[c_prof_i])
            if prof_i is not None:
                prof = max(prof, prof_i) if prof is not None else prof_i
        if prof is not None:
            mapa_prof[rid] = prof

    def _cf(ini, fin):
        p_ini = mapa_prof.get(_norm_id(ini))
        p_fin = mapa_prof.get(_norm_id(fin))
        if p_ini is not None and p_fin is not None:
            prof_max = max(p_ini, p_fin)
        elif p_ini is not None:
            prof_max = p_ini
        elif p_fin is not None:
            prof_max = p_fin
        else:
            prof_max = None
        return _clasificar(prof_max, limites, clase_sin_dato)

    valores = [_cf(ini, fin) for ini, fin in zip(colectores_gdf[c_ini], colectores_gdf[c_fin])]
    return pd.Series(valores, index=colectores_gdf.index, dtype="Int64")
