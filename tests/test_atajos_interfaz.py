"""Regresiones de foco para los atajos temporales de la interfaz."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

import recursos_rc  # noqa: F401  (registra los iconos embebidos)
from ventana.construccion_ui import ConstruccionUI


_APP = QApplication.instance() or QApplication([])


class AtajosInterfazTests(unittest.TestCase):
    def test_toggles_de_panel_no_roban_espacio_al_lienzo(self):
        interfaz = ConstruccionUI()
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)

        interfaz.create_panel_toggle_buttons(fila)

        for nombre in ("btn_toggle_tools", "btn_toggle_history",
                       "btn_toggle_layers", "btn_toggle_colors",
                       "btn_toggle_histogram"):
            with self.subTest(nombre=nombre):
                boton = getattr(interfaz, nombre)
                self.assertEqual(boton.focusPolicy(), Qt.NoFocus)


if __name__ == "__main__":
    unittest.main()
