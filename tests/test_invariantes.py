"""Propiedades que tienen que valer SIEMPRE, con cualquier dato de entrada.

Cada test de este archivo corresponde a un bug real que ya ocurrio. No prueban
un valor concreto sino una regla: si se vuelve a romper, se rompe aca.
"""
import unittest

import geopandas as gpd
import pandas as pd

from cf_pf_core import flujo, gpkg_io
from cf_pf_core.calculos import criticidad as C
from cf_pf_core.calculos import proximidad
from tests.helpers import CRS, colectores, lineas, objetivos


class TestOrdenDeLasFilas(unittest.TestCase):
    """BUG (2026-08): proximidad recorria los objetivos por fuera y congelaba la
    clase con el PRIMERO que alcanzaba al colector, no con el mas cercano. El
    resultado dependia del orden de las filas de la capa de objetivos."""

    def test_proximidad_no_depende_del_orden_de_los_objetivos(self):
        col = gpd.GeoDataFrame({"id": [1]}, geometry=lineas(1), crs=CRS)
        rango = proximidad.RANGOS_MEDIOAMBIENTAL_DEFAULT
        distancias = [180, 10, 350, 45]
        clase_ref, dist_ref = proximidad.calcular_detalle(
            col, objetivos(distancias), rango)

        for corte in range(len(distancias)):
            rotado = distancias[corte:] + distancias[:corte]
            clase, dist = proximidad.calcular_detalle(col, objetivos(rotado), rango)
            self.assertEqual(int(clase.iloc[0]), int(clase_ref.iloc[0]),
                             f"con los objetivos en el orden {rotado}")
            self.assertAlmostEqual(float(dist.iloc[0]), float(dist_ref.iloc[0]))

    def test_proximidad_toma_el_mas_cercano(self):
        col = gpd.GeoDataFrame({"id": [1]}, geometry=lineas(1), crs=CRS)
        clase, dist = proximidad.calcular_detalle(
            col, objetivos([180, 10]), proximidad.RANGOS_MEDIOAMBIENTAL_DEFAULT)
        self.assertEqual(int(clase.iloc[0]), 6, "10 m manda sobre 180 m")
        self.assertAlmostEqual(float(dist.iloc[0]), 10.0)


class TestSubdivision(unittest.TestCase):
    """Los poligonos grandes se trocean para que el indice espacial sirva. Es una
    optimizacion: no puede mover ni un decimal de las distancias."""

    def _poligono_denso(self, lado=1000.0, n=400):
        import math

        from shapely.geometry import Polygon
        pts = [(lado / 2 + lado / 2 * math.cos(2 * math.pi * i / n),
                lado / 2 + lado / 2 * math.sin(2 * math.pi * i / n))
               for i in range(n)]
        return Polygon(pts)

    def test_la_union_de_las_piezas_es_la_original(self):
        import shapely

        from cf_pf_core import geo
        original = self._poligono_denso()
        piezas = geo.subdividir(original, max_vertices=32)
        self.assertGreater(len(piezas), 1, "no se troceo")
        union = shapely.union_all(piezas)
        self.assertAlmostEqual(union.area, original.area, places=3)

    def test_la_distancia_no_cambia(self):
        import shapely

        from cf_pf_core import geo
        original = self._poligono_denso()
        piezas = geo.subdividir(original, max_vertices=32)
        for x in (-500, -100, 0, 500, 2000):
            punto = shapely.geometry.Point(x, -800)
            d_orig = punto.distance(original)
            d_piezas = min(punto.distance(p) for p in piezas)
            self.assertAlmostEqual(d_orig, d_piezas, places=6,
                                   msg=f"desde x={x}")

    def test_capas_chicas_no_se_tocan(self):
        from shapely.geometry import Point

        from cf_pf_core import geo
        geoms = [Point(0, 0).buffer(10), Point(100, 0).buffer(10)]
        self.assertEqual(len(geo.trocear_todas(geoms)), 2)

    def test_proximidad_da_lo_mismo_con_poligonos_grandes(self):
        import geopandas as gpd

        from cf_pf_core import geo
        from cf_pf_core.calculos import proximidad as P
        col = gpd.GeoDataFrame({"id": [1]}, geometry=lineas(1), crs=CRS)
        grande = gpd.GeoDataFrame(
            {"i": [0]}, geometry=[self._poligono_denso().buffer(0)], crs=CRS)
        clase, dist = P.calcular_detalle(col, grande, P.RANGOS_SITIOS_DEFAULT)
        # Mismo calculo forzando a NO trocear, para comparar.
        original = geo.MAX_VERTICES_DEFAULT
        try:
            geo.MAX_VERTICES_DEFAULT = 10 ** 9
            clase2, dist2 = P.calcular_detalle(col, grande, P.RANGOS_SITIOS_DEFAULT)
        finally:
            geo.MAX_VERTICES_DEFAULT = original
        self.assertEqual(int(clase.iloc[0]), int(clase2.iloc[0]))
        self.assertAlmostEqual(float(dist.iloc[0]), float(dist2.iloc[0]), places=6)


class TestCantidadDeFilas(unittest.TestCase):
    """BUG (2026-08): la capa de salida se multiplicaba en cada calculo
    individual. Ninguna operacion puede cambiar la cantidad de tramos."""

    def test_correr_no_cambia_la_cantidad_de_filas(self):
        col = colectores(5)
        res = flujo.correr(col, solo=["criticidad", "pf", "riesgo"])
        self.assertEqual(len(res), len(col))

    def test_escribir_sobre_una_capa_existente_no_multiplica(self):
        import os
        import tempfile
        out = os.path.join(tempfile.mkdtemp(), "salida.gpkg")
        col = colectores(5)

        res = flujo.correr(col, solo=["criticidad"])
        gpkg_io.escribir_resultados(res, out, clave="ELEMRED", reemplazar=True)
        n0 = len(gpkg_io.leer_capa(out, gpkg_io.LAYER_SALIDA_DEFAULT))

        for _ in range(3):
            base = gpkg_io.leer_capa(out, gpkg_io.LAYER_SALIDA_DEFAULT)
            r = flujo.correr(col, solo=["pf"], base=base, clave="ELEMRED")
            gpkg_io.escribir_resultados(r, out, clave="ELEMRED")
            n = len(gpkg_io.leer_capa(out, gpkg_io.LAYER_SALIDA_DEFAULT))
            self.assertEqual(n, n0, "un calculo individual multiplico las filas")

    def test_clave_repetida_corta_en_vez_de_multiplicar(self):
        col = colectores(3)
        base = gpd.GeoDataFrame(
            {"ELEMRED": [1, 1, 2, 2, 3, 3], "CF_Diametro": [4] * 6},
            geometry=lineas(3) * 2, crs=CRS)
        with self.assertRaises(ValueError) as e:
            flujo.correr(col, solo=["criticidad"], base=base, clave="ELEMRED")
        self.assertIn("repetidos", str(e.exception))

    def test_diagnostico_detecta_claves_rotas(self):
        sana = gpd.GeoDataFrame({"ELEMRED": [1, 2, 3]}, geometry=lineas(3), crs=CRS)
        self.assertIsNone(gpkg_io.diagnosticar_claves(sana, "ELEMRED"))

        repetida = gpd.GeoDataFrame({"ELEMRED": [1, 1, 2]}, geometry=lineas(3), crs=CRS)
        self.assertIn("repetidos", gpkg_io.diagnosticar_claves(repetida, "ELEMRED"))

        # Varias filas sin clave colapsan todas en "" al normalizar y se cruzan.
        vacias = gpd.GeoDataFrame({"ELEMRED": [1.0, None, None]},
                                  geometry=lineas(3), crs=CRS)
        self.assertIn("sin", gpkg_io.diagnosticar_claves(vacias, "ELEMRED"))


class TestRangosDeSalida(unittest.TestCase):
    """Todo CF vive en 1..6 y la criticidad tambien. Un valor fuera de escala
    rompe la simbologia y el visualizador sin avisar."""

    def test_criticidad_queda_en_escala(self):
        for valor in (1, 2, 3, 4, 5, 6):
            d = pd.DataFrame({p: [valor] for p in C.PARAMS_DISPONIBLES})
            crit = float(C.calcular(d).iloc[0])
            self.assertGreaterEqual(crit, 1.0)
            self.assertLessEqual(crit, 6.0)

    def test_criticidad_es_monotona(self):
        """Subir todos los CF no puede bajar la criticidad."""
        previa = None
        for valor in range(1, 7):
            d = pd.DataFrame({p: [valor] for p in C.PARAMS_DISPONIBLES})
            crit = float(C.calcular(d).iloc[0])
            if previa is not None:
                self.assertGreaterEqual(crit, previa)
            previa = crit


class TestClaveConfigurable(unittest.TestCase):
    """La criticidad se puede escribir como 'CF' para el visualizador de las
    entregas; renombrarla no puede cambiar ningun numero."""

    def test_renombrar_no_cambia_los_valores(self):
        col = colectores(4, PACP_Clasificacion=["5B", "3222", "0000", "4131"])
        pasos = ["criticidad", "pf", "riesgo"]
        base = flujo.correr(col, solo=pasos)
        renombrado = flujo.correr(col, solo=pasos, config={"criticidad_campo": "CF"})

        self.assertIn("criticidad", base.columns)
        self.assertIn("CF", renombrado.columns)
        self.assertEqual(list(base["criticidad"]), list(renombrado["CF"]))
        self.assertEqual(list(base["Riesgo"]), list(renombrado["Riesgo"]),
                         "Riesgo tiene que seguir encontrando la criticidad")

    def test_vacio_cae_al_nombre_por_defecto(self):
        for valor in ("", "   ", None):
            r = flujo.correr(colectores(2), solo=["criticidad"],
                             config={"criticidad_campo": valor})
            self.assertIn("criticidad", r.columns, f"con criticidad_campo={valor!r}")


class TestFuenteIntacta(unittest.TestCase):
    """Regla de oro del proyecto: la capa de Colectores se LEE, nunca se escribe."""

    def test_correr_no_modifica_la_capa_de_entrada(self):
        col = colectores(4)
        antes_cols = list(col.columns)
        antes_filas = len(col)
        flujo.correr(col, solo=["criticidad", "pf", "riesgo"])
        self.assertEqual(list(col.columns), antes_cols)
        self.assertEqual(len(col), antes_filas)


class TestProgreso(unittest.TestCase):
    """La barra tiene que avanzar aunque los pasos se salteen por falta de capa."""

    def test_progreso_es_monotono_y_llega_a_uno(self):
        avisos = []
        flujo.correr(colectores(3), progreso=lambda f, e: avisos.append(f))
        self.assertTrue(avisos, "no se reporto progreso")
        self.assertEqual(avisos, sorted(avisos), "el progreso retrocedio")
        self.assertEqual(avisos[-1], 1.0)
        self.assertGreaterEqual(avisos[0], 0.0)

    def test_los_pasos_salteados_igual_avanzan(self):
        # Sin capas auxiliares se saltean varios pasos; igual tiene que llegar a 100%.
        avisos = []
        flujo.correr(colectores(3), solo=["prox_sitios", "prox_medioamb", "criticidad"],
                     progreso=lambda f, e: avisos.append(f))
        self.assertEqual(avisos[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
