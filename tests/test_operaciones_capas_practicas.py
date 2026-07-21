import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QFile, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainterPath
from PySide6.QtWidgets import QApplication

from models.layer import Layer, TextLayer
import recursos_rc  # noqa: F401  (registra los iconos nuevos)
from tools.numpy_utils import alpha_bounds
from widgets.canvas import Canvas


_APP = QApplication.instance() or QApplication([])


def _canvas(ancho, alto):
    canvas = Canvas(ancho, alto)
    canvas.layers[0].image.fill(Qt.transparent)
    return canvas


def _pixeles(image):
    return tuple(image.pixelColor(x, y).rgba()
                 for y in range(image.height())
                 for x in range(image.width()))


class OperacionesCapasPracticasTests(unittest.TestCase):
    def test_iconos_nuevos_estan_embebidos(self):
        for name in (
                "layer_copy_visible.png", "layer_new_visible.png",
                "layer_alpha_select.png", "layer_crop_content.png",
                "layer_center.png", "layer_clip.png"):
            with self.subTest(name=name):
                self.assertTrue(QFile.exists(":/icons/" + name))

    def test_copiar_visible_respeta_compuesto_y_seleccion(self):
        canvas = _canvas(5, 4)
        canvas.layers[0].image.fill(QColor("#c03020"))
        top = Layer(5, 4, "Superior")
        top.image.fill(Qt.transparent)
        top.image.setPixelColor(2, 1, QColor("#2050d0"))
        canvas.layers.append(top)
        canvas.active_layer_index = 1

        selection = QPainterPath()
        selection.addRect(QRectF(1, 1, 3, 1))
        canvas.selection = selection

        self.assertTrue(canvas.copy_visible())
        copied = QApplication.clipboard().image()
        self.assertEqual((copied.width(), copied.height()), (3, 1))
        self.assertEqual(copied.pixelColor(0, 0), QColor("#c03020"))
        self.assertEqual(copied.pixelColor(1, 0), QColor("#2050d0"))
        self.assertEqual(type(canvas).last_copy_info[0].x(), 1)

    def test_nueva_capa_desde_visible_conserva_fuentes_y_es_deshacible(self):
        canvas = _canvas(4, 3)
        canvas.layers[0].image.fill(QColor("#d04020"))
        top = Layer(4, 3, "Superior")
        top.image.fill(Qt.transparent)
        top.image.setPixelColor(1, 1, QColor("#2040d0"))
        top.opacity = 65
        canvas.layers.append(top)
        canvas.active_layer_index = 1
        original_layers = list(canvas.layers)
        expected = _pixeles(canvas.render_flat_image(Qt.transparent))

        self.assertTrue(canvas.new_layer_from_visible())
        self.assertEqual(len(canvas.layers), 3)
        created = canvas.layers[2]
        self.assertEqual(_pixeles(created.image), expected)
        self.assertEqual(canvas.layers[:2], original_layers)
        self.assertEqual(created.opacity, 100)

        canvas.undo_stack.undo()
        self.assertEqual(canvas.layers, original_layers)
        canvas.undo_stack.redo()
        self.assertIs(canvas.layers[2], created)

    def test_alfa_a_seleccion_incluye_mascara_y_deshace(self):
        canvas = _canvas(6, 4)
        layer = canvas.layers[0]
        layer.image.setPixelColor(1, 1, QColor("#ffffff"))
        layer.image.setPixelColor(4, 2, QColor("#ffffff"))
        layer.mask = QImage(6, 4, QImage.Format_Grayscale8)
        layer.mask.fill(255)
        layer.mask.setPixelColor(4, 2, QColor(0, 0, 0))
        previous = QPainterPath()
        previous.addRect(QRectF(0, 0, 1, 1))
        canvas.selection = previous

        self.assertTrue(canvas.selection_from_layer_alpha())
        self.assertTrue(canvas.selection.contains(QPointF(1.5, 1.5)))
        self.assertFalse(canvas.selection.contains(QPointF(4.5, 2.5)))

        canvas.undo_stack.undo()
        self.assertEqual(canvas.selection, previous)
        canvas.undo_stack.redo()
        self.assertTrue(canvas.selection.contains(QPointF(1.5, 1.5)))

    def test_recortar_al_contenido_ignora_capas_ocultas_y_deshace(self):
        canvas = _canvas(8, 6)
        visible = canvas.layers[0]
        visible.image.setPixelColor(2, 1, QColor("#ff0000"))
        visible.image.setPixelColor(5, 4, QColor("#0000ff"))
        hidden = Layer(8, 6, "Oculta")
        hidden.image.setPixelColor(7, 5, QColor("#ffffff"))
        hidden.visible = False
        canvas.layers.append(hidden)

        self.assertTrue(canvas.crop_to_content())
        self.assertEqual((canvas.base_width, canvas.base_height), (4, 4))
        self.assertEqual(visible.image.pixelColor(0, 0), QColor("#ff0000"))
        self.assertEqual(visible.image.pixelColor(3, 3), QColor("#0000ff"))
        self.assertEqual((hidden.image.width(), hidden.image.height()), (4, 4))

        canvas.undo_stack.undo()
        self.assertEqual((canvas.base_width, canvas.base_height), (8, 6))
        self.assertEqual(visible.image.pixelColor(2, 1), QColor("#ff0000"))
        canvas.undo_stack.redo()
        self.assertEqual((canvas.base_width, canvas.base_height), (4, 4))

    def test_centrar_capa_mueve_mascara_y_respeta_bloqueo(self):
        canvas = _canvas(9, 7)
        layer = canvas.layers[0]
        layer.image.setPixelColor(0, 0, QColor("#ff0000"))
        layer.image.setPixelColor(1, 0, QColor("#0000ff"))
        layer.mask = QImage(9, 7, QImage.Format_Grayscale8)
        layer.mask.fill(0)
        layer.mask.setPixelColor(0, 0, QColor(255, 255, 255))
        layer.mask.setPixelColor(1, 0, QColor(255, 255, 255))

        self.assertTrue(canvas.center_active_layer())
        self.assertEqual(layer.image.pixelColor(3, 3), QColor("#ff0000"))
        self.assertEqual(layer.image.pixelColor(4, 3), QColor("#0000ff"))
        self.assertEqual(layer.mask.pixelColor(3, 3).red(), 255)
        self.assertEqual(layer.mask.pixelColor(0, 0).red(), 0)

        canvas.undo_stack.undo()
        self.assertEqual(layer.image.pixelColor(0, 0), QColor("#ff0000"))
        self.assertEqual(layer.mask.pixelColor(0, 0).red(), 255)
        layer.position_locked = True
        count = canvas.undo_stack.count()
        self.assertFalse(canvas.center_active_layer())
        self.assertEqual(canvas.undo_stack.count(), count)

    def test_centrar_texto_conserva_la_capa_vectorial(self):
        canvas = _canvas(120, 60)
        layer = TextLayer(120, 60, "Texto")
        layer.set_text(
            '<span style="font-size: 14px; color: #ffffff;">Imago</span>',
            QPointF(2, 3))
        canvas.layers = [layer]
        canvas.active_layer_index = 0
        old_origin = QPointF(layer.text_origin)
        old_html = layer.text_html

        self.assertTrue(canvas.center_active_layer())
        bounds = alpha_bounds(layer.render_image())
        self.assertEqual(bounds.x(), (canvas.base_width - bounds.width()) // 2)
        self.assertEqual(bounds.y(), (canvas.base_height - bounds.height()) // 2)
        self.assertTrue(layer.is_text)
        self.assertEqual(layer.text_html, old_html)

        canvas.undo_stack.undo()
        self.assertEqual(layer.text_origin, old_origin)
        self.assertEqual(layer.text_html, old_html)


if __name__ == "__main__":
    unittest.main()
