"""Regresiones de invalidación y caché de miniaturas del panel de capas."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from widgets.canvas import Canvas
from widgets.layers_panel import LayersPanel


_APP = QApplication.instance() or QApplication([])


class _EfectoFalso:
    activo = True

    def __init__(self, revision=0):
        self.revision = revision

    def fingerprint(self):
        return "efecto_falso", self.revision


class MiniaturasCapasTests(unittest.TestCase):
    def _panel_con_dos_capas(self):
        lienzo = Canvas(24, 18)
        lienzo.layers[0].image.fill(QColor(Qt.white))
        lienzo.add_new_layer()
        lienzo.layers[1].image.fill(QColor(Qt.transparent))
        panel = LayersPanel(lienzo)
        panel._thumb_timer.setInterval(20)
        panel.show()
        _APP.processEvents()
        self.addCleanup(panel.close)
        return lienzo, panel

    def test_en_reposo_no_hay_sondeo_y_solo_cambia_una_fila(self):
        lienzo, panel = self._panel_con_dos_capas()

        with patch.object(panel, "_thumb_pixmap",
                          wraps=panel._thumb_pixmap) as crear:
            QTest.qWait(50)
            self.assertEqual(crear.call_count, 0)

            lienzo.layers[0].image.fill(QColor(Qt.red))
            lienzo.contenido_visual_cambiado.emit()
            QTest.qWait(50)
            self.assertEqual(crear.call_count, 1)

            lienzo.contenido_visual_cambiado.emit()
            QTest.qWait(50)
            self.assertEqual(crear.call_count, 1)

    def test_cambio_de_mascara_no_recrea_la_miniatura_principal(self):
        lienzo = Canvas(24, 18)
        capa = lienzo.layers[0]
        capa.mask = QImage(24, 18, QImage.Format_Grayscale8)
        capa.mask.fill(255)
        panel = LayersPanel(lienzo)
        panel._thumb_timer.setInterval(20)
        panel.show()
        _APP.processEvents()
        self.addCleanup(panel.close)

        with (patch.object(panel, "_thumb_pixmap",
                           wraps=panel._thumb_pixmap) as crear_principal,
              patch.object(panel, "_mask_thumb_pixmap",
                           wraps=panel._mask_thumb_pixmap) as crear_mascara):
            capa.mask.fill(0)
            lienzo.contenido_visual_cambiado.emit()
            QTest.qWait(50)

        self.assertEqual(crear_principal.call_count, 0)
        self.assertEqual(crear_mascara.call_count, 1)

    def test_la_firma_detecta_cambios_en_efectos_activos(self):
        lienzo, panel = self._panel_con_dos_capas()
        capa = lienzo.layers[0]
        efecto = _EfectoFalso()
        capa.effects = [efecto]
        firma_inicial = panel._thumbnail_signatures(capa, 0)

        efecto.revision += 1

        self.assertNotEqual(
            firma_inicial, panel._thumbnail_signatures(capa, 0))

    def test_reconecta_la_senal_al_cambiar_de_canvas(self):
        lienzo_anterior, panel = self._panel_con_dos_capas()
        lienzo_nuevo = Canvas(16, 12)
        panel.canvas = lienzo_nuevo
        panel.update_layer_list()
        panel._thumb_refresh_pending = False

        lienzo_anterior.contenido_visual_cambiado.emit()
        self.assertFalse(panel._thumb_refresh_pending)

        lienzo_nuevo.contenido_visual_cambiado.emit()
        self.assertTrue(panel._thumb_refresh_pending)

    def test_aplica_al_mostrarse_un_cambio_recibido_oculto(self):
        lienzo, panel = self._panel_con_dos_capas()
        panel.hide()
        _APP.processEvents()

        with patch.object(panel, "_thumb_pixmap",
                          wraps=panel._thumb_pixmap) as crear:
            lienzo.layers[0].image.fill(QColor(Qt.blue))
            lienzo.contenido_visual_cambiado.emit()
            QTest.qWait(50)
            self.assertEqual(crear.call_count, 0)
            self.assertTrue(panel._thumb_refresh_pending)

            panel.show()
            QTest.qWait(50)
            self.assertEqual(crear.call_count, 1)
            self.assertFalse(panel._thumb_refresh_pending)


if __name__ == "__main__":
    unittest.main()
