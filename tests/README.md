# Laboratorio de tests

Chequea que los cálculos den lo que tienen que dar, sin revisar capas a mano.

## Cómo correrlo

Desde la raíz del repo:

```powershell
python -m unittest discover -s tests -t .
```

Con detalle de cada test:

```powershell
python -m unittest discover -s tests -t . -v
```

Un solo archivo, o una sola clase:

```powershell
python -m unittest tests.test_calculos
python -m unittest tests.test_invariantes.TestOrdenDeLasFilas
```

No hace falta instalar nada: usa `unittest` de la biblioteca estándar. Si algún
día instalás `pytest`, levanta estos mismos archivos sin cambiarlos.

## Qué hay adentro

| Archivo | Qué cubre |
|---|---|
| `test_calculos.py` | Valores exactos de cada cálculo: bordes de rango, "sin dato", campos ausentes. Los esperados salen de la documentación de cada módulo, no de copiar la salida. |
| `test_invariantes.py` | Propiedades que valen siempre. **Cada test acá es un bug que ya ocurrió.** |
| `test_flujo_io.py` | Orquestación (pasos salteados, reenganche, clave) y GeoPackage (escritura, capas múltiples). |
| `test_regresion_cdlc.py` | Contra los datos reales de Ciudad de la Costa. Se saltea solo si no hay acceso a G:. |

## Los datos de referencia

`test_regresion_cdlc.py` busca Ciudad de la Costa en la ruta de Drive del
proyecto. Para usar otra copia (por ejemplo local, que es más rápido):

```powershell
$env:CF_PF_DATOS_CDLC = "D:\datos\ciudad_de_la_costa"
python -m unittest tests.test_regresion_cdlc
```

Si la ruta no existe, esos tests se saltean y el resto corre igual. Así la suite
funciona en cualquier máquina, con o sin Drive montado.

## Al agregar un cálculo nuevo

1. Un test de valores en `test_calculos.py`: los bordes de cada rango, el "sin
   dato" y qué pasa si falta la columna.
2. Si el cálculo recorre otra capa, un test en `test_invariantes.py` que
   compruebe que **el orden de las filas no cambia el resultado**. Es el error
   que ya nos pasó con proximidad y no da la cara solo.

## Por qué los invariantes importan más que los valores

Un test de valor te dice que `_clasificar(250)` da 2. Un invariante te dice que
*ningún* dato de entrada puede hacer que la capa cambie de cantidad de filas, o
que reordenar una capa auxiliar cambie el resultado. Los cuatro bugs que
encontramos en agosto de 2026 —proximidad dependiente del orden, filas
multiplicándose al escribir, claves vacías cruzándose entre sí y la paleta
invertida— eran todos invariantes rotos, y ninguno se veía en un valor puntual.
