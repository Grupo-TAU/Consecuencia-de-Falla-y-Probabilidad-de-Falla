"""
Empaqueta e instala el plugin de QGIS con cf_pf_core adentro.

El plugin no trae ninguna logica propia: la toma de cf_pf_core, que en el repo
vive un nivel mas arriba (fuera de la carpeta del plugin). QGIS, en cambio, copia
solo la carpeta del plugin a su perfil, asi que ahi el core tiene que viajar
adentro. Este script arma esa copia: junta Plugin_CF_Y_PF + cf_pf_core en un
staging y de ahi instala o genera el .zip.

    python scripts/deploy_plugin.py                 # instala en el perfil default
    python scripts/deploy_plugin.py --perfil otro   # instala en otro perfil
    python scripts/deploy_plugin.py --zip           # solo genera el .zip
    python scripts/deploy_plugin.py --destino RUTA  # instala donde le digas
    python scripts/deploy_plugin.py --lanzamiento   # publica para los compañeros

Cada corrida reemplaza la version instalada. El staging queda en dist/ (ignorado
por git) para poder inspeccionar que se copio.

Despues de instalar hay que reiniciar QGIS (o desactivar/activar el plugin en el
Administrador de complementos): Python no recarga modulos ya importados.
"""
import argparse
import os
import re
import shutil
import stat
import sys
import time
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = "Plugin_CF_Y_PF"
CORE = "cf_pf_core"
# Carpeta versionada de la que baja QGIS: el download_url de plugins.xml apunta
# aca, con nombre FIJO (sin version), asi el XML no cambia de URL en cada release.
LANZAMIENTOS = "Lanzamientos"

# Basura de desarrollo que no tiene por que viajar al perfil de QGIS.
IGNORAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store")


def perfil_por_defecto():
    """Carpeta de plugins del perfil de QGIS segun el sistema operativo."""
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("APPDATA", ""), "QGIS", "QGIS3", "profiles")
    elif sys.platform == "darwin":
        base = os.path.expanduser(
            "~/Library/Application Support/QGIS/QGIS3/profiles")
    else:
        base = os.path.expanduser("~/.local/share/QGIS/QGIS3/profiles")
    return base


def carpeta_plugins(perfil):
    return os.path.join(perfil_por_defecto(), perfil, "python", "plugins")


def borrar_arbol(carpeta, intentos=5):
    """rmtree que aguanta Windows.

    En carpetas sincronizadas (OneDrive) o con el antivirus mirando, el borrado
    falla con 'Acceso denegado' aunque nada las tenga abiertas de verdad: se
    reintenta un rato antes de darse por vencido.
    """
    if not os.path.isdir(carpeta):
        return

    def _forzar(func, ruta, _exc):
        os.chmod(ruta, stat.S_IWRITE)
        func(ruta)

    for intento in range(intentos):
        try:
            shutil.rmtree(carpeta, onerror=_forzar)
            return
        except OSError:
            if intento == intentos - 1:
                raise
            time.sleep(0.5)


def armar_staging(destino_staging):
    """Copia el plugin y vendoriza el core adentro. Devuelve la ruta del staging."""
    borrar_arbol(destino_staging)

    shutil.copytree(os.path.join(RAIZ, PLUGIN), destino_staging, ignore=IGNORAR)
    shutil.copytree(os.path.join(RAIZ, CORE),
                    os.path.join(destino_staging, CORE), ignore=IGNORAR)
    return destino_staging


def verificar(staging):
    """Chequeos baratos que atrapan un empaquetado incompleto antes de instalar."""
    faltantes = [
        rel for rel in (
            "metadata.txt",
            "provider.py",
            "core_bridge.py",
            os.path.join("algorithms", "_base.py"),
            os.path.join("algorithms", "_base_preparacion.py"),
            os.path.join(CORE, "flujo.py"),
            os.path.join(CORE, "gpkg_io.py"),
            os.path.join(CORE, "calculos", "__init__.py"),
            os.path.join(CORE, "preparacion", "__init__.py"),
        )
        if not os.path.exists(os.path.join(staging, rel))
    ]
    if faltantes:
        raise SystemExit("ERROR: el paquete quedo incompleto, falta: "
                         + ", ".join(faltantes))

    # El core tiene que ser importable desde adentro del plugin, que es como lo
    # va a resolver core_bridge en QGIS.
    if not os.path.exists(os.path.join(staging, CORE, "__init__.py")):
        raise SystemExit(f"ERROR: {CORE} vendorizado sin __init__.py.")


def avisar_rutas_largas(carpeta_destino):
    """Avisa si la instalacion va a pasar el limite MAX_PATH de Windows.

    qgis_process.exe no maneja rutas de mas de 260 caracteres: los .py que se
    pasen quedan invisibles y el plugin falla al cargar con un
    ModuleNotFoundError que no dice nada del largo de la ruta.
    """
    if sys.platform != "win32":
        return
    largas = []
    raiz_plugin = os.path.join(RAIZ, PLUGIN)
    for carpeta, _dirs, archivos in os.walk(raiz_plugin):
        for archivo in archivos:
            rel = os.path.relpath(os.path.join(carpeta, archivo), raiz_plugin)
            final = os.path.join(carpeta_destino, PLUGIN, rel)
            if len(final) > 259:
                largas.append(final)
    if largas:
        print(f"AVISO: {len(largas)} archivo(s) van a quedar en rutas de mas de 260 "
              "caracteres; QGIS no va a poder importarlos.")
        print(f"  el mas largo ({len(max(largas, key=len))}): {max(largas, key=len)}")
        print("  Instala en una carpeta menos profunda.")


def instalar(staging, carpeta_destino):
    destino = os.path.join(carpeta_destino, PLUGIN)
    if not os.path.isdir(carpeta_destino):
        raise SystemExit(
            f"ERROR: no existe la carpeta de plugins '{carpeta_destino}'.\n"
            "Abri QGIS al menos una vez (crea el perfil) o pasa --destino.")
    borrar_arbol(destino)
    shutil.copytree(staging, destino, ignore=IGNORAR)
    return destino


def empaquetar_zip(staging, ruta_zip):
    """.zip con la carpeta del plugin en la raiz (formato que espera QGIS)."""
    os.makedirs(os.path.dirname(ruta_zip), exist_ok=True)
    if os.path.exists(ruta_zip):
        os.remove(ruta_zip)
    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for carpeta, _dirs, archivos in os.walk(staging):
            for archivo in archivos:
                completo = os.path.join(carpeta, archivo)
                interno = os.path.join(
                    PLUGIN, os.path.relpath(completo, staging))
                z.write(completo, interno)
    return ruta_zip


def leer_metadata(clave, default=""):
    """Un valor de metadata.txt. Es la unica fuente de verdad de la version."""
    ruta = os.path.join(RAIZ, PLUGIN, "metadata.txt")
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if linea.startswith(f"{clave}="):
                return linea.split("=", 1)[1].strip()
    return default


def version_plugin():
    return leer_metadata("version", "0.0.0")


def actualizar_plugins_xml(ruta_xml, version, qgis_min, qgis_max):
    """Sincroniza plugins.xml con metadata.txt.

    QGIS decide si hay actualizacion comparando el <version> de este XML contra
    la instalada. Si el numero no sube, nadie se entera de que hay algo nuevo por
    mas que el .zip haya cambiado. Y el numero vive en dos lugares (el atributo y
    el elemento): con editarlo a mano en uno solo alcanza para que no funcione.
    """
    with open(ruta_xml, encoding="utf-8") as f:
        xml = f.read()

    antes = xml
    xml = re.sub(r'(<pyqgis_plugin[^>]*\sversion=")[^"]*(")',
                 rf"\g<1>{version}\g<2>", xml)
    xml = re.sub(r"(<version>)[^<]*(</version>)", rf"\g<1>{version}\g<2>", xml)
    xml = re.sub(r"(<qgis_minimum_version>)[^<]*(</qgis_minimum_version>)",
                 rf"\g<1>{qgis_min}\g<2>", xml)
    xml = re.sub(r"(<qgis_maximum_version>)[^<]*(</qgis_maximum_version>)",
                 rf"\g<1>{qgis_max}\g<2>", xml)

    if xml != antes:
        with open(ruta_xml, "w", encoding="utf-8") as f:
            f.write(xml)
    return xml != antes


def url_de_descarga(ruta_xml):
    """El download_url declarado, para poder verificar que apunte al zip que
    acabamos de escribir."""
    with open(ruta_xml, encoding="utf-8") as f:
        m = re.search(r"<download_url>([^<]+)</download_url>", f.read())
    return m.group(1).strip() if m else ""


def publicar(staging):
    """Deja listo un lanzamiento: el .zip en Lanzamientos/ y plugins.xml al dia.

    Los compañeros no instalan desde el repo: tienen configurado plugins.xml como
    repositorio de complementos en QGIS, que baja el .zip del download_url. Los
    dos archivos tienen que moverse juntos y con el mismo numero de version, y
    hacerlo a mano es donde se cuela el error que no avisa: si la version no sube,
    QGIS simplemente no ofrece la actualizacion y nadie recibe nada.
    """
    version = version_plugin()
    qgis_min = leer_metadata("qgisMinimumVersion", "3.16")
    qgis_max = leer_metadata("qgisMaximumVersion", "4.99")

    ruta_zip = os.path.join(RAIZ, LANZAMIENTOS, f"{PLUGIN}.zip")
    empaquetar_zip(staging, ruta_zip)
    print(f"ZIP publicado: {ruta_zip} ({os.path.getsize(ruta_zip) // 1024} KB)")

    ruta_xml = os.path.join(RAIZ, "plugins.xml")
    if not os.path.isfile(ruta_xml):
        raise SystemExit(f"ERROR: no se encontro {ruta_xml}.")
    cambio = actualizar_plugins_xml(ruta_xml, version, qgis_min, qgis_max)
    print(f"plugins.xml -> version {version} "
          f"({'actualizado' if cambio else 'ya estaba al dia'})")

    # El download_url tiene que apuntar al archivo que acabamos de escribir: si
    # alguien lo cambia por un nombre con version, deja de encontrarlo en silencio.
    url = url_de_descarga(ruta_xml)
    esperado = f"{LANZAMIENTOS}/{PLUGIN}.zip"
    if esperado not in url.replace("\\", "/"):
        print(f"AVISO: el download_url no apunta a {esperado}:\n  {url}")

    print()
    print("Falta publicarlo: los compañeros lo bajan del repo, no de tu disco.")
    print(f"  git add {LANZAMIENTOS}/{PLUGIN}.zip plugins.xml "
          f"{PLUGIN}/metadata.txt")
    print(f'  git commit -m "Plugin v{version}"')
    print("  git push")
    print()
    print("Ellos: Complementos > Administrar e instalar > Buscar actualizaciones.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Empaqueta el plugin con cf_pf_core adentro y lo instala en QGIS.")
    p.add_argument("--perfil", default="default",
                   help="Perfil de QGIS donde instalar (default: default)")
    p.add_argument("--destino", default=None,
                   help="Carpeta de plugins destino (pisa --perfil)")
    p.add_argument("--zip", action="store_true",
                   help="Solo generar el .zip en dist/, sin instalar")
    p.add_argument("--lanzamiento", action="store_true",
                   help="Publicar: escribe Lanzamientos/ y sincroniza plugins.xml")
    args = p.parse_args(argv)

    dist = os.path.join(RAIZ, "dist")
    staging = armar_staging(os.path.join(dist, PLUGIN))
    verificar(staging)
    print(f"Empaquetado {PLUGIN} v{version_plugin()} con {CORE} vendorizado "
          f"-> {staging}")

    if args.lanzamiento:
        return publicar(staging)

    if args.zip:
        ruta = empaquetar_zip(
            staging, os.path.join(dist, f"{PLUGIN}-{version_plugin()}.zip"))
        print(f"OK. ZIP generado: {ruta}")
        print("Instalalo en QGIS con Complementos > Instalar a partir de un ZIP.")
        return 0

    carpeta = args.destino or carpeta_plugins(args.perfil)
    avisar_rutas_largas(carpeta)
    destino = instalar(staging, carpeta)
    print(f"OK. Instalado en {destino}")
    print("Reinicia QGIS (o desactiva y reactiva el plugin) para que tome los cambios.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
