"""Valores exactos de cada calculo, incluidos los bordes y el 'sin dato'.

Cada clase cubre un modulo de cf_pf_core.calculos. Los valores esperados salen
de la documentacion de cada modulo, no de correr el codigo y copiar la salida:
si manana alguien cambia la logica, el test tiene que protestar.
"""
import unittest

import geopandas as gpd
import pandas as pd

from cf_pf_core.calculos import (
    antiguedad, criticidad, diametro, material, obstrucciones,
    probabilidad_falla, proximidad, riesgo,
)
from tests.helpers import CRS, lineas, objetivos


def df(**columnas):
    return pd.DataFrame(columnas)


class TestDiametro(unittest.TestCase):
    """Rangos '200=1; 300=2; 400=3; 500=4; 800=5'; el corte es ESTRICTO (<)."""

    def test_clases_por_rango(self):
        d = df(DIAMETRO=[150, 200, 250, 300, 450, 799, 800, 1200])
        self.assertEqual(list(diametro.calcular(d)),
                         [1, 2, 2, 3, 4, 5, 6, 6])

    def test_sin_dato_va_a_cero(self):
        d = df(DIAMETRO=[None, float("nan"), "", "sin datos"])
        self.assertEqual(list(diametro.calcular(d)), [0, 0, 0, 0])

    def test_texto_con_unidades(self):
        self.assertEqual(list(diametro.calcular(df(DIAMETRO=["200 mm", "Ø 300"]))),
                         [2, 3])

    def test_separadores_ambiguos(self):
        """OJO: este test documenta la conducta ACTUAL, que tiene un filo.

        _to_mm solo trata el punto como separador de miles cuando ademas hay una
        coma. Con punto solo lo lee como decimal, asi que '1.200' da 1,2 mm y no
        1200 mm. Y ',200' (3 decimales) se toma como miles, asi que '0,200' da
        200 mm. Las dos lecturas son defendibles por separado pero se contradicen
        entre si; si en alguna capa aparecen diametros escritos '1.200' van a caer
        todos en clase 1 sin avisar.
        """
        d = df(DIAMETRO=["1.200", "1,5", "0,200"])
        self.assertEqual(list(diametro.calcular(d)), [1, 1, 2])

    def test_campo_ausente_explica_el_problema(self):
        with self.assertRaises(KeyError) as e:
            diametro.calcular(df(otro=[1]))
        self.assertIn("DIAMETRO", str(e.exception))


class TestAntiguedad(unittest.TestCase):
    """Limites [10,20,30,50] -> clases [1,2,3,4,6]; el corte es INCLUSIVO (<=)."""

    def test_clases_por_tramo(self):
        d = df(Antiguedad=[0, 10, 11, 20, 21, 30, 31, 50, 51, 200])
        self.assertEqual(list(antiguedad.calcular(d)),
                         [1, 1, 2, 2, 3, 3, 4, 4, 6, 6])

    def test_sin_dato_va_a_cero(self):
        self.assertEqual(list(antiguedad.calcular(df(Antiguedad=[None, "x"]))), [0, 0])

    def test_clases_deben_ser_una_mas_que_limites(self):
        with self.assertRaises(ValueError):
            antiguedad.calcular(df(Antiguedad=[1]), limites=[10, 20], clases=[1, 2])


class TestMaterial(unittest.TestCase):
    def test_mapeo_por_defecto(self):
        d = df(Material=["PE", "PVC", "PEAD", "Hormigon Armado",
                         "Hormigon Simple", "Mamposteria"])
        self.assertEqual(list(material.calcular(d)), [1, 3, 3, 4, 5, 6])

    def test_ignora_acentos_y_mayusculas(self):
        # El caso real: la capa de CDLC trae 'Hormigón' con tilde.
        d = df(Material=["hormigón armado", "HORMIGON ARMADO", "  Hormigon Armado  "])
        self.assertEqual(list(material.calcular(d)), [4, 4, 4])

    def test_desconocido_va_a_cero(self):
        self.assertEqual(list(material.calcular(df(Material=["Adobe", None]))), [0, 0])

    def test_reporta_los_no_reconocidos(self):
        d = df(Material=["PVC", "Adobe", "Ladrillo", None, ""])
        self.assertEqual(material.materiales_no_reconocidos(d), ["Adobe", "Ladrillo"])


class TestObstrucciones(unittest.TestCase):
    def test_cero_una_o_mas(self):
        d = df(Obstrucciones=[0, 1, 2, 7])
        self.assertEqual(list(obstrucciones.calcular(d)), [1, 3, 6, 6])

    def test_sin_dato_va_a_uno_no_a_cero(self):
        # A diferencia de los otros CF, aca 'sin dato' se asume sin obstrucciones.
        d = df(Obstrucciones=[None, float("nan"), "no aplica"])
        self.assertEqual(list(obstrucciones.calcular(d)), [1, 1, 1])


class TestProbabilidadFalla(unittest.TestCase):
    """PACP: 2do char letra -> digito+1; 2do char digito -> 2 primeros /10."""

    def test_reglas_documentadas(self):
        d = df(PACP_Clasificacion=["5B", "3222", "0000", "4131", None, "", "5"])
        self.assertEqual(list(probabilidad_falla.calcular(d)),
                         [6.0, 3.2, 1.0, 4.1, 0, 0, 0])

    def test_autodetecta_la_columna_pacp(self):
        d = df(PACP_Estructural=["5B"])
        self.assertEqual(list(probabilidad_falla.calcular(d)), [6.0])

    def test_campo_explicito_manda(self):
        d = df(PACP_Estructural=["5B"], PACP_OYM=["2100"])
        self.assertEqual(list(probabilidad_falla.calcular(d, campo_pacp="PACP_OYM")), [2.1])


class TestRiesgo(unittest.TestCase):
    def test_producto(self):
        d = df(criticidad=[2.0, 3.0], PF=[3.0, 1.5])
        self.assertEqual(list(riesgo.calcular(d)), [6.0, 4.5])

    def test_cero_y_nulo_cuentan_como_uno(self):
        d = df(criticidad=[0.0, 4.0, None], PF=[5.0, 0.0, 2.0])
        self.assertEqual(list(riesgo.calcular(d)), [5.0, 4.0, 2.0])

    def test_usa_el_campo_de_criticidad_que_se_le_indique(self):
        d = df(CF=[2.0], PF=[3.0])
        self.assertEqual(list(riesgo.calcular(d, campo_criticidad="CF")), [6.0])


class TestCriticidad(unittest.TestCase):
    def test_todos_en_uno_da_uno_y_todos_en_seis_da_seis(self):
        for valor, esperado in ((1, 1.0), (6, 6.0)):
            d = df(**{p: [valor] for p in criticidad.PARAMS_DISPONIBLES})
            self.assertEqual(list(criticidad.calcular(d)), [esperado],
                             f"con todos los CF en {valor}")

    def test_los_pesos_por_defecto_suman_uno(self):
        total = sum(g["peso"] for g in criticidad.GRUPOS_DEFAULT.values())
        self.assertAlmostEqual(total, 1.0)

    def test_faltan_columnas_lo_dice(self):
        _, faltantes = criticidad.resolver_columnas(["CF_Diametro"],
                                                    criticidad.GRUPOS_DEFAULT)
        self.assertIn("CF_Material", faltantes)

    def test_clases_de_color_cubren_la_escala(self):
        limites = [lim for lim, _, _ in criticidad.CLASES_COLOR]
        self.assertEqual(limites, [1, 2, 3, 4, 5, 6])


class TestProfundidad(unittest.TestCase):
    """Rango '1.5=1; 2.5=2; 3.5=3; 4.5=4; 6=5'. La profundidad de un colector es
    la mayor de sus dos registros; la de un registro, la mayor de sus columnas."""

    def setUp(self):
        from shapely.geometry import Point
        self.col = gpd.GeoDataFrame(
            {"Registro_Inicial": [10, 20], "Registro_Final": [20, 30]},
            geometry=lineas(2), crs=CRS)
        self._punto = Point

    def _registros(self, **cols):
        base = {"ID": [10, 20, 30]}
        base.update(cols)
        return gpd.GeoDataFrame(
            base, geometry=[self._punto(x, 0) for x in (0, 10, 20)], crs=CRS)

    def test_alcanza_con_profundidad_inspeccionada(self):
        """Es lo unico que deja el paso de preparacion 'Actualizar Cota Zampeado'."""
        from cf_pf_core.calculos import profundidad
        r = self._registros(Profundidad_Inspeccionada=[1.2, 3.0, 5.0])
        self.assertEqual(list(profundidad.calcular(self.col, r)), [3, 5])

    def test_alcanza_con_profundidad_sola(self):
        from cf_pf_core.calculos import profundidad
        r = self._registros(PROFUNDIDAD=[1.2, 3.0, 5.0])
        self.assertEqual(list(profundidad.calcular(self.col, r)), [3, 5])

    def test_con_las_dos_toma_la_mayor(self):
        from cf_pf_core.calculos import profundidad
        r = self._registros(PROFUNDIDAD=[1.2, 3.0, 5.0],
                            Profundidad_Inspeccionada=[4.0, 1.0, 1.0])
        self.assertEqual(list(profundidad.calcular(self.col, r)), [4, 5])

    def test_sin_ninguna_dice_que_hacer(self):
        from cf_pf_core.calculos import profundidad
        with self.assertRaises(KeyError) as e:
            profundidad.calcular(self.col, self._registros())
        self.assertIn("Cota Zampeado", str(e.exception))


class TestProximidad(unittest.TestCase):
    """Rangos medioambientales '25=6; 50=5; 100=4; 200=3; 400=2'."""

    def setUp(self):
        self.rango = proximidad.RANGOS_MEDIOAMBIENTAL_DEFAULT
        self.col = gpd.GeoDataFrame({"id": [1]}, geometry=lineas(1), crs=CRS)

    def _clase(self, distancia):
        clase, _ = proximidad.calcular_detalle(
            self.col, objetivos([distancia]), self.rango)
        return int(clase.iloc[0])

    def test_bordes_de_rango_son_inclusivos(self):
        casos = [(10, 6), (25, 6), (25.1, 5), (50, 5), (99, 4),
                 (200, 3), (400, 2), (400.1, 1), (673.7, 1)]
        for distancia, esperada in casos:
            self.assertEqual(self._clase(distancia), esperada, f"a {distancia} m")

    def test_devuelve_la_distancia_real(self):
        _, dist = proximidad.calcular_detalle(
            self.col, objetivos([137.5]), self.rango)
        self.assertAlmostEqual(float(dist.iloc[0]), 137.5, places=6)

    def test_sin_objetivos_es_clase_uno(self):
        clase, dist = proximidad.calcular_detalle(
            self.col, objetivos([]), self.rango)
        self.assertEqual(int(clase.iloc[0]), 1)
        self.assertTrue(pd.isna(dist.iloc[0]))

    def test_geometria_vacia_no_rompe(self):
        vacio = gpd.GeoDataFrame({"id": [1]}, geometry=[None], crs=CRS)
        clase, dist = proximidad.calcular_detalle(
            vacio, objetivos([10]), self.rango)
        self.assertEqual(int(clase.iloc[0]), 1)
        self.assertTrue(pd.isna(dist.iloc[0]))

    def test_rango_invalido_protesta(self):
        with self.assertRaises(ValueError):
            proximidad.calcular_detalle(self.col, objetivos([10]), "sin sentido")

    def test_calcular_sigue_devolviendo_solo_la_clase(self):
        r = proximidad.calcular(self.col, objetivos([10]), self.rango)
        self.assertIsInstance(r, pd.Series)
        self.assertEqual(int(r.iloc[0]), 6)


if __name__ == "__main__":
    unittest.main()
