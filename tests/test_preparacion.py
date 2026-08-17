"""Pasos de preparacion: son los unicos que escriben sobre las capas reales."""
import os
import sqlite3
import tempfile
import unittest

import geopandas as gpd
from shapely.geometry import LineString, Point

from cf_pf_core import preparacion
from cf_pf_core.preparacion import gpkg_edit as ge

CRS = "EPSG:32721"
CFG = {"campo_cota_tapa": "cota", "campo_id_reg": "elem_red",
       "campo_zarriba": "zarriba"}


class TestCotaZampeado(unittest.TestCase):
    """Deduce Cota_Zampeado_Calculada y Profundidad_Inspeccionada desde ZARRIBA
    del colector y la cota de tapa del registro."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.col = os.path.join(tmp, "colectores.gpkg")
        self.reg = os.path.join(tmp, "registros.gpkg")
        gpd.GeoDataFrame(
            {"Registro_Inicial": [10, 20, 30], "zarriba": [8.0, 5.0, 0.0]},
            geometry=[LineString([(i, 0), (i + 1, 0)]) for i in range(3)],
            crs=CRS).to_file(self.col, layer="colectores", driver="GPKG")
        gpd.GeoDataFrame(
            {"elem_red": [10, 20, 30], "cota": [12.5, 9.0, 7.0]},
            geometry=[Point(i, 0) for i in range(3)],
            crs=CRS).to_file(self.reg, layer="registros", driver="GPKG")

    def _valores(self, campo):
        con = sqlite3.connect(self.reg)
        try:
            cols = [r[1] for r in con.execute('PRAGMA table_info("registros")')]
            if campo not in cols:
                return None
            return [r[0] for r in con.execute(
                f'SELECT "{campo}" FROM "registros" ORDER BY "elem_red"')]
        finally:
            con.close()

    def _correr(self):
        return preparacion.correr("cota_zampeado", gpkg_col=self.col,
                                  gpkg_reg=self.reg, config=CFG)

    def test_deduce_la_profundidad(self):
        self._correr()
        # 12.5-8.0=4.5 | 9.0-5.0=4.0 | zarriba 0 -> sin dato
        self.assertEqual(self._valores("Profundidad_Inspeccionada"), [4.5, 4.0, None])
        self.assertEqual(self._valores("Cota_Zampeado_Calculada"), [8.0, 5.0, 0.0])

    def test_no_pisa_lo_que_ya_estaba(self):
        self._correr()
        con = ge.conectar(self.reg, escritura=True)
        with ge.sin_triggers(con, "registros"):
            con.execute('UPDATE "registros" SET "Profundidad_Inspeccionada"=9.9 '
                        'WHERE "elem_red"=10')
        con.commit()
        con.close()
        self._correr()
        self.assertEqual(self._valores("Profundidad_Inspeccionada")[0], 9.9)

    def test_completa_la_profundidad_aunque_la_cota_ya_este(self):
        """BUG (2026-08): con Cota_Zampeado_Calculada ya cargada, un unico guard
        cortaba la iteracion y Profundidad_Inspeccionada quedaba NULL para
        siempre. Son dos salidas independientes."""
        self._correr()
        con = ge.conectar(self.reg, escritura=True)
        with ge.sin_triggers(con, "registros"):
            con.execute('UPDATE "registros" SET "Profundidad_Inspeccionada"=NULL')
        con.commit()
        con.close()
        self.assertEqual(self._valores("Profundidad_Inspeccionada"), [None] * 3)

        self._correr()
        self.assertEqual(self._valores("Profundidad_Inspeccionada"), [4.5, 4.0, None],
                         "la profundidad tiene que recuperarse en una segunda corrida")

    def test_es_idempotente(self):
        self._correr()
        primero = self._valores("Profundidad_Inspeccionada")
        self._correr()
        self.assertEqual(self._valores("Profundidad_Inspeccionada"), primero)


if __name__ == "__main__":
    unittest.main()
