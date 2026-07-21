"""Regresiones del estado inicial del panel Histograma."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from widgets.histogram_panel import HistogramaWidget


_APP = QApplication.instance() or QApplication([])


class _Ventana:
    def __init__(self, settings):
        self.settings = settings


class CanalHistogramaTests(unittest.TestCase):
    def test_rgb_es_el_canal_inicial_sin_preferencia_guardada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ajustes = QSettings(os.path.join(carpeta, "Imago.ini"),
                                QSettings.IniFormat)
            panel = HistogramaWidget(_Ventana(ajustes))
            self.assertEqual(panel.canal_combo.currentData(), "rgb")
            self.assertEqual(panel._vista._canal, "rgb")
            panel.close()

    def test_respeta_un_canal_elegido_en_una_sesion_anterior(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ajustes = QSettings(os.path.join(carpeta, "Imago.ini"),
                                QSettings.IniFormat)
            ajustes.setValue("histogram/canal", "lum")
            panel = HistogramaWidget(_Ventana(ajustes))
            self.assertEqual(panel.canal_combo.currentData(), "lum")
            self.assertEqual(panel._vista._canal, "lum")
            panel.close()


if __name__ == "__main__":
    unittest.main()
