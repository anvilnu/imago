"""Regresiones de lectura de paletas y colecciones de muestras."""

import os
import struct
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

from palette_io import cargar_paleta
from widgets.color_dialog import (ImagoColorPickerOverlay,
                                  _codificar_colecciones,
                                  _decodificar_colecciones)


def _guardar(carpeta, nombre, datos):
    ruta = os.path.join(carpeta, nombre)
    with open(ruta, "wb") as archivo:
        archivo.write(datos)
    return ruta


def _rgb(colores):
    return [(color.red(), color.green(), color.blue(), color.alpha())
            for color in colores]


class LecturaPaletasTests(unittest.TestCase):
    def test_gpl_y_jasc_pal(self):
        with tempfile.TemporaryDirectory() as carpeta:
            gpl = _guardar(carpeta, "colores.gpl", (
                b"GIMP Palette\nName: Prueba\nColumns: 2\n"
                b"255 0 0 Rojo\n0 128 255 Azul\n255 0 0 Duplicado\n"))
            pal = _guardar(carpeta, "colores.pal", (
                b"JASC-PAL\n0100\n2\n12 34 56\n255 255 255\n"))

            self.assertEqual(_rgb(cargar_paleta(gpl)),
                             [(255, 0, 0, 255), (0, 128, 255, 255)])
            self.assertEqual(_rgb(cargar_paleta(pal)),
                             [(12, 34, 56, 255), (255, 255, 255, 255)])

    def test_riff_pal_y_act_con_transparencia(self):
        with tempfile.TemporaryDirectory() as carpeta:
            entradas = bytes((10, 20, 30, 0, 200, 150, 100, 0))
            bloque = struct.pack("<HH", 0x0300, 2) + entradas
            riff = (b"RIFF" + struct.pack("<I", 4 + 8 + len(bloque))
                    + b"PAL " + b"data" + struct.pack("<I", len(bloque))
                    + bloque)
            ruta_pal = _guardar(carpeta, "windows.pal", riff)

            tabla = bytearray(768)
            tabla[0:6] = bytes((1, 2, 3, 4, 5, 6))
            act = bytes(tabla) + struct.pack(">HH", 2, 1)
            ruta_act = _guardar(carpeta, "adobe.act", act)

            self.assertEqual(_rgb(cargar_paleta(ruta_pal)),
                             [(10, 20, 30, 255), (200, 150, 100, 255)])
            self.assertEqual(_rgb(cargar_paleta(ruta_act)),
                             [(1, 2, 3, 255), (4, 5, 6, 0)])

    def test_aco_rgb_y_ase_rgb(self):
        with tempfile.TemporaryDirectory() as carpeta:
            aco = (struct.pack(">HH", 1, 1)
                   + struct.pack(">HHHHH", 0, 65535, 0, 32768, 0))
            ruta_aco = _guardar(carpeta, "adobe.aco", aco)

            nombre = "Verde\0".encode("utf-16-be")
            contenido = (struct.pack(">H", len("Verde\0")) + nombre + b"RGB "
                         + struct.pack(">fffH", 0.0, 1.0, 0.25, 0))
            ase = (b"ASEF" + struct.pack(">HHI", 1, 0, 1)
                   + struct.pack(">HI", 0x0001, len(contenido)) + contenido)
            ruta_ase = _guardar(carpeta, "adobe.ase", ase)

            color_aco = cargar_paleta(ruta_aco)[0]
            self.assertEqual((color_aco.red(), color_aco.green()), (255, 0))
            self.assertIn(color_aco.blue(), (127, 128))
            self.assertEqual(_rgb(cargar_paleta(ruta_ase)),
                             [(0, 255, 64, 255)])

    def test_txt_paintnet_hex_y_css(self):
        with tempfile.TemporaryDirectory() as carpeta:
            txt = _guardar(carpeta, "paintnet.txt", (
                b"; ARGB de Paint.NET\n80FF0000\n00 128 255\n"))
            hexa = _guardar(carpeta, "lista.hex", b"33669980\n#fff\n")
            css = _guardar(carpeta, "tema.css", (
                b":root { --uno: #123456; --dos: rgba(255, 0, 128, 0.5); }"))

            self.assertEqual(_rgb(cargar_paleta(txt)),
                             [(255, 0, 0, 128), (0, 128, 255, 255)])
            self.assertEqual(_rgb(cargar_paleta(hexa)),
                             [(51, 102, 153, 128), (255, 255, 255, 255)])
            self.assertEqual(_rgb(cargar_paleta(css)),
                             [(18, 52, 86, 255), (255, 0, 128, 128)])

    def test_archivo_no_reconocido_devuelve_none(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = _guardar(carpeta, "desconocido.bin", b"no es una paleta")
            self.assertIsNone(cargar_paleta(ruta))


class _BarraEstadoFalsa:
    def __init__(self):
        self.mensajes = []

    def showMessage(self, texto, duracion):
        self.mensajes.append((texto, duracion))


class GestionMuestrasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _crear_editor(self, carpeta, muestras=""):
        principal = QWidget()
        principal.settings = QSettings(
            os.path.join(carpeta, "ajustes.ini"), QSettings.Format.IniFormat)
        principal.settings.setValue("colors/custom_swatches", muestras)
        principal.status_bar = _BarraEstadoFalsa()
        principal.last_opened_dir = ""
        editor = ImagoColorPickerOverlay(QColor("#123456"), principal)
        return principal, editor

    def test_colecciones_json_validan_nombres_colores_y_limites(self):
        original = [
            {"name": "Marca", "colors": [QColor("#80ff0000"),
                                           QColor("#ff00ff00")]},
        ]
        crudo = _codificar_colecciones(original)
        cargadas = _decodificar_colecciones(crudo)

        self.assertEqual([c["name"] for c in cargadas], ["Marca"])
        self.assertEqual(_rgb(cargadas[0]["colors"]),
                         [(255, 0, 0, 128), (0, 255, 0, 255)])
        self.assertEqual(_decodificar_colecciones("{incorrecto"), [])

    def test_eliminar_todas_no_borra_colecciones_guardadas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            principal, editor = self._crear_editor(
                carpeta, "#ffff0000,#ff00ff00")
            editor._custom_collections = [{
                "name": "Conservar", "colors": [QColor("#0000ff")],
            }]
            editor._save_custom_collections()

            with patch.object(editor, "_confirmar_muestras", return_value=False):
                editor.delete_all_custom_swatches()
            self.assertEqual(len(editor._custom_colors), 2)

            with patch.object(editor, "_confirmar_muestras", return_value=True):
                editor.delete_all_custom_swatches()

            self.assertEqual(editor._custom_colors, [])
            self.assertEqual(
                principal.settings.value("colors/custom_swatches"), "")
            colecciones = _decodificar_colecciones(
                principal.settings.value("colors/custom_collections"))
            self.assertEqual([c["name"] for c in colecciones], ["Conservar"])
            editor.deleteLater()
            principal.deleteLater()

    def test_guardar_y_cargar_un_conjunto_con_nombre(self):
        with tempfile.TemporaryDirectory() as carpeta:
            principal, editor = self._crear_editor(
                carpeta, "#ffff0000,#800000ff")

            dialogo = type("DialogoNombre", (), {
                "exec": lambda self: True,
                "nombre": lambda self: "Identidad visual",
            })()
            with patch("widgets.color_dialog._NombreColeccionDialog",
                       return_value=dialogo):
                self.assertTrue(editor.save_custom_collection())

            guardadas = _decodificar_colecciones(
                principal.settings.value("colors/custom_collections"))
            self.assertEqual([c["name"] for c in guardadas],
                             ["Identidad visual"])
            self.assertEqual(_rgb(guardadas[0]["colors"]),
                             [(255, 0, 0, 255), (0, 0, 255, 128)])

            editor._custom_colors = [QColor("#ffffff")]
            editor.collection_combo.setCurrentIndex(1)
            with patch.object(editor, "_confirmar_muestras", return_value=True):
                editor.load_custom_collection()
            self.assertEqual(_rgb(editor._custom_colors),
                             [(255, 0, 0, 255), (0, 0, 255, 128)])
            editor.deleteLater()
            principal.deleteLater()

    def test_importar_reemplaza_la_paleta_actual_en_vez_de_unirla(self):
        with tempfile.TemporaryDirectory() as carpeta:
            principal, editor = self._crear_editor(carpeta, "#ff0000ff")
            ruta = _guardar(
                carpeta, "tema.css", b"a { color:#ff0000; background:#00ff00; }")

            with (patch("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                        return_value=(ruta, "")),
                  patch.object(editor, "_autorizar_reemplazo_importado",
                               return_value=True)):
                editor.import_palette()

            self.assertEqual(_rgb(editor._custom_colors),
                             [(255, 0, 0, 255), (0, 255, 0, 255)])
            self.assertEqual(principal.last_opened_dir, carpeta)
            editor.deleteLater()
            principal.deleteLater()

    def test_importar_no_toca_nada_si_no_se_autoriza_el_reemplazo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            principal, editor = self._crear_editor(carpeta, "#ff0000ff")
            ruta = _guardar(carpeta, "lista.hex", b"ff0000\n00ff00\n")

            with (patch("PySide6.QtWidgets.QFileDialog.getOpenFileName",
                        return_value=(ruta, "")),
                  patch.object(editor, "_autorizar_reemplazo_importado",
                               return_value=False)):
                editor.import_palette()

            self.assertEqual(_rgb(editor._custom_colors),
                             [(0, 0, 255, 255)])
            editor.deleteLater()
            principal.deleteLater()

    def test_paleta_no_guardada_ofrece_guardarla_antes_de_importar(self):
        with tempfile.TemporaryDirectory() as carpeta:
            principal, editor = self._crear_editor(carpeta, "#ff123456")

            class DialogoDecision:
                def add_button(self, *_args, **_kwargs):
                    pass

                def exec(self):
                    return True

                def value(self):
                    return "guardar"

            with (patch("widgets.color_dialog.ImagoMessageBox",
                        return_value=DialogoDecision()),
                  patch.object(editor, "save_custom_collection",
                               return_value=False) as guardar):
                self.assertFalse(editor._autorizar_reemplazo_importado())
            guardar.assert_called_once()

            with (patch("widgets.color_dialog.ImagoMessageBox",
                        return_value=DialogoDecision()),
                  patch.object(editor, "save_custom_collection",
                               return_value=True)):
                self.assertTrue(editor._autorizar_reemplazo_importado())
            editor.deleteLater()
            principal.deleteLater()

    def test_paleta_ya_guardada_solo_pide_confirmar_reemplazo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            principal, editor = self._crear_editor(carpeta, "#ff123456")
            editor._custom_collections = [{
                "name": "Marca",
                "colors": [QColor("#123456")],
            }]

            with patch.object(editor, "_confirmar_muestras",
                              return_value=True) as confirmar:
                self.assertTrue(editor._autorizar_reemplazo_importado())
            confirmar.assert_called_once()
            self.assertIn("Marca", confirmar.call_args.args[0])
            editor.deleteLater()
            principal.deleteLater()


if __name__ == "__main__":
    unittest.main()
