from qgis.core import QgsApplication
from .provider import ColectoresRiesgoProvider


class ColectoresRiesgoPlugin:
    """Clase principal del plugin. Registra y desregistra el provider de Processing."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None

    def initProcessing(self):
        """Registra el provider.

        QGIS de escritorio arranca el plugin por initGui(); qgis_process (headless)
        lo arranca por initProcessing() y ni siquiera lo carga si el metodo no
        existe. Como el plugin no aporta nada de GUI, los dos caminos hacen esto.
        """
        if self.provider is None:
            self.provider = ColectoresRiesgoProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
