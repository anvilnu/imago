"""Regresiones del render común de fotogramas por capas."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage

from models.anim_io import capas_de_animacion, frames_de_capas
from models.layer import LayerGroup


def _imagen(color):
    imagen = QImage(3, 2, QImage.Format_ARGB32)
    imagen.fill(QColor(color))
    return imagen


class _CapaFotograma:
    def __init__(self, color_base, color_efecto, delay, group=None):
        self.visible = True
        self.opacity = 100
        self.frame_delay = delay
        self.group = group
        self._base = _imagen(color_base)
        self._con_efectos = _imagen(color_efecto)
        self.renders_con_efectos = 0

    def render_image(self):
        return self._base

    def render_with_effects(self):
        self.renders_con_efectos += 1
        return self._con_efectos


class _CanvasAnimacion:
    base_width = 3
    base_height = 2

    def __init__(self, layers):
        self.layers = layers


class FotogramasPorCapasTests(unittest.TestCase):
    def test_un_grupo_oculto_excluye_sus_capas_y_duraciones(self):
        grupo_oculto = LayerGroup("Oculto")
        grupo_oculto.visible = False
        subgrupo = LayerGroup("Subgrupo", parent=grupo_oculto)
        oculta = _CapaFotograma("red", "yellow", 25, group=subgrupo)
        visible = _CapaFotograma("green", "blue", 80)
        canvas = _CanvasAnimacion([oculta, visible])

        self.assertEqual(capas_de_animacion(canvas), [visible])
        frames, delays = frames_de_capas(canvas)

        self.assertEqual(len(frames), 1)
        self.assertEqual(delays, [80])
        self.assertEqual(oculta.renders_con_efectos, 0)

    def test_preview_y_exportacion_reciben_el_render_con_efectos(self):
        capa = _CapaFotograma("red", "blue", 40)
        frames, delays = frames_de_capas(_CanvasAnimacion([capa]))

        self.assertEqual(delays, [40])
        self.assertEqual(capa.renders_con_efectos, 1)
        color = frames[0].pixelColor(1, 1)
        self.assertEqual(color, QColor("blue"))

    def test_la_visibilidad_individual_sigue_excluyendo_fotogramas(self):
        oculta = _CapaFotograma("red", "red", 20)
        oculta.visible = False
        visible = _CapaFotograma("green", "green", 30)
        canvas = _CanvasAnimacion([oculta, visible])

        self.assertEqual(capas_de_animacion(canvas), [visible])


if __name__ == "__main__":
    unittest.main()
