"""Regresiones de la caché regional capa×máscara."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication

import models.layer as modulo_layer
from models.layer import Layer
from tools.commands import PaintCommand
from widgets.canvas import Canvas


_APP = QApplication.instance() or QApplication([])


def _capa_con_mascara(ancho=240, alto=160):
    capa = Layer(ancho, alto, "Enmascarada")
    capa.image.fill(QColor(40, 80, 120, 200))
    capa.mask = QImage(ancho, alto, QImage.Format_Grayscale8)
    capa.mask.fill(255)
    capa.render_image()
    return capa


def _rellenar(imagen, rect, valor):
    if isinstance(valor, int):
        valor = QColor(valor, valor, valor)
    painter = QPainter(imagen)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_Source)
    painter.fillRect(rect, valor)
    painter.end()


class CacheMascaraRegionalTests(unittest.TestCase):
    def test_editar_mascara_parchea_roi_sin_recomponer_documento(self):
        capa = _capa_con_mascara()
        zona = QRect(90, 60, 14, 12)
        _rellenar(capa.mask, zona, 128)

        with patch.object(
                modulo_layer, "_apply_mask_to_image",
                side_effect=AssertionError("recomposición completa")):
            self.assertTrue(
                capa.actualizar_cache_mascara_region(zona, target="mask"))
            resultado = capa.render_image()

        self.assertEqual(resultado.pixelColor(95, 65).alpha(), 100)
        self.assertEqual(resultado.pixelColor(10, 10).alpha(), 200)

    def test_editar_imagen_enmascarada_tambien_parchea_solo_roi(self):
        capa = _capa_con_mascara()
        capa.mask.fill(128)
        capa.render_image()
        zona = QRect(30, 25, 10, 9)
        nuevo = QColor(210, 30, 20, 128)
        _rellenar(capa.image, zona, nuevo)

        with patch.object(
                modulo_layer, "_apply_mask_to_image",
                side_effect=AssertionError("recomposición completa")):
            self.assertTrue(
                capa.actualizar_cache_mascara_region(zona, target="image"))
            resultado = capa.render_image()

        dentro = resultado.pixelColor(34, 28)
        self.assertEqual((dentro.red(), dentro.green(), dentro.blue()),
                         (nuevo.red(), nuevo.green(), nuevo.blue()))
        self.assertEqual(dentro.alpha(), 64)
        self.assertEqual(resultado.pixelColor(5, 5).alpha(), 100)

    def test_dos_entradas_modificadas_fuerzan_respaldo_completo(self):
        capa = _capa_con_mascara()
        zona = QRect(50, 40, 8, 8)
        _rellenar(capa.image, zona, QColor(200, 10, 10, 180))
        _rellenar(capa.mask, zona, 80)

        self.assertFalse(
            capa.actualizar_cache_mascara_region(zona, target="mask"))
        original = modulo_layer._apply_mask_to_image
        with patch.object(modulo_layer, "_apply_mask_to_image",
                          wraps=original) as recomponer:
            capa.render_image()
        recomponer.assert_called_once()

    def test_canvas_conecta_roi_de_mascara_con_su_cache_interna(self):
        canvas = Canvas(320, 200)
        capa = canvas.layers[0]
        capa.mask = QImage(320, 200, QImage.Format_Grayscale8)
        capa.mask.fill(255)
        capa.render_image()
        canvas._cache_valid_region = QRegion(QRect(0, 0, 320, 200))
        canvas._last_cache_state = canvas._huella_visual()
        zona = QRect(140, 90, 16, 14)
        _rellenar(capa.mask, zona, 0)

        with patch.object(
                modulo_layer, "_apply_mask_to_image",
                side_effect=AssertionError("recomposición completa")):
            self.assertTrue(canvas.actualizar_region_pintada(
                zona, layer_index=0, target="mask"))
            resultado = capa.render_image()

        self.assertEqual(resultado.pixelColor(145, 95).alpha(), 0)
        self.assertEqual(resultado.pixelColor(20, 20).alpha(), 255)
        self.assertFalse(
            canvas._cache_valid_region.contains(QPoint(145, 95)))

    def test_deshacer_y_rehacer_preservan_cache_exterior_al_parche(self):
        canvas = Canvas(180, 120)
        capa = canvas.layers[0]
        capa.mask = QImage(180, 120, QImage.Format_Grayscale8)
        capa.mask.fill(255)
        capa.render_image()
        antes = QImage(capa.mask)
        despues = QImage(capa.mask)
        zona = QRect(70, 45, 12, 10)
        _rellenar(despues, zona, 0)
        comando = PaintCommand(
            canvas, 0, antes, despues, target="mask", dirty_rect=zona)

        with patch.object(
                modulo_layer, "_apply_mask_to_image",
                side_effect=AssertionError("recomposición completa")):
            canvas.undo_stack.push(comando)
            self.assertEqual(capa.render_image().pixelColor(75, 50).alpha(), 0)
            canvas.undo_stack.undo()
            self.assertEqual(
                capa.render_image().pixelColor(75, 50).alpha(), 255)
            canvas.undo_stack.redo()
            self.assertEqual(capa.render_image().pixelColor(75, 50).alpha(), 0)


if __name__ == "__main__":
    unittest.main()
