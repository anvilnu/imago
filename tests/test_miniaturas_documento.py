"""Regresiones de invalidación y caché de miniaturas de documentos."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from widgets.canvas import Canvas
from widgets.tab_thumbnails import TabThumbnailBar


_APP = QApplication.instance() or QApplication([])


class _CanvasFalso(QWidget):
    contenido_visual_cambiado = Signal()

    def __init__(self):
        super().__init__()
        self.confirmaciones = 0

    def confirmar_miniatura_actualizada(self):
        self.confirmaciones += 1


class _VentanaFalsa(QWidget):
    def __init__(self, canvases):
        super().__init__()
        self.tabs = QTabWidget()
        self.tooltips = []
        for numero, canvas in enumerate(canvases):
            marker = QWidget()
            marker.canvas = canvas
            self.tabs.addTab(marker, f"Documento {numero}")

    def update_tab_tooltip(self, index, preview=None):
        self.tooltips.append((index, preview))


def _preview():
    imagen = QImage(120, 80, QImage.Format_ARGB32)
    imagen.fill(Qt.red)
    return QPixmap.fromImage(imagen)


class MiniaturasDocumentoTests(unittest.TestCase):
    def test_rebuild_reutiliza_la_vista_previa_existente(self):
        canvas = _CanvasFalso()
        ventana = _VentanaFalsa([canvas])
        barra = TabThumbnailBar(ventana)

        with patch.object(barra, "_make_preview", side_effect=lambda _: _preview()) as crear:
            barra.rebuild()
            barra.rebuild()

        self.assertEqual(crear.call_count, 1)
        self.assertEqual(canvas.confirmaciones, 1)

    def test_cambios_en_rafaga_se_agrupan_y_en_reposo_no_hay_sondeo(self):
        canvas = _CanvasFalso()
        ventana = _VentanaFalsa([canvas])
        barra = TabThumbnailBar(ventana)
        barra.REFRESH_MS = 30
        barra._refresh_timer.setInterval(barra.REFRESH_MS)

        with patch.object(barra, "_make_preview", side_effect=lambda _: _preview()) as crear:
            barra.rebuild()
            for _ in range(8):
                canvas.contenido_visual_cambiado.emit()
            self.assertEqual(crear.call_count, 1)
            QTest.qWait(60)
            self.assertEqual(crear.call_count, 2)
            QTest.qWait(60)
            self.assertEqual(crear.call_count, 2)

    def test_huella_ignora_historial_sin_cambio_visual(self):
        canvas = Canvas(8, 8)
        canvas.confirmar_miniatura_actualizada()
        avisos = []
        canvas.contenido_visual_cambiado.connect(lambda: avisos.append(True))

        canvas._on_history_changed()
        self.assertEqual(avisos, [])

        canvas.layers[0].image.fill(Qt.blue)
        canvas._on_history_changed()
        self.assertEqual(avisos, [True])


if __name__ == "__main__":
    unittest.main()
