"""
CF Posicion Relativa - standalone sin QGIS.
Calcula posicionRelativa (suma de tramos aguas arriba) y CF_PosicionRelativa.
Ignora tramos de tipo AL/EB (configurable).

Uso:
    python scripts\\run_cf_posicion_relativa.py --gpkg <ruta>
    python scripts\\run_cf_posicion_relativa.py --gpkg <ruta> --layer vsstramoarteaga_prueba
"""
import argparse, sqlite3, sys, os

CAMPO_POS_REL_DEFAULT      = "posicionRelativa"
CAMPO_POS_REL_CLAS_DEFAULT = "CF_PosicionRelativa"
CAMPO_PENDIENTE_DEFAULT    = "Pendiente"
CAMPO_REG_INI_DEFAULT      = "Registro_Inicial"
CAMPO_REG_FIN_DEFAULT      = "Registro_Final"
CAMPO_INSPECCION_DEFAULT   = "Inspeccion"
VALORES_CORTE_DEFAULT      = "AL,EB"
RANGO_POS_REL_DEFAULT      = "10=1; 30=2; 70=3; 120=4; 150=5"


def _detectar_capa(con, layer_name):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print("ERROR: Sin capas."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no existe. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1: return capas[0]
    print(f"Varias capas: {capas}. Usa --layer."); sys.exit(1)


def _columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _campo(cols, *nombres):
    lower = {c.lower(): c for c in cols}
    for n in nombres:
        if n.lower() in lower: return lower[n.lower()]
    return None


def _parse_rangos(texto):
    rangos = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par: continue
        v, _, c = par.partition("=")
        try:
            rangos.append((float(v.strip().replace(",", ".")), int(c.strip())))
        except ValueError: continue
    return sorted(rangos, key=lambda x: x[0]) if rangos else []


def _clasificar(valor, rangos):
    if valor == 0: return 0
    for lim, cls in rangos:
        if valor <= lim: return cls
    return rangos[-1][1] + 1 if rangos else 1


def _normalize(v):
    if v is None: return ""
    return str(v).strip()


def _to_float(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def run(gpkg_path, layer_name=None,
        campo_pos_rel=CAMPO_POS_REL_DEFAULT,
        campo_pos_rel_clas=CAMPO_POS_REL_CLAS_DEFAULT,
        campo_pendiente=CAMPO_PENDIENTE_DEFAULT,
        campo_reg_ini=CAMPO_REG_INI_DEFAULT,
        campo_reg_fin=CAMPO_REG_FIN_DEFAULT,
        campo_inspeccion=CAMPO_INSPECCION_DEFAULT,
        valores_corte_str=VALORES_CORTE_DEFAULT,
        rango_str=RANGO_POS_REL_DEFAULT):

    gpkg_path = os.path.normpath(gpkg_path)
    if not os.path.isfile(gpkg_path): print(f"ERROR: No existe '{gpkg_path}'"); sys.exit(1)
    con = sqlite3.connect(gpkg_path)
    con.execute("PRAGMA journal_mode=WAL")
    tabla = _detectar_capa(con, layer_name)
    print(f"Capa: {tabla}")
    cols = _columnas(con, tabla)

    c_pend  = _campo(cols, campo_pendiente, "Slope", "slope") or ""
    c_ini   = _campo(cols, campo_reg_ini)
    c_fin   = _campo(cols, campo_reg_fin)
    c_insp  = _campo(cols, campo_inspeccion)

    if not c_ini: print(f"ERROR: Campo '{campo_reg_ini}' no encontrado."); con.close(); sys.exit(1)
    if not c_fin: print(f"ERROR: Campo '{campo_reg_fin}' no encontrado."); con.close(); sys.exit(1)
    if not c_pend: print(f"AVISO: Campo pendiente no encontrado. Se usara 0.");

    rangos = _parse_rangos(rango_str)
    valores_corte = {v.strip().upper() for v in valores_corte_str.split(",") if v.strip()}
    print(f"  Registro_Inicial : {c_ini}")
    print(f"  Registro_Final   : {c_fin}")
    print(f"  Pendiente        : {c_pend or '(no encontrado)'}")
    print(f"  Tipo tramo       : {c_insp or '(no encontrado)'}")
    print(f"  Valores de corte : {', '.join(sorted(valores_corte))}")
    print(f"  Rangos           : {rangos}")

    for campo_out in (campo_pos_rel, campo_pos_rel_clas):
        if not _campo(cols, campo_out):
            con.execute(f'ALTER TABLE "{tabla}" ADD COLUMN "{campo_out}" INTEGER')
            cols.append(campo_out)

    # Leer todos los colectores
    sel_parts = [f'"{c_ini}"', f'"{c_fin}"']
    if c_pend: sel_parts.append(f'"{c_pend}"')
    else: sel_parts.append("0")
    if c_insp: sel_parts.append(f'"{c_insp}"')
    else: sel_parts.append("NULL")

    filas = con.execute(
        f'SELECT fid, {", ".join(sel_parts)}, "{campo_pos_rel}", "{campo_pos_rel_clas}" FROM "{tabla}"'
    ).fetchall()

    start_node  = {}  # fid -> nodo_inicio
    end_node    = {}  # fid -> nodo_fin
    pendiente   = {}  # fid -> float
    insp_val    = {}  # fid -> str upper

    for row in filas:
        fid = row[0]
        start_node[fid] = _normalize(row[1])
        end_node[fid]   = _normalize(row[2])
        pendiente[fid]  = abs(_to_float(row[3]))
        insp_val[fid]   = _normalize(row[4]).upper()

    corte_fids = {fid for fid, v in insp_val.items() if v in valores_corte}
    if corte_fids:
        print(f"  Colectores con corte ({', '.join(sorted(valores_corte))}): {len(corte_fids)}")

    # Índices de red
    end_to_segs   = {}  # nodo_fin -> [fid que llegan ahí] (incoming)
    start_to_segs = {}  # nodo_ini -> [fid que salen de ahí]
    for fid in start_node:
        n_ini = start_node[fid]
        n_fin = end_node[fid]
        if n_ini: start_to_segs.setdefault(n_ini, []).append(fid)
        if n_fin: end_to_segs.setdefault(n_fin, []).append(fid)

    # incoming_by_seg: tramos cuyo nodo_fin = mi nodo_inicio (me alimentan)
    incoming_by_seg = {}
    outgoing_same   = {}  # tramos que salen del mismo nodo_inicio que yo
    for fid in start_node:
        n_ini = start_node[fid]
        if not n_ini:
            incoming_by_seg[fid] = []
            outgoing_same[fid]   = [fid]
        else:
            incoming_by_seg[fid] = [s for s in end_to_segs.get(n_ini, []) if s != fid]
            outgoing_same[fid]   = list(start_to_segs.get(n_ini, [fid]))

    memo = {}

    def calcular(fid, stack):
        if fid in memo: return memo[fid]
        if fid in corte_fids: memo[fid] = 0; return 0
        if fid in stack: return 1
        stack.add(fid)
        inc = incoming_by_seg.get(fid, [])
        if not inc:
            valor = 1
        else:
            inc_sum = sum(calcular(p, stack) for p in inc)
            out = outgoing_same.get(fid, [])
            if len(out) <= 1:
                valor = inc_sum + 1
            else:
                ordenados = sorted(out, key=lambda s: (-pendiente.get(s, 0.0), s))
                valor = inc_sum + 1 if fid == ordenados[0] else 1
        stack.discard(fid)
        memo[fid] = int(valor)
        return memo[fid]

    pos_rel = {}
    for row in filas:
        fid = row[0]
        ni, nf = start_node[fid], end_node[fid]
        pos_rel[fid] = 0 if (not ni and not nf) else calcular(fid, set())

    triggers = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,)
    ).fetchall()
    for name, _ in triggers: con.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for row in filas:
        fid = row[0]
        nuevo_val  = pos_rel[fid]
        nuevo_clas = _clasificar(nuevo_val, rangos)
        actual_val  = row[-2]
        actual_clas = row[-1]
        if actual_val != nuevo_val or actual_clas != nuevo_clas:
            con.execute(
                f'UPDATE "{tabla}" SET "{campo_pos_rel}"=?, "{campo_pos_rel_clas}"=? WHERE fid=?',
                (nuevo_val, nuevo_clas, fid)
            )
            actualizadas += 1

    for _, sql in triggers:
        if sql: con.execute(sql)
    con.commit(); con.close()
    print(f"OK. '{campo_pos_rel}' y '{campo_pos_rel_clas}' actualizados en {actualizadas}/{len(filas)} colectores.")


def main():
    p = argparse.ArgumentParser(description="CF Posicion Relativa standalone")
    p.add_argument("--gpkg", required=True)
    p.add_argument("--layer", default=None)
    p.add_argument("--campo-pos-rel",      default=CAMPO_POS_REL_DEFAULT)
    p.add_argument("--campo-pos-rel-clas", default=CAMPO_POS_REL_CLAS_DEFAULT)
    p.add_argument("--campo-pendiente",    default=CAMPO_PENDIENTE_DEFAULT)
    p.add_argument("--campo-reg-ini",      default=CAMPO_REG_INI_DEFAULT)
    p.add_argument("--campo-reg-fin",      default=CAMPO_REG_FIN_DEFAULT)
    p.add_argument("--campo-inspeccion",   default=CAMPO_INSPECCION_DEFAULT)
    p.add_argument("--valores-corte",      default=VALORES_CORTE_DEFAULT,
                   help="Tipos a ignorar en la red (ej: 'AL,EB')")
    p.add_argument("--rango",              default=RANGO_POS_REL_DEFAULT,
                   help="Ej: '10=1; 30=2; 70=3; 120=4; 150=5'")
    a = p.parse_args()
    run(a.gpkg, a.layer, a.campo_pos_rel, a.campo_pos_rel_clas, a.campo_pendiente,
        a.campo_reg_ini, a.campo_reg_fin, a.campo_inspeccion, a.valores_corte, a.rango)

if __name__ == "__main__":
    main()
