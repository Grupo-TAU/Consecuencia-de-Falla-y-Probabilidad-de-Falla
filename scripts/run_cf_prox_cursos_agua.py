"""
CF Proximidad Cursos de Agua (Medio Ambiental) - standalone sin QGIS.
Requiere: pip install shapely

Crea buffers crecientes alrededor de cursos de agua y clasifica colectores
segun el buffer mas pequeno que los intersecta.

Rangos por defecto: 25=6; 50=5; 100=4; 200=3; 400=2
Colectores sin interseccion reciben clase 1.

Uso:
    python scripts\\run_cf_prox_cursos_agua.py \\
        --gpkg-col <ruta> --gpkg-cursos <ruta>
"""
import argparse, sqlite3, sys, os

try:
    from shapely import wkb as shapely_wkb
    from shapely.strtree import STRtree
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

CAMPO_CLASIFICACION_DEFAULT = "CF_Prox_MedioAmbiental"
RANGOS_DEFAULT = "25=6; 50=5; 100=4; 200=3; 400=2"


def _detectar_capa(con, layer_name, etiqueta="capa"):
    capas = [r[0] for r in con.execute(
        "SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()]
    if not capas: print(f"ERROR: Sin capas en {etiqueta}."); sys.exit(1)
    if layer_name:
        if layer_name not in capas:
            print(f"ERROR: '{layer_name}' no existe. Disponibles: {capas}"); sys.exit(1)
        return layer_name
    if len(capas) == 1: return capas[0]
    print(f"Varias capas en {etiqueta}: {capas}."); sys.exit(1)


def _columnas(con, tabla):
    return [r[1] for r in con.execute(f"PRAGMA table_info('{tabla}')").fetchall()]


def _campo(cols, *nombres):
    lower = {c.lower(): c for c in cols}
    for n in nombres:
        if n.lower() in lower: return lower[n.lower()]
    return None


def _geom_col(con, tabla):
    rows = con.execute(
        "SELECT column_name FROM gpkg_geometry_columns WHERE table_name=?", (tabla,)
    ).fetchall()
    return rows[0][0] if rows else "geom"


def _wkb_offset(blob):
    if blob is None or len(blob) < 8: return -1
    if bytes(blob[:2]) != b'GP': return -1
    flags = blob[3]
    env_type = (flags & 0x0E) >> 1
    env_sizes = [0, 32, 48, 48, 64]
    return 8 + (env_sizes[env_type] if env_type <= 4 else 0)


def _blob_to_geom(blob):
    offset = _wkb_offset(blob)
    if offset < 0: return None
    try:
        return shapely_wkb.loads(bytes(blob[offset:]))
    except Exception:
        return None


def _parse_rangos(texto):
    rangos = []
    for par in str(texto).split(";"):
        par = par.strip()
        if "=" not in par: continue
        d, _, c = par.partition("=")
        try:
            rangos.append((float(d.strip()), int(c.strip())))
        except ValueError: continue
    return sorted(rangos, key=lambda x: x[0]) if rangos else []


def run(gpkg_col, gpkg_cursos,
        layer_col=None, layer_cursos=None,
        campo_cf=CAMPO_CLASIFICACION_DEFAULT,
        rango_str=RANGOS_DEFAULT):

    if not HAS_SHAPELY:
        print("ERROR: shapely no encontrado. Instala con: pip install shapely"); sys.exit(1)

    gpkg_col    = os.path.normpath(gpkg_col)
    if gpkg_cursos is None: gpkg_cursos = gpkg_col
    gpkg_cursos = os.path.normpath(gpkg_cursos)
    for path in (gpkg_col, gpkg_cursos):
        if not os.path.isfile(path): print(f"ERROR: No existe '{path}'"); sys.exit(1)

    rangos = _parse_rangos(rango_str)
    if not rangos: print("ERROR: Rangos invalidos."); sys.exit(1)
    print(f"Rangos buffer: {rangos}")

    # Cargar cursos de agua
    con_cur = sqlite3.connect(gpkg_cursos)
    tabla_cur = _detectar_capa(con_cur, layer_cursos, "cursos de agua")
    gc_cur    = _geom_col(con_cur, tabla_cur)
    cursos_geoms = []
    for blob, in con_cur.execute(f'SELECT "{gc_cur}" FROM "{tabla_cur}"').fetchall():
        g = _blob_to_geom(blob)
        if g is not None and not g.is_empty:
            cursos_geoms.append(g)
    con_cur.close()
    print(f"Cursos de agua cargados: {len(cursos_geoms)}")

    # Cargar colectores
    con_col = sqlite3.connect(gpkg_col)
    con_col.execute("PRAGMA journal_mode=WAL")
    tabla_col = _detectar_capa(con_col, layer_col, "colectores")
    cols_col  = _columnas(con_col, tabla_col)
    gc_col    = _geom_col(con_col, tabla_col)

    if not _campo(cols_col, campo_cf):
        con_col.execute(f'ALTER TABLE "{tabla_col}" ADD COLUMN "{campo_cf}" INTEGER')

    filas = con_col.execute(
        f'SELECT fid, "{gc_col}", "{campo_cf}" FROM "{tabla_col}"'
    ).fetchall()
    print(f"Colectores: {len(filas)}")

    col_geoms = []
    col_fids  = []
    for fid, blob, _ in filas:
        g = _blob_to_geom(blob)
        if g is not None and not g.is_empty:
            col_geoms.append(g)
            col_fids.append(fid)
    tree_col = STRtree(col_geoms)

    clasificacion = {}
    rangos_ord = sorted(rangos, key=lambda x: x[0])

    for curso_geom in cursos_geoms:
        for dist, clase in rangos_ord:
            buf = curso_geom.buffer(dist)
            for idx in tree_col.query(buf):
                fid = col_fids[idx]
                if fid in clasificacion: continue
                if col_geoms[idx].intersects(buf):
                    clasificacion[fid] = clase

    triggers = con_col.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla_col,)
    ).fetchall()
    for name, _ in triggers: con_col.execute(f'DROP TRIGGER IF EXISTS "{name}"')

    actualizadas = 0
    for fid, _, cf_actual in filas:
        nueva = clasificacion.get(fid, 1)
        if cf_actual != nueva:
            con_col.execute(
                f'UPDATE "{tabla_col}" SET "{campo_cf}"=? WHERE fid=?', (nueva, fid)
            )
            actualizadas += 1

    for _, sql in triggers:
        if sql: con_col.execute(sql)
    con_col.commit(); con_col.close()
    print(f"OK. '{campo_cf}' actualizado en {actualizadas}/{len(filas)} colectores.")
    print(f"  Con interseccion: {len(clasificacion)}, Sin interseccion (clase 1): {len(filas)-len(clasificacion)}")


def main():
    p = argparse.ArgumentParser(description="CF Prox Cursos de Agua standalone")
    p.add_argument("--gpkg", "--gpkg-col", dest="gpkg_col", required=True,
                   help="GeoPackage con Colectores")
    p.add_argument("--layer-col",   default=None)
    p.add_argument("--gpkg-cursos", default=None,
                   help="GeoPackage con Cursos de Agua (default: mismo que --gpkg)")
    p.add_argument("--layer-cursos", default=None)
    p.add_argument("--campo-cf",    default=CAMPO_CLASIFICACION_DEFAULT)
    p.add_argument("--rango",       default=RANGOS_DEFAULT,
                   help="Ej: '25=6; 50=5; 100=4; 200=3; 400=2'")
    a = p.parse_args()
    run(a.gpkg_col, a.gpkg_cursos, a.layer_col, a.layer_cursos, a.campo_cf, a.rango)

if __name__ == "__main__":
    main()
