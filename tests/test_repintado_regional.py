"""Regresiones del repintado regional durante herramientas de trazo."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QPainter, QRadialGradient,
                           QRegion)
from PySide6.QtWidgets import QApplication

from tools.draw_tools import PenTool
from widgets.canvas import Canvas


_APP = QApplication.instance() or QApplication([])


class _Evento:
    def __init__(self, x, y, boton=Qt.LeftButton, botones=Qt.LeftButton,
                 modificadores=Qt.NoModifier):
        self._pos = QPointF(x, y)
        self._boton = boton
        self._botones = botones
        self._modificadores = modificadores

    def position(self):
        return QPointF(self._pos)

    def button(self):
        return self._boton

    def buttons(self):
        return self._botones

    def modifiers(self):
        return self._modificadores


class _CanvasRegistro(Canvas):
    def __init__(self, ancho, alto):
        self.actualizaciones = []
        super().__init__(ancho, alto)
        self.actualizaciones.clear()

    def update(self, *args):
        self.actualizaciones.append(args)


def _preparar_cache(canvas):
    canvas._cache_valid_region = QRegion(
        QRect(0, 0, canvas.base_width, canvas.base_height))
    canvas._last_cache_state = canvas._huella_visual()


def _pintar_rect(canvas, rect, color=QColor(20, 40, 220, 255)):
    painter = QPainter(canvas.layers[0].image)
    painter.fillRect(rect, color)
    painter.end()


class RepintadoRegionalTests(unittest.TestCase):
    def test_conserva_cache_fuera_del_roi_y_actualiza_solo_su_pantalla(self):
        canvas = _CanvasRegistro(400, 300)
        _preparar_cache(canvas)
        zona = QRect(120, 80, 18, 14)
        _pintar_rect(canvas, zona)

        # La petición interactiva no debe recorrer todas las capas; la huella
        # completa se valida una sola vez en paintEvent.
        with patch.object(canvas, "_huella_visual",
                          side_effect=AssertionError("huella por evento")):
            parcial = canvas.actualizar_region_pintada(zona, layer_index=0)

        self.assertTrue(parcial)
        self.assertFalse(canvas._cache_valid_region.contains(QPoint(125, 85)))
        self.assertTrue(canvas._cache_valid_region.contains(QPoint(20, 20)))
        self.assertEqual(len(canvas.actualizaciones), 1)
        self.assertEqual(len(canvas.actualizaciones[0]), 1)
        actualizada = canvas.actualizaciones[0][0]
        self.assertLess(actualizada.width(), canvas.width() // 4)
        self.assertLess(actualizada.height(), canvas.height() // 4)

    def test_cambio_adicional_es_rechazado_al_validar_el_lote(self):
        canvas = _CanvasRegistro(200, 120)
        _preparar_cache(canvas)
        estado_anterior = canvas._last_cache_state
        zona = QRect(30, 25, 12, 10)
        _pintar_rect(canvas, zona)
        canvas.layers[0].opacity = 75

        parcial = canvas.actualizar_region_pintada(zona, layer_index=0)
        valido = canvas._huella_admite_cambios_locales(
            estado_anterior,
            canvas._huella_visual(),
            canvas._cambios_visuales_parciales_pendientes,
        )

        # La petición sigue siendo barata y regional; paintEvent descubre el
        # cambio simultáneo de opacidad y agenda su respaldo completo.
        self.assertTrue(parcial)
        self.assertFalse(valido)
        self.assertEqual(len(canvas.actualizaciones[0]), 1)

    def test_efecto_activo_usa_el_respaldo_completo(self):
        class _Efecto:
            activo = True

        canvas = _CanvasRegistro(200, 120)
        _preparar_cache(canvas)
        zona = QRect(50, 40, 10, 10)
        _pintar_rect(canvas, zona)
        canvas.layers[0].effects = [_Efecto()]

        parcial = canvas.actualizar_region_pintada(zona, layer_index=0)

        self.assertFalse(parcial)
        self.assertEqual(canvas.actualizaciones, [()])

    def test_pincel_repinta_el_segmento_actual_y_no_todo_el_trazo(self):
        canvas = _CanvasRegistro(320, 120)
        canvas.brush_size = 9
        _preparar_cache(canvas)
        pincel = PenTool(canvas)

        pincel.mouse_press(_Evento(20, 60))
        canvas.actualizaciones.clear()
        pincel.mouse_move(_Evento(160, 60))
        canvas.actualizaciones.clear()
        pincel.mouse_move(_Evento(170, 60))

        self.assertEqual(len(canvas.actualizaciones), 1)
        self.assertEqual(len(canvas.actualizaciones[0]), 1)
        segmento = canvas.actualizaciones[0][0]
        self.assertLess(segmento.width(), 35)
        self.assertGreater(segmento.left(), 145)

        pincel.mouse_release(_Evento(170, 60, botones=Qt.NoButton))

    def test_paint_event_recompone_el_roi_hasta_el_resultado_final(self):
        canvas = Canvas(80, 60)
        canvas.show()
        _APP.processEvents()
        zona = QRect(30, 20, 8, 7)
        color = QColor(15, 90, 210, 255)
        _pintar_rect(canvas, zona, color)

        self.assertTrue(canvas.actualizar_region_pintada(zona, layer_index=0))
        _APP.processEvents()

        self.assertTrue(canvas._cache_valid_region.contains(QPoint(33, 23)))
        self.assertEqual(canvas._composed_cache.pixelColor(33, 23), color)
        self.assertEqual(
            canvas._composed_cache.pixelColor(5, 5), QColor(Qt.white))
        canvas.close()

    def test_punta_cacheada_de_mascara_conserva_pixeles_del_gradiente(self):
        canvas = Canvas(100, 80)
        pincel = PenTool(canvas)
        pincel._paint_on_mask = True
        radius = 15.5
        hardness = 60
        color = QColor(0, 0, 0)
        shape = "round"
        point = QPoint(50, 40)

        stamp, center = pincel._mask_solid_stamp(
            radius, color, hardness, shape)
        stamp_again, center_again = pincel._mask_solid_stamp(
            radius, color, hardness, shape)
        self.assertIs(stamp_again, stamp)
        self.assertEqual(center_again, center)

        actual = QImage(100, 80, QImage.Format_Grayscale8)
        actual.fill(255)
        painter = QPainter(actual)
        painter.drawImage(point.x() - center, point.y() - center, stamp)
        painter.end()

        esperado = QImage(100, 80, QImage.Format_Grayscale8)
        esperado.fill(255)
        painter = QPainter(esperado)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gradient = QRadialGradient(point.x(), point.y(), radius)
        gradient.setColorAt(0, color)
        gradient.setColorAt(hardness / 100.0, color)
        for i in range(1, 9):
            k = i / 8
            pos = hardness / 100.0 + (1.0 - hardness / 100.0) * k
            gradient.setColorAt(
                pos, QColor(0, 0, 0, int(255 * ((1.0 - k) ** 3))))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(pincel._shape_path(point, radius, shape))
        painter.end()

        self.assertEqual(actual, esperado)


if __name__ == "__main__":
    unittest.main()
