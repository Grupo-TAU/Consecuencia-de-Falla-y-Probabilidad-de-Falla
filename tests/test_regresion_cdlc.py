"""Regresion contra los datos reales de Ciudad de la Costa.

Es la unica validacion que compara contra numeros que no salieron de este codigo.
Se saltea sola si G: no esta montado, asi la suite corre igual en cualquier maquina.

Para apuntar a otra copia de los datos:
    set CF_PF_DATOS_CDLC=D:\\ruta\\a\\ciudad_de_la_costa
"""
import os
import unittest

BASE = os.environ.get(
    "CF_PF_DATOS_CDLC",
    r"G:\Unidades compartidas\GRUPO TAU\02 - EQUIPO TAU\NA"
    r"\Ciudad_de_la_Costa_Visor\ciudad_de_la_costa",
)
COLECTORES = os.path.join(BASE, "Colectoress.gpkg")
CAPA = "rehecho"

hay_datos = os.path.isfile(COLECTORES)
motivo = f"no se encontro {COLECTORES} (definí CF_PF_DATOS_CDLC para apuntar a otra copia)"


@unittest.skipUnless(hay_datos, motivo)
class TestCriticidadCDLC(unittest.TestCase):
    """La capa `rehecho` ya trae su columna `criticidad` calculada por la
    herramienta anterior. El core tiene que reproducirla exactamente."""

    @classmethod
    def setUpClass(cls):
        import geopandas as gpd
        cls.gdf = gpd.read_file(COLECTORES, layer=CAPA)

    def test_la_capa_es_la_esperada(self):
        self.assertGreater(len(self.gdf), 0)
        self.assertIn("criticidad", self.gdf.columns,
                      "la capa de referencia no trae la columna a comparar")

    def test_criticidad_reproduce_la_referencia(self):
        from cf_pf_core.calculos import criticidad as C
        _mapa, faltantes = C.resolver_columnas(self.gdf.columns, C.GRUPOS_DEFAULT)
        if faltantes:
            self.skipTest(f"a la capa le faltan CF: {faltantes}")

        calculada = C.calcular(self.gdf).round(2)
        referencia = self.gdf["criticidad"].astype(float).round(2)
        distintos = int((calculada != referencia).sum())
        self.assertEqual(
            distintos, 0,
            f"{distintos} de {len(self.gdf)} tramos difieren de rehecho.criticidad")

    def test_no_hay_claves_repetidas_en_la_fuente(self):
        from cf_pf_core import gpkg_io
        for clave in ("ELEMRED", "ID"):
            if clave in self.gdf.columns:
                aviso = gpkg_io.diagnosticar_claves(self.gdf, clave)
                self.assertIsNone(aviso, f"la capa fuente tiene un problema: {aviso}")
                return
        self.skipTest("la capa no tiene ELEMRED ni ID")


@unittest.skipUnless(hay_datos, motivo)
class TestProximidadCDLC(unittest.TestCase):
    """Cuantos tramos cambian de clase con la proximidad nueva (por distancia al
    mas cercano) respecto de la vieja (por buffers, primer objetivo gana).

    No falla por encontrar diferencias —se esperan, es un arreglo—: falla si la
    version nueva resultara MENOS critica que la vieja, que seria imposible.
    """

    def _cargar(self, *palabras):
        """Busca un .gpkg cuyo nombre contenga todas las palabras dadas.

        Los nombres reales traen espacios de mas ('cursos _de_agua.gpkg'), asi
        que buscar por nombre exacto no sirve.
        """
        import glob

        import geopandas as gpd
        for sub in ("", "Datos"):
            for ruta in glob.glob(os.path.join(BASE, sub, "*.gpkg")):
                nombre = os.path.basename(ruta).lower().replace(" ", "")
                if all(p in nombre for p in palabras) and "buffer" not in nombre:
                    return gpd.read_file(ruta)
        return None

    def test_la_nueva_nunca_es_menos_critica(self):
        import geopandas as gpd
        from cf_pf_core.calculos import proximidad as P

        colectores = gpd.read_file(COLECTORES, layer=CAPA)
        cursos = self._cargar("cursos", "agua")
        if cursos is None:
            self.skipTest("no se encontro la capa de cursos de agua")

        if "CF_Prox_MedioAmbiental" not in colectores.columns:
            self.skipTest("la capa no trae CF_Prox_MedioAmbiental para comparar")

        nueva, dist = P.calcular_detalle(
            colectores, cursos, P.RANGOS_MEDIOAMBIENTAL_DEFAULT)
        vieja = colectores["CF_Prox_MedioAmbiental"]
        # La columna vieja trae nulos (tramos que nunca se calcularon): solo se
        # comparan los que tienen un valor previo con el que contrastar.
        comparables = vieja.notna()
        v = vieja[comparables].astype(float)
        n = nueva[comparables].astype(float)

        cambian = int((n != v).sum())
        peores = int((n < v).sum())
        print(f"\n    [CDLC] {len(colectores)} tramos, {int(comparables.sum())} comparables")
        print(f"    [CDLC] cambian de clase : {cambian}"
              f" ({100 * cambian / max(int(comparables.sum()), 1):.1f} %)")
        print(f"    [CDLC] suben (mas critico): {int((n > v).sum())}")
        print(f"    [CDLC] bajan               : {peores}")
        print(f"    [CDLC] distancia mediana al curso mas cercano: {dist.median():.1f} m")

        self.assertEqual(
            peores, 0,
            f"{peores} tramos quedaron MENOS criticos que antes; la version por "
            "buffers solo podia subestimar, nunca sobreestimar")


if __name__ == "__main__":
    unittest.main()
