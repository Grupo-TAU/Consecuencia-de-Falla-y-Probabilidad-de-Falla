"""CF Arboles: binario, la ausencia viene como NULL."""
import unittest

import pandas as pd

from cf_pf_core import flujo
from cf_pf_core.calculos import arboles, criticidad as C
from tests.helpers import colectores


class TestArboles(unittest.TestCase):
    def test_null_es_clase_1_y_con_arbol_clase_6(self):
        d = pd.DataFrame({"nro_arbol_5m": [None, 1, 2, 29]})
        self.assertEqual(list(arboles.calcular(d)), [1, 6, 6, 6])

    def test_un_cero_cuenta_como_sin_arbol(self):
        """La capa marca la ausencia con NULL, pero si llega un 0 significa lo mismo."""
        d = pd.DataFrame({"nro_arbol_5m": [0, 0.0, None]})
        self.assertEqual(list(arboles.calcular(d)), [1, 1, 1])

    def test_manda_la_cantidad_sobre_la_distancia(self):
        d = pd.DataFrame({"nro_arbol_5m": [None, 3], "dist_arbol": [2.5, None]})
        self.assertEqual(list(arboles.calcular(d)), [1, 6])

    def test_sin_cantidad_usa_la_distancia(self):
        """Una distancia cargada ya implica que se encontro un arbol; 0 m es un
        arbol pegado al colector, no un dato faltante."""
        d = pd.DataFrame({"dist_arbol": [None, 2.8, 0.0]})
        self.assertEqual(list(arboles.calcular(d)), [1, 6, 6])

    def test_las_clases_son_configurables(self):
        d = pd.DataFrame({"nro_arbol_5m": [None, 1]})
        self.assertEqual(list(arboles.calcular(d, clase_con=4, clase_sin=2)), [2, 4])

    def test_sin_columnas_dice_cuales_busco(self):
        with self.assertRaises(KeyError) as e:
            arboles.calcular(pd.DataFrame({"otra": [1]}))
        self.assertIn("nro_arbol_5m", str(e.exception))

    def test_mayusculas_indistintas(self):
        d = pd.DataFrame({"NRO_ARBOL_5M": [None, 1]})
        self.assertEqual(list(arboles.calcular(d)), [1, 6])

    def test_resumen_cuenta_los_afectados(self):
        d = pd.DataFrame({"nro_arbol_5m": [None, 1, 2, None, None]})
        self.assertEqual(arboles.resumen(d), (2, 3))


class TestArbolesEnElFlujo(unittest.TestCase):
    def test_el_paso_produce_la_columna(self):
        col = colectores(3, nro_arbol_5m=[None, 1, 5])
        res = flujo.correr(col, solo=["arboles"])
        self.assertEqual(list(res["CF_Arboles"]), [1, 6, 6])

    def test_esta_en_su_grupo_pero_con_peso_cero(self):
        self.assertIn("Arboles", C.GRUPOS_DEFAULT)
        self.assertEqual(C.GRUPOS_DEFAULT["Arboles"]["peso"], 0.0)
        self.assertEqual(C.GRUPOS_DEFAULT["Arboles"]["params"], ["CF_Arboles"])
        self.assertIn("CF_Arboles", C.PARAMS_DISPONIBLES)

    def test_con_peso_cero_no_cambia_la_criticidad(self):
        col = colectores(2, nro_arbol_5m=[None, 5])
        res = flujo.correr(col, solo=["arboles", "criticidad"])
        self.assertEqual(list(res["CF_Arboles"]), [1, 6])
        self.assertEqual(res["criticidad"].iloc[0], res["criticidad"].iloc[1],
                         "con peso 0 el arbol no puede mover la criticidad")

    def test_un_grupo_sin_peso_no_exige_su_columna(self):
        """Es lo que permite que el grupo exista sin romper Ciudad de la Costa ni
        Arteaga, que no tienen datos de arboles."""
        import pandas as pd
        sin_arboles = pd.DataFrame(
            {p: [3] for p in C.PARAMS_DISPONIBLES if p != "CF_Arboles"})
        self.assertEqual(list(C.calcular(sin_arboles)), [3.0])

    def test_grupos_activos_filtra_los_que_no_pesan(self):
        activos = C.grupos_activos(C.GRUPOS_DEFAULT)
        self.assertNotIn("Arboles", activos)
        self.assertIn("Valorizacion", activos)

    def test_al_darle_peso_empieza_a_influir(self):
        import copy
        grupos = copy.deepcopy(C.GRUPOS_DEFAULT)
        for nombre in grupos:
            if nombre != "Arboles":
                grupos[nombre]["peso"] = round(grupos[nombre]["peso"] * 0.9, 4)
        grupos["Arboles"]["peso"] = 0.10
        col = colectores(2, nro_arbol_5m=[None, 5])
        res = flujo.correr(col, solo=["arboles", "criticidad"],
                           config={"criticidad_grupos": grupos})
        self.assertLess(res["criticidad"].iloc[0], res["criticidad"].iloc[1],
                        "con peso, el tramo con arbol tiene que quedar mas critico")

    def test_una_capa_sin_arboles_sigue_calculando_criticidad(self):
        res = flujo.correr(colectores(3), solo=["criticidad"])
        self.assertEqual(len(res["criticidad"]), 3)

    def test_se_puede_sumar_a_un_grupo_por_configuracion(self):
        import copy
        grupos = copy.deepcopy(C.GRUPOS_DEFAULT)
        grupos["Valorizacion"]["params"].append("CF_Arboles")
        col = colectores(2, nro_arbol_5m=[None, 3])
        res = flujo.correr(col, solo=["arboles", "criticidad"],
                           config={"criticidad_grupos": grupos})
        self.assertEqual(list(res["CF_Arboles"]), [1, 6])
        self.assertLess(res["criticidad"].iloc[0], res["criticidad"].iloc[1],
                        "el tramo con arbol tiene que quedar mas critico")


if __name__ == "__main__":
    unittest.main()
