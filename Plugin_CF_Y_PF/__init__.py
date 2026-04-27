from .plugin import ColectoresRiesgoPlugin


def classFactory(iface):
    return ColectoresRiesgoPlugin(iface)
