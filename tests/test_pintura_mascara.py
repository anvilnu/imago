"""Regresiones al pintar y representar una máscara de capa."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from tools.draw_tools import PenTool
from widgets.canvas import Canvas
from widgets.layers_panel import LayersPanel, _imagen_miniatura_capa


_APP = QApplication.instance() or QApplication([])


class _Evento:
    def __init__(self, x, y, boton=Qt.LeftButton, botones=Qt.LeftButton):
        self._posicion = QPointF(x, y)
        self._boton = boton
        self._botones = botones

    def position(self):
        return QPointF(self._posicion)

    def button(self):
        return self._boton

    def buttons(self):
        return self._botones

    def modifiers(self):
        return Qt.NoModifier


class PinturaMascaraTests(unittest.TestCase):
    def _lienzo_con_mascara(self):
        lienzo = Canvas(40, 30)
        capa = lienzo.layers[0]
        capa.image.fill(QColor(210, 45, 30, 255))
        self.assertTrue(lienzo.create_mask())
        lienzo.mask_edit_active = True
        lienzo.brush_color = QColor(Qt.black)
        lienzo.brush_size = 7
        return lienzo, capa

    def test_trazo_en_mascara_preserva_imagen_y_solo_modifica_mascara(self):
        lienzo, capa = self._lienzo_con_mascara()
        imagen_original = QImage(capa.image)
        pincel = PenTool(lienzo)

        pincel.mouse_press(_Evento(18, 14))
        pincel.mouse_release(_Evento(18, 14, botones=Qt.NoButton))

        self.assertEqual(capa.image, imagen_original)
        self.assertEqual(capa.mask.pixelColor(18, 14).red(), 0)
        self.assertEqual(capa.mask.pixelColor(2, 2).red(), 255)
        self.assertEqual(capa.render_image().pixelColor(18, 14).alpha(), 0)
        self.assertEqual(capa.render_image().pixelColor(2, 2).alpha(), 255)

        lienzo.undo_stack.undo()
        self.assertEqual(capa.image, imagen_original)
        self.assertEqual(capa.mask.pixelColor(18, 14).red(), 255)
        lienzo.undo_stack.redo()
        self.assertEqual(capa.image, imagen_original)
        self.assertEqual(capa.mask.pixelColor(18, 14).red(), 0)

    def test_miniatura_principal_ignora_la_mascara_separada(self):
        lienzo, capa = self._lienzo_con_mascara()
        capa.mask.fill(0)

        resultado_visible = capa.render_with_effects()
        miniatura_principal = _imagen_miniatura_capa(capa)

        self.assertEqual(resultado_visible.pixelColor(10, 10).alpha(), 0)
        self.assertEqual(miniatura_principal.pixelColor(10, 10),
                         QColor(210, 45, 30, 255))
        self.assertIs(miniatura_principal, capa.image)

    def test_invertir_mascara_es_deshacible_y_preserva_la_imagen(self):
        lienzo, capa = self._lienzo_con_mascara()
        imagen_original = QImage(capa.image)
        capa.mask.fill(64)

        self.assertTrue(lienzo.invert_mask())
        self.assertEqual(capa.mask.pixelColor(10, 10).red(), 191)
        self.assertEqual(capa.image, imagen_original)

        lienzo.undo_stack.undo()
        self.assertEqual(capa.mask.pixelColor(10, 10).red(), 64)
        self.assertEqual(capa.image, imagen_original)
        lienzo.undo_stack.redo()
        self.assertEqual(capa.mask.pixelColor(10, 10).red(), 191)
        self.assertEqual(capa.image, imagen_original)

    def test_boton_anade_mascara_blanca_y_la_activa(self):
        lienzo = Canvas(24, 18)
        panel = LayersPanel(lienzo)
        self.assertFalse(lienzo.layers[0].has_mask())
        self.assertTrue(panel.btn_mask.isEnabled())
        self.assertEqual(panel.btn_mask.size(), QSize(26, 26))

        panel.btn_mask.click()
        _APP.processEvents()

        self.assertTrue(lienzo.layers[0].has_mask())
        self.assertTrue(lienzo.mask_edit_active)
        self.assertEqual(lienzo.layers[0].mask.pixelColor(5, 5).red(), 255)
        self.assertFalse(panel.btn_mask.isEnabled())
        mask_label = panel._thumb_rows[0][3]
        self.assertIsNotNone(mask_label)
        self.assertEqual(mask_label.contextMenuPolicy(), Qt.CustomContextMenu)
        panel._thumb_timer.stop()
        panel.close()

    def test_boton_fusionar_todas_sustituye_a_los_de_reordenacion(self):
        lienzo = Canvas(24, 18)
        panel = LayersPanel(lienzo)
        self.assertFalse(hasattr(panel, "btn_up"))
        self.assertFalse(hasattr(panel, "btn_down"))
        self.assertFalse(panel.btn_flatten.isEnabled())

        lienzo.add_layer_undoable()
        _APP.processEvents()
        self.assertTrue(panel.btn_flatten.isEnabled())
        panel.btn_flatten.click()
        _APP.processEvents()

        self.assertEqual(len(lienzo.layers), 1)
        self.assertFalse(panel.btn_flatten.isEnabled())
        lienzo.undo_stack.undo()
        self.assertEqual(len(lienzo.layers), 2)
        panel._thumb_timer.stop()
        panel.close()


if __name__ == "__main__":
    unittest.main()
