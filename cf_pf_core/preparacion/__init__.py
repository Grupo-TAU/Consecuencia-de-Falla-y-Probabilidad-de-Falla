"""
Pasos de preparacion de datos.

Son los unicos pasos del core que ESCRIBEN sobre las capas reales de Colectores
y Registros: completan campos que quedan vacios y que despues necesitan los
calculos de Consecuencia de Falla. El resto del core (cf_pf_core.calculos) solo
lee la fuente y deja los resultados en la capa aparte DatosConsecuenciaDeFalla.

Orden recomendado: asignar_registros → cota_zampeado → colectores_cota_pendiente.
Cada paso es idempotente: no pisa lo que ya viene cargado.

Igual que en cf_pf_core.flujo, los pasos se registran en PASOS para que la app y
los scripts los recorran de forma uniforme, y CONFIG_CAMPOS describe que columnas
puede reconfigurar el usuario.
"""
import inspect

from cf_pf_core.preparacion import (
    asignar_registros,
    colectores_cota_pendiente,
    cota_zampeado,
)
from cf_pf_core.preparacion.gpkg_edit import PreparacionError

__all__ = [
    "PASOS", "PASOS_POR_KEY", "CONFIG_CAMPOS", "CAMPOS_COMUNES",
    "ETIQUETAS_PASO", "PreparacionError", "correr",
    "asignar_registros", "cota_zampeado", "colectores_cota_pendiente",
]


# Columnas que comparten varios pasos: se configuran una sola vez.
# (clave, etiqueta, valor_default) — la clave es el nombre del parametro de ejecutar().
CAMPOS_COMUNES = [
    ("campo_reg_ini", "Columna Registro Inicial (Colectores)",
     asignar_registros.CAMPO_REG_INI_DEFAULT),
    ("campo_reg_fin", "Columna Registro Final (Colectores)",
     asignar_registros.CAMPO_REG_FIN_DEFAULT),
    ("campo_id_reg", "Columna ID (Registros)",
     asignar_registros.CAMPO_ID_REG_DEFAULT),
    ("campo_cota_zamp", "Columna Cota Zampeado Calculada (Registros)",
     cota_zampeado.CAMPO_COTA_ZAMP_DEFAULT),
    ("campo_prof_inspec", "Columna Profundidad Inspeccionada (Registros)",
     cota_zampeado.CAMPO_PROF_INSPEC_DEFAULT),
]

# (key, label, fn, campos_propios)
PASOS = [
    (
        "asignar_registros",
        "Asignar Registro Inicial y Final (Colectores)",
        asignar_registros.ejecutar,
        [("tolerancia", "Tolerancia de busqueda (m)", asignar_registros.TOLERANCIA_DEFAULT)],
    ),
    (
        "cota_zampeado",
        "Actualizar Cota Zampeado (Registros)",
        cota_zampeado.ejecutar,
        [
            ("campo_cota_tapa", "Columna Cota Tapa Inspeccionada (Registros)",
             cota_zampeado.CAMPO_COTA_TAPA_DEFAULT),
            ("campo_zarriba", "Columna ZARRIBA (Colectores)",
             cota_zampeado.CAMPO_ZARRIBA_DEFAULT),
        ],
    ),
    (
        "colectores_cota_pendiente",
        "Completar Cotas y Pendiente (Colectores)",
        colectores_cota_pendiente.ejecutar,
        [
            ("campo_longitud", "Columna Longitud (Colectores, solo lectura)",
             colectores_cota_pendiente.CAMPO_LONGITUD_DEFAULT),
            ("campo_cota_ini", "Columna Cota Zampeado Inicial (Colectores)",
             colectores_cota_pendiente.CAMPO_COTA_INI_DEFAULT),
            ("campo_cota_fin", "Columna Cota Zampeado Final (Colectores)",
             colectores_cota_pendiente.CAMPO_COTA_FIN_DEFAULT),
            ("campo_pendiente", "Columna Pendiente (Colectores)",
             colectores_cota_pendiente.CAMPO_PENDIENTE_DEFAULT),
            ("campo_prof_salto", "Columna Prof. Salto (Colectores, vacio = sin ajuste)",
             colectores_cota_pendiente.CAMPO_PROF_SALTO_DEFAULT),
        ],
    ),
]

PASOS_POR_KEY = {p[0]: p for p in PASOS}
CONFIG_CAMPOS = {p[0]: p[3] for p in PASOS}
ETIQUETAS_PASO = {p[0]: p[1] for p in PASOS}


def _parametros(fn):
    """Nombres de parametro que acepta ejecutar(), para filtrar la config."""
    return set(inspect.signature(fn).parameters)


def correr(key, gpkg_col=None, gpkg_reg=None, layer_col=None, layer_reg=None,
           config=None, log=None):
    """Ejecuta un paso de preparacion.

    config es un dict plano de {nombre_de_parametro: valor}; se le pasan al paso
    solo las claves que acepta, asi la app puede mantener una sola config para
    todos los pasos (las columnas comunes quedan consistentes entre pasos).

    Devuelve el dict de resumen del paso. Lanza PreparacionError si no puede
    completarse.
    """
    if key not in PASOS_POR_KEY:
        raise PreparacionError(f"Paso de preparacion desconocido: '{key}'")
    _key, _label, fn, _campos = PASOS_POR_KEY[key]

    # Se filtra solo None (clave no provista). El string vacio SI se pasa: en los
    # campos opcionales significa "no usar esta columna" (p.ej. campo_prof_salto).
    aceptados = _parametros(fn)
    extra = {k: v for k, v in (config or {}).items()
             if k in aceptados and v is not None}
    return fn(gpkg_col=gpkg_col, gpkg_reg=gpkg_reg,
              layer_col=layer_col, layer_reg=layer_reg, log=log, **extra)
