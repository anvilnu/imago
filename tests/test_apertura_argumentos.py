"""Regresiones de la apertura de archivos entregados al iniciar Imago."""

import os
import tempfile
import unittest

from main import _abrir_rutas_inicio, _rutas_inicio_desde_argumentos


class _Ventana:
    def __init__(self):
        self.abiertas = []

    def open_path(self, ruta):
        self.abiertas.append(ruta)


class AperturaArgumentosTests(unittest.TestCase):
    def test_resuelve_ruta_relativa_antes_del_cambio_de_directorio(self):
        with tempfile.TemporaryDirectory() as carpeta:
            rutas = _rutas_inicio_desde_argumentos(
                ["Imago.exe", os.path.join("Mis imágenes", "foto uno.png")],
                carpeta)

            self.assertEqual(rutas, [os.path.normpath(os.path.join(
                carpeta, "Mis imágenes", "foto uno.png"))])

    def test_abre_en_orden_todos_los_archivos_recibidos(self):
        rutas = [os.path.abspath("primera.png"), os.path.abspath("segunda.imago")]
        ventana = _Ventana()

        _abrir_rutas_inicio(ventana, rutas)

        self.assertEqual(ventana.abiertas, rutas)


if __name__ == "__main__":
    unittest.main()
