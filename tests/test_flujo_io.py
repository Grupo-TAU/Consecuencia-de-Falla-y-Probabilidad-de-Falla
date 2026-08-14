"""Orquestacion (flujo) e I/O de GeoPackage."""
import os
import tempfile
import unittest

import geopandas as gpd

from cf_pf_core import flujo, gpkg_io
from tests.helpers import CRS, colectores, lineas, objetivos


class TestPasosYConfig(unittest.TestCase):
    def test_cada_paso_declara_las_columnas_que_produce(self):
        for key, label, _req, _fn in flujo.PASOS:
            self.assertIn(key, flujo.COLUMNAS_POR_PASO,
                          f"el paso '{label}' no declara sus columnas")
            self.assertTrue(flujo.COLUMNAS_POR_PASO[key],
                            f"el paso '{label}' declara una lista vacia")

    def test_los_parametros_de_config_no_chocan(self):
        vistos = {}
        for seccion, campos in flujo.CONFIG_CAMPOS.items():
            for clave, _etiqueta, _default in campos:
                if clave in vistos and vistos[clave] != seccion:
                    self.fail(f"'{clave}' esta en '{seccion}' y en '{vistos[clave]}'")
                vistos[clave] = seccion

    def test_paso_desconocido_avisa_y_no_rompe(self):
        avisos = []
        flujo.correr(colectores(2), solo=["no_existe"],
                     log=lambda m, n: avisos.append((n, m)))
        self.assertTrue(any("desconocido" in m for _, m in avisos))

    def test_falta_de_capa_se_omite_con_aviso(self):
        avisos = []
        flujo.correr(colectores(2), solo=["prox_sitios"],
                     log=lambda m, n: avisos.append((n, m)))
        self.assertTrue(any(n == "warn" and "se omite" in m for n, m in avisos))

    def test_un_paso_que_falla_no_frena_a_los_demas(self):
        # 'profundidad' necesita Registros; se le pasa una capa inservible.
        avisos = []
        res = flujo.correr(
            colectores(2), registros=gpd.GeoDataFrame({"x": [1]},
                                                      geometry=lineas(1), crs=CRS),
            solo=["profundidad", "criticidad"],
            log=lambda m, n: avisos.append((n, m)))
        self.assertIn("criticidad", res.columns,
                      "criticidad tendria que haberse calculado igual")


class TestClaveYReenganche(unittest.TestCase):
    def test_resolver_clave_prefiere_la_indicada(self):
        col = colectores(2, clave="ELEMRED")
        col["ID"] = [9, 9]
        self.assertEqual(flujo.resolver_clave(col, "ID"), "ID")
        self.assertEqual(flujo.resolver_clave(col, None), "ELEMRED")

    def test_reenganche_trae_los_cf_de_la_corrida_anterior(self):
        col = gpd.GeoDataFrame({"ELEMRED": [1, 2]}, geometry=lineas(2), crs=CRS)
        base = gpd.GeoDataFrame(
            {"ELEMRED": [1, 2], **{p: [6, 6] for p in
                                   flujo.criticidad.PARAMS_DISPONIBLES}},
            geometry=lineas(2), crs=CRS)
        res = flujo.correr(col, solo=["criticidad"], base=base, clave="ELEMRED")
        self.assertEqual(list(res["criticidad"]), [6.0, 6.0])

    def test_clave_como_float_matchea_con_entero(self):
        """geopandas lee enteros con NULL como float: 123 y 123.0 son la misma clave."""
        col = gpd.GeoDataFrame({"ELEMRED": [1.0, 2.0]}, geometry=lineas(2), crs=CRS)
        base = gpd.GeoDataFrame(
            {"ELEMRED": [1, 2], **{p: [6, 6] for p in
                                   flujo.criticidad.PARAMS_DISPONIBLES}},
            geometry=lineas(2), crs=CRS)
        res = flujo.correr(col, solo=["criticidad"], base=base, clave="ELEMRED")
        self.assertEqual(list(res["criticidad"]), [6.0, 6.0])


class TestGpkgIO(unittest.TestCase):
    def setUp(self):
        self.out = os.path.join(tempfile.mkdtemp(), "salida.gpkg")

    def _leer(self):
        return gpkg_io.leer_capa(self.out, gpkg_io.LAYER_SALIDA_DEFAULT)

    def test_escribe_en_la_capa_de_resultados(self):
        res = flujo.correr(colectores(3), solo=["criticidad"])
        gpkg_io.escribir_resultados(res, self.out, clave="ELEMRED", reemplazar=True)
        self.assertEqual(gpkg_io.listar_capas(self.out),
                         [gpkg_io.LAYER_SALIDA_DEFAULT])
        self.assertEqual(len(self._leer()), 3)

    def test_calculo_individual_conserva_lo_anterior(self):
        col = colectores(3, PACP_Clasificacion=["5B", "3222", "0000"])
        gpkg_io.escribir_resultados(flujo.correr(col, solo=["criticidad"]),
                                    self.out, clave="ELEMRED", reemplazar=True)
        base = self._leer()
        gpkg_io.escribir_resultados(
            flujo.correr(col, solo=["pf"], base=base, clave="ELEMRED"),
            self.out, clave="ELEMRED")
        final = self._leer()
        self.assertIn("criticidad", final.columns, "se perdio la columna anterior")
        self.assertIn("PF", final.columns, "no se agrego la nueva")

    def test_no_pisa_otras_capas_del_geopackage(self):
        ajena = gpd.GeoDataFrame({"a": [1]}, geometry=lineas(1), crs=CRS)
        ajena.to_file(self.out, layer="otra_cosa", driver="GPKG")
        gpkg_io.escribir_resultados(flujo.correr(colectores(2), solo=["criticidad"]),
                                    self.out, clave="ELEMRED", reemplazar=True)
        self.assertIn("otra_cosa", gpkg_io.listar_capas(self.out))
        self.assertEqual(len(gpd.read_file(self.out, layer="otra_cosa")), 1)

    def test_resolver_capa_pide_eleccion_si_hay_varias(self):
        gpd.GeoDataFrame({"a": [1]}, geometry=lineas(1), crs=CRS).to_file(
            self.out, layer="una", driver="GPKG")
        gpd.GeoDataFrame({"a": [1]}, geometry=lineas(1), crs=CRS).to_file(
            self.out, layer="otra", driver="GPKG")
        with self.assertRaises(ValueError) as e:
            gpkg_io.resolver_capa(self.out)
        self.assertIn("varias", str(e.exception).lower())

    def test_archivo_inexistente_no_explota(self):
        self.assertEqual(gpkg_io.listar_capas(os.path.join(self.out, "no_hay.gpkg")), [])


class TestVisualizador(unittest.TestCase):
    def test_genera_html_autonomo(self):
        from cf_pf_core import visualizador
        res = flujo.correr(colectores(4), solo=["criticidad"])
        destino = os.path.join(tempfile.mkdtemp(), "vis.html")
        visualizador.generar_html(res, destino)
        with open(destino, encoding="utf-8") as fh:
            html = fh.read()
        self.assertGreater(len(html), 1000)
        for _lim, color, _etq in flujo.criticidad.CLASES_COLOR:
            self.assertIn(color.lower(), html.lower(),
                          f"falta el color {color} de la simbologia")

    def test_verde_abajo_y_rojo_arriba(self):
        """La paleta va de criticidad baja (verde) a alta (rojo), no al reves."""
        from cf_pf_core.calculos import criticidad as C
        primero = C.CLASES_COLOR[0][1].lower()
        ultimo = C.CLASES_COLOR[-1][1].lower()
        self.assertIn("verde", C.CLASES_COLOR[0][2].lower())
        self.assertIn("rojo", C.CLASES_COLOR[-1][2].lower())
        # verde: componente G mayor que R; rojo: al reves
        self.assertGreater(int(primero[3:5], 16), int(primero[1:3], 16))
        self.assertGreater(int(ultimo[1:3], 16), int(ultimo[3:5], 16))

    def test_encuentra_las_columnas_en_minuscula(self):
        """Las capas de distintas intendencias traen 'diametro' o 'DIAMETRO'.
        El tooltip tiene que resolverlas igual, o pierde los valores crudos."""
        import json
        import re

        from cf_pf_core import visualizador
        from cf_pf_core.calculos import criticidad as C
        datos = {p: [1, 4, 6] for p in C.PARAMS_DISPONIBLES}
        datos.update(elemred=[1, 2, 3], diametro=[200.0, 300.0, 400.0],
                     antiguedad=[26, 30, 12], material=["PVC", "PVC", "HA"],
                     longitud=[54.1, 49.9, 33.2])
        gdf = gpd.GeoDataFrame(datos, geometry=lineas(3), crs=CRS)

        destino = os.path.join(tempfile.mkdtemp(), "min.html")
        visualizador.generar_html(gdf, destino)
        with open(destino, encoding="utf-8") as fh:
            doc = re.search(r'type="application/json"[^>]*>(.*?)</script>',
                            fh.read(), re.S).group(1)
        pares = max((json.loads(m) for m in
                     re.findall(r'"tooltips":\s*(\[\[.*?\]\])', doc, re.S)), key=len)
        plantillas = " ".join(p for _e, p in pares)
        for col in ("elemred", "diametro", "antiguedad", "material", "longitud"):
            self.assertIn(col, plantillas, f"no encontro la columna '{col}'")

    def test_muestra_la_suma_de_pesos(self):
        from cf_pf_core import visualizador
        res = flujo.correr(colectores(3), solo=["criticidad"])
        destino = os.path.join(tempfile.mkdtemp(), "suma.html")
        visualizador.generar_html(res, destino)
        with open(destino, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("Suma de pesos", html)
        self.assertIn("100%", html, "con los pesos por defecto tiene que dar 100%")

    def test_adjuntar_crudos_encuentra_minusculas(self):
        from cf_pf_core import visualizador
        res = flujo.correr(colectores(3), solo=["criticidad"])
        fuente = gpd.GeoDataFrame(
            {"elemred": [1, 2, 3], "diametro": [200, 300, 400]},
            geometry=lineas(3), crs=CRS)
        con_crudos = visualizador.adjuntar_crudos(res, fuente)
        self.assertIn("diametro", con_crudos.columns)
        self.assertEqual(len(con_crudos), 3)

    def test_adjuntar_crudos_no_multiplica_filas(self):
        from cf_pf_core import visualizador
        res = flujo.correr(colectores(3), solo=["criticidad"])
        fuente = gpd.GeoDataFrame(
            {"ELEMRED": [1, 1, 2, 3], "DIAMETRO": [200, 200, 300, 400]},
            geometry=lineas(4), crs=CRS)
        con_crudos = visualizador.adjuntar_crudos(res, fuente)
        self.assertEqual(len(con_crudos), len(res))
        self.assertIn("DIAMETRO", con_crudos.columns)


if __name__ == "__main__":
    unittest.main()
