"""
Precalcula lo pesado del tablero y lo deja cacheado en parquet.

    python scripts/precompute.py
    python scripts/precompute.py --gpkg ruta.gpkg --capa DatosConsecuenciaDeFalla
    python scripts/precompute.py --nsim 2000

Sin esto el tablero arranca igual, pero el tab de Sensibilidad y el de
Priorizacion aparecen vacios hasta que alguien apreta el boton y espera. Con el
cache al dia, los cuatro tabs estan llenos apenas carga la pagina.

El nombre del archivo de cache incluye una firma de (ruta, mtime, parametros),
asi que reescribir el .gpkg invalida el cache solo: no hay que acordarse de
borrarlo, y un cache viejo nunca se puede colar como si fuera del dato nuevo.
"""
import argparse
import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from app.dashboard import data, estado  # noqa: E402
from cf_pf_core.analisis import espacial as sp  # noqa: E402
from cf_pf_core.analisis import sensibilidad as sn  # noqa: E402


def _barra(fraccion, etiqueta):
    ancho = 32
    lleno = int(fraccion * ancho)
    sys.stdout.write(f"\r  [{'█' * lleno}{'·' * (ancho - lleno)}] {etiqueta}   ")
    sys.stdout.flush()


def monte_carlo(datos, n_sim, forzar=False):
    firma = data.firma(datos.ruta, datos.capa,
                       f"mc|{n_sim}|{estado.SEED}|False")
    destino = data.ruta_cache("sensibilidad", firma)
    if os.path.isfile(destino) and not forzar:
        print(f"  ya estaba: {os.path.basename(destino)}")
        return destino

    X, _ = datos.matriz()
    t = time.time()
    res = sn.monte_carlo(X, n_sim=n_sim, seed=estado.SEED, progreso=_barra)
    res = sn.clasificar_robustez(res)
    print()
    cuenta = sn.resumen_categorias(res)
    print(f"  {time.time() - t:.1f} s · " +
          " · ".join(f"{k}: {v}" for k, v in cuenta.items()))
    data.escribir_cache(res, "sensibilidad", firma)
    return destino


def lisa(datos, forzar=False):
    firma = data.firma(datos.ruta, datos.capa,
                       f"lisa|{sp.K_VECINOS}|{sp.PERMUTACIONES}|"
                       "media_aritmetica|False")
    destino = data.ruta_cache("lisa", firma)
    if os.path.isfile(destino) and not forzar:
        print(f"  ya estaba: {os.path.basename(destino)}")
        return destino

    from cf_pf_core.analisis import indices

    valores = indices.criticidad_vectorizada(datos.gdf, datos.grupos).to_numpy()
    t = time.time()
    _barra(0.15, "vecindad KNN")
    w = sp.pesos_knn(datos.gdf)
    _barra(0.35, "Moran global")
    moran = sp.moran_global(valores, w)
    _barra(0.55, f"{sp.PERMUTACIONES} permutaciones")
    li = sp.lisa(valores, w)
    _barra(0.80, "agrupando zonas")
    zonas, zona_tramo = sp.zonas_intervencion(
        datos.gdf, li["cluster"].to_numpy(), valores, datos.longitud)
    _barra(1.0, "listo")
    print()

    guardar = li.copy()
    guardar["zona"] = zona_tramo.to_numpy()
    guardar.attrs.update({k: moran[k] for k in ("I", "p", "z", "lectura")})
    data.escribir_cache(guardar, "lisa", firma)

    cuenta = sp.resumen_clusters(li)
    print(f"  {time.time() - t:.1f} s · Moran's I {moran['I']:.4f} "
          f"(p {moran['p']}) · " + " · ".join(f"{k}: {v}" for k, v in cuenta.items()))
    print(f"  {len(zonas)} zonas HH · {zonas['longitud'].sum() / 1000:.1f} km")
    return destino


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Precalcula Monte Carlo y LISA para el tablero.")
    ap.add_argument("--gpkg", default=None,
                    help="GeoPackage de resultados (default: CF_GPKG).")
    ap.add_argument("--capa", default=None, help="Capa dentro del GeoPackage.")
    ap.add_argument("--nsim", type=int, default=estado.N_SIM_DEFAULT,
                    help=f"Simulaciones del Monte Carlo (default {estado.N_SIM_DEFAULT}).")
    ap.add_argument("--forzar", action="store_true",
                    help="Recalcular aunque el cache exista.")
    ap.add_argument("--solo", choices=["mc", "lisa"], default=None,
                    help="Correr sólo una de las dos partes.")
    args = ap.parse_args(argv)

    print(f"Leyendo capa…")
    t = time.time()
    datos = data.cargar(args.gpkg, args.capa)
    print(f"  {len(datos)} tramos en {time.time() - t:.1f} s · "
          f"{os.path.basename(datos.ruta)}")
    prop, msg = datos.verificar_reproduccion()
    print(f"  {msg}")
    if prop is not None and prop < 0.99:
        # Se avisa pero no se aborta: el cache sirve igual para explorar, y quien
        # corre esto tiene que poder ver el numero para decidir.
        print("  (los resultados no son los del índice entregado)")

    os.makedirs(estado.CACHE, exist_ok=True)
    if args.solo in (None, "mc"):
        print(f"\nMonte Carlo ({args.nsim} escenarios)…")
        monte_carlo(datos, args.nsim, args.forzar)
    if args.solo in (None, "lisa"):
        print(f"\nLISA ({sp.PERMUTACIONES} permutaciones, k={sp.K_VECINOS})…")
        lisa(datos, args.forzar)

    print(f"\nCaché en {estado.CACHE}")
    print("Levantá el tablero con:  bokeh serve app/dashboard --show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
