"""Regresiones de los colores primario/secundario entre pestañas."""

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from widgets.colors_panel import ColorsPanel
from widgets.canvas import Canvas


_APP = QApplication.instance() or QApplication([])


class _Muestra:
    def __init__(self, color):
        self._color = QColor(color)

    def color(self):
        return QColor(self._color)


class ColoresEntrePestanasTests(unittest.TestCase):
    def test_activar_pestana_aplica_los_colores_globales_del_panel(self):
        primario = QColor(24, 130, 210, 190)
        secundario = QColor(230, 80, 35, 220)
        callback = object()
        panel = SimpleNamespace(
            preview_box=_Muestra(primario),
            secondary_box=_Muestra(secundario),
            on_color_picked=callback,
            _sync_mirror=lambda: None,
        )
        lienzo = Canvas(20, 16)
        lienzo.brush_color = QColor("#112233")
        lienzo.brush_color_secondary = QColor("#445566")

        ColorsPanel.sync_from_canvas(panel, lienzo)

        self.assertEqual(lienzo.brush_color, primario)
        self.assertEqual(lienzo.brush_color_secondary, secundario)
        self.assertIs(lienzo.color_picked_callback, callback)

    def test_dos_pestanas_no_restauran_sus_colores_antiguos(self):
        primario = QColor("#1976d2")
        secundario = QColor("#ffc107")
        panel = SimpleNamespace(
            preview_box=_Muestra(primario),
            secondary_box=_Muestra(secundario),
            on_color_picked=lambda *_args: None,
            _sync_mirror=lambda: None,
        )
        lienzo_a = Canvas(12, 10)
        lienzo_b = Canvas(12, 10)
        lienzo_a.brush_color = QColor("#aa0000")
        lienzo_b.brush_color = QColor("#00aa00")

        ColorsPanel.sync_from_canvas(panel, lienzo_a)
        ColorsPanel.sync_from_canvas(panel, lienzo_b)

        self.assertEqual(lienzo_a.brush_color, primario)
        self.assertEqual(lienzo_b.brush_color, primario)
        self.assertEqual(lienzo_a.brush_color_secondary, secundario)
        self.assertEqual(lienzo_b.brush_color_secondary, secundario)


if __name__ == "__main__":
    unittest.main()
