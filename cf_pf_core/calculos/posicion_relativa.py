"""
CF Posicion Relativa — suma de tramos aguas arriba (posicionRelativa) y su clase.

Logica portada IDENTICA a scripts/run_cf_posicion_relativa.py: construye la red a
partir de Registro_Inicial/Final, recorre aguas arriba con memoizacion, y en nodos
con bifurcacion elige como "principal" el tramo de mayor pendiente. Ignora tramos de
tipo AL/EB (configurable).

Diferencia con el script: opera sobre un DataFrame usando su INDICE como id de tramo
(equivalente al fid), y devuelve un DataFrame con las dos columnas de resultado.
"""
import pandas as pd

CAMPO_POS_REL_DEFAULT = "posicionRelativa"
CAMPO_POS_REL_CLAS_DEFAULT = "CF_PosicionRelativa"
CAMPO_PENDIENTE_DEFAULT = "Pendiente"
CAMPO_REG_INI_DEFAULT = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT = "Registro_Final"
CAMPO_TIPO_DEFAULT = "Inspeccion"
VALORES_CORTE_DEFAULT = "AL,EB"
RANGO_DEFAULT = "10=1; 30=2; 70=3; 120=4; 150=5"


def parse_rangos(texto):
    rangos = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par:
            continue
        v, _, c = par.partition("=")
        try:
            rangos.append((float(v.strip().replace(",", ".")), int(c.strip())))
        except ValueError:
            continue
    return sorted(rangos, key=lambda x: x[0]) if rangos else []


def _clasificar(valor, rangos):
    if valor == 0:
        return 0
    for lim, cls in rangos:
        if valor <= lim:
            return cls
    return rangos[-1][1] + 1 if rangos else 1


def _normalize(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _to_float(v):
    # NaN (como lee geopandas los NULL) debe comportarse como el None que ve el
    # script via SQL: 0.0. Sin esto, un NaN rompe el desempate por pendiente.
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _buscar(cols, candidatos):
    lower = {c.lower(): c for c in cols}
    for n in candidatos:
        if n.lower() in lower:
            return lower[n.lower()]
    return None


def calcular(
    df,
    campo_reg_ini=CAMPO_REG_INI_DEFAULT,
    campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
    campo_pendiente=CAMPO_PENDIENTE_DEFAULT,
    campo_tipo=CAMPO_TIPO_DEFAULT,
    valores_corte=VALORES_CORTE_DEFAULT,
    rango=RANGO_DEFAULT,
):
    """Devuelve un DataFrame (mismo indice que df) con columnas
    posicionRelativa (int) y CF_PosicionRelativa (int)."""
    c_ini = _buscar(df.columns, (campo_reg_ini,))
    c_fin = _buscar(df.columns, (campo_reg_fin,))
    if not c_ini:
        raise KeyError(f"Campo '{campo_reg_ini}' no encontrado. Columnas: {list(df.columns)}")
    if not c_fin:
        raise KeyError(f"Campo '{campo_reg_fin}' no encontrado. Columnas: {list(df.columns)}")
    c_pend = _buscar(df.columns, (campo_pendiente, "Slope", "slope"))
    c_tipo = _buscar(df.columns, (campo_tipo,))

    rangos = parse_rangos(rango)
    corte_set = {v.strip().upper() for v in str(valores_corte).split(",") if v.strip()}

    start_node, end_node, pendiente, insp_val = {}, {}, {}, {}
    for fid, row in df.iterrows():
        start_node[fid] = _normalize(row[c_ini])
        end_node[fid] = _normalize(row[c_fin])
        pendiente[fid] = abs(_to_float(row[c_pend])) if c_pend else 0.0
        insp_val[fid] = (_normalize(row[c_tipo]).upper() if c_tipo else "")

    corte_fids = {fid for fid, v in insp_val.items() if v in corte_set}

    end_to_segs, start_to_segs = {}, {}
    for fid in start_node:
        n_ini, n_fin = start_node[fid], end_node[fid]
        if n_ini:
            start_to_segs.setdefault(n_ini, []).append(fid)
        if n_fin:
            end_to_segs.setdefault(n_fin, []).append(fid)

    incoming_by_seg, outgoing_same = {}, {}
    for fid in start_node:
        n_ini = start_node[fid]
        if not n_ini:
            incoming_by_seg[fid] = []
            outgoing_same[fid] = [fid]
        else:
            incoming_by_seg[fid] = [s for s in end_to_segs.get(n_ini, []) if s != fid]
            outgoing_same[fid] = list(start_to_segs.get(n_ini, [fid]))

    memo = {}

    def _calc(fid, stack):
        if fid in memo:
            return memo[fid]
        if fid in corte_fids:
            memo[fid] = 0
            return 0
        if fid in stack:
            return 1
        stack.add(fid)
        inc = incoming_by_seg.get(fid, [])
        if not inc:
            valor = 1
        else:
            inc_sum = sum(_calc(p, stack) for p in inc)
            out = outgoing_same.get(fid, [])
            if len(out) <= 1:
                valor = inc_sum + 1
            else:
                ordenados = sorted(out, key=lambda s: (-pendiente.get(s, 0.0), s))
                valor = inc_sum + 1 if fid == ordenados[0] else 1
        stack.discard(fid)
        memo[fid] = int(valor)
        return memo[fid]

    pos_rel, pos_clas = {}, {}
    for fid in start_node:
        ni, nf = start_node[fid], end_node[fid]
        val = 0 if (not ni and not nf) else _calc(fid, set())
        pos_rel[fid] = val
        pos_clas[fid] = _clasificar(val, rangos)

    return pd.DataFrame(
        {
            CAMPO_POS_REL_DEFAULT: pd.Series(pos_rel, dtype="int64"),
            CAMPO_POS_REL_CLAS_DEFAULT: pd.Series(pos_clas, dtype="int64"),
        }
    ).reindex(df.index)
