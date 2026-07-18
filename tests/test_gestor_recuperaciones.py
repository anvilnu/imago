import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QDialog

from models.autosave import AutoSaveManager
from ventana.menu_archivo import AccionesMenuArchivo
from widgets.recovery_manager import RecoveryManagerDialog


def _manager(carpeta):
    manager = AutoSaveManager.__new__(AutoSaveManager)
    manager.dir = carpeta
    manager._counter = 0
    manager._entradas_diferidas = []
    return manager


def _crear_copia(carpeta, identificador, con_miniatura=True):
    nombre = f"doc_{identificador}.imago"
    ruta = os.path.join(carpeta, nombre)
    with open(ruta, "wb") as archivo:
        archivo.write(b"COPIA")
    entrada = {
        "file": nombre,
        "title": f"Documento {identificador}",
        "project_path": os.path.join(carpeta, f"original_{identificador}.imago"),
    }
    if con_miniatura:
        miniatura = f"doc_{identificador}.thumb.png"
        imagen = QImage(20, 12, QImage.Format.Format_ARGB32)
        imagen.fill(QColor("#336699"))
        imagen.save(os.path.join(carpeta, miniatura), "PNG")
        entrada["thumbnail"] = miniatura
    return entrada


class PersistenciaRecuperacionesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pending_entries_anade_fecha_ruta_y_miniatura(self):
        with tempfile.TemporaryDirectory() as carpeta:
            entrada = _crear_copia(carpeta, 3)
            with open(os.path.join(carpeta, "session.json"), "w",
                      encoding="utf-8") as archivo:
                json.dump({"entries": [entrada]}, archivo)

            pendientes = _manager(carpeta).pending_entries()

            self.assertEqual(len(pendientes), 1)
            self.assertEqual(pendientes[0]["title"], "Documento 3")
            self.assertEqual(
                pendientes[0]["path"], os.path.join(carpeta, "doc_3.imago"))
            self.assertEqual(
                pendientes[0]["thumbnail_path"],
                os.path.join(carpeta, "doc_3.thumb.png"))
            self.assertIsInstance(pendientes[0]["modified_at"], float)

    def test_snapshot_publica_miniatura_atomica_desde_la_cache(self):
        with tempfile.TemporaryDirectory() as carpeta:
            imagen = QImage(30, 18, QImage.Format.Format_ARGB32)
            imagen.fill(QColor("#884422"))
            pixmap = QPixmap.fromImage(imagen)
            canvas = type("Canvas", (), {
                "undo_stack": type("Pila", (), {
                    "isClean": lambda self: False,
                })(),
                "recovered_dirty": False,
                "revision_autoguardado": 5,
                "project_path": None,
            })()
            tabs = type("Tabs", (), {
                "count": lambda self: 1,
                "widget": lambda self, _i: type(
                    "Marker", (), {"canvas": canvas})(),
                "tabText": lambda self, _i: "Documento",
            })()
            barra = type("Barra", (), {
                "preview_for_canvas": lambda self, _canvas: pixmap,
            })()
            manager = _manager(carpeta)
            manager.main = type("Main", (), {
                "tabs": tabs, "thumbnail_bar": barra,
            })()

            def guardar(_canvas, ruta):
                with open(ruta, "wb") as archivo:
                    archivo.write(b"COPIA")
                return True

            with patch("models.autosave.save_project", side_effect=guardar):
                manager.snapshot()

            ruta_miniatura = os.path.join(carpeta, "doc_1.thumb.png")
            self.assertFalse(QImage(ruta_miniatura).isNull())
            with open(os.path.join(carpeta, "session.json"), "r",
                      encoding="utf-8") as archivo:
                entrada = json.load(archivo)["entries"][0]
            self.assertEqual(entrada["thumbnail"], "doc_1.thumb.png")

    def test_clear_conserva_diferidas_y_elimina_copias_activas(self):
        with tempfile.TemporaryDirectory() as carpeta:
            conservar = _crear_copia(carpeta, 1)
            _crear_copia(carpeta, 2)
            manager = _manager(carpeta)
            manager.defer_entries([conservar])

            manager.clear()

            self.assertTrue(os.path.exists(os.path.join(carpeta, "doc_1.imago")))
            self.assertTrue(os.path.exists(
                os.path.join(carpeta, "doc_1.thumb.png")))
            self.assertFalse(os.path.exists(os.path.join(carpeta, "doc_2.imago")))
            with open(os.path.join(carpeta, "session.json"), "r",
                      encoding="utf-8") as archivo:
                manifiesto = json.load(archivo)
            self.assertEqual(
                [e["file"] for e in manifiesto["entries"]], ["doc_1.imago"])

    def test_descarte_selectivo_no_toca_la_copia_conservada(self):
        with tempfile.TemporaryDirectory() as carpeta:
            descartada = _crear_copia(carpeta, 1)
            conservada = _crear_copia(carpeta, 2)
            manager = _manager(carpeta)
            manager.defer_entries([descartada, conservada])

            manager.discard_entries([descartada])
            manager.clear()

            self.assertFalse(os.path.exists(os.path.join(carpeta, "doc_1.imago")))
            self.assertFalse(os.path.exists(
                os.path.join(carpeta, "doc_1.thumb.png")))
            self.assertTrue(os.path.exists(os.path.join(carpeta, "doc_2.imago")))
            self.assertEqual(
                [e["file"] for e in manager._entradas_diferidas],
                ["doc_2.imago"])

    def test_adoptar_reutiliza_id_y_evitas_colisiones(self):
        with tempfile.TemporaryDirectory() as carpeta:
            entrada = _crear_copia(carpeta, 7)
            manager = _manager(carpeta)
            manager.defer_entries([entrada])
            canvas = type("Canvas", (), {"revision_autoguardado": 42})()

            manager.adopt_recovery(canvas, entrada)

            self.assertEqual(canvas._autosave_id, 7)
            self.assertEqual(canvas._autosave_revision, 42)
            self.assertEqual(manager._counter, 7)
            self.assertEqual(manager._entradas_diferidas, [])

    def test_manifiesto_no_permite_rutas_fuera_de_recuperacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with open(os.path.join(carpeta, "session.json"), "w",
                      encoding="utf-8") as archivo:
                json.dump({"entries": [{"file": "../documento.imago"}]}, archivo)
            self.assertEqual(_manager(carpeta).pending_entries(), [])


class DialogoRecuperacionesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_cada_fila_tiene_decision_independiente_y_miniatura(self):
        with tempfile.TemporaryDirectory() as carpeta:
            primera = _crear_copia(carpeta, 1)
            segunda = _crear_copia(carpeta, 2, con_miniatura=False)
            primera["thumbnail_path"] = os.path.join(
                carpeta, "doc_1.thumb.png")
            primera["modified_at"] = 1_700_000_000
            segunda["modified_at"] = None
            dialogo = RecoveryManagerDialog([primera, segunda])

            self.assertEqual(
                [accion for _entrada, accion in dialogo.decisiones()],
                ["open", "open"])
            dialogo._filas[0].set_accion("keep")
            dialogo._filas[1].set_accion("discard")
            self.assertEqual(
                [accion for _entrada, accion in dialogo.decisiones()],
                ["keep", "discard"])
            self.assertFalse(dialogo._filas[0].miniatura.pixmap().isNull())
            self.assertTrue(dialogo._filas[1].miniatura.pixmap().isNull())
            dialogo.deleteLater()


class FlujoGestorRecuperacionesTests(unittest.TestCase):
    def test_aplica_abrir_conservar_y_descartar_sin_perder_fallidas(self):
        entradas = [
            {"file": "doc_1.imago"},
            {"file": "doc_2.imago"},
            {"file": "doc_3.imago"},
        ]

        class AutoguardadoFalso:
            def __init__(self):
                self.diferidas = []
                self.descartadas = []
                self.snapshots = 0

            def pending_entries(self):
                return entradas

            def defer_entries(self, nuevas):
                self.diferidas.extend(nuevas)

            def discard_entries(self, descartadas):
                self.descartadas.extend(descartadas)

            def snapshot(self):
                self.snapshots += 1

        class DialogoFalso:
            def __init__(self, recibidas, parent):
                self.recibidas = recibidas

            def exec(self):
                return QDialog.DialogCode.Accepted

            def decisiones(self):
                return [(entradas[0], "open"), (entradas[1], "keep"),
                        (entradas[2], "discard")]

        ventana = type("Ventana", (), {})()
        ventana.autosave = AutoguardadoFalso()
        ventana.abiertas = []
        ventana._restore_recovery = lambda nuevas: ventana.abiertas.extend(nuevas)

        with patch("widgets.recovery_manager.RecoveryManagerDialog", DialogoFalso):
            AccionesMenuArchivo._check_recovery(ventana)

        self.assertEqual(ventana.autosave.diferidas, entradas)
        self.assertEqual(ventana.abiertas, [entradas[0]])
        self.assertEqual(ventana.autosave.descartadas, [entradas[2]])
        self.assertEqual(ventana.autosave.snapshots, 1)

    def test_cerrar_gestor_conserva_todo_sin_publicar_decisiones(self):
        entradas = [{"file": "doc_1.imago"}]

        class AutoguardadoFalso:
            def __init__(self):
                self.diferidas = []

            def pending_entries(self):
                return entradas

            def defer_entries(self, nuevas):
                self.diferidas.extend(nuevas)

        class DialogoFalso:
            def __init__(self, recibidas, parent):
                pass

            def exec(self):
                return QDialog.DialogCode.Rejected

        ventana = type("Ventana", (), {"autosave": AutoguardadoFalso()})()
        with patch("widgets.recovery_manager.RecoveryManagerDialog", DialogoFalso):
            AccionesMenuArchivo._check_recovery(ventana)

        self.assertEqual(ventana.autosave.diferidas, entradas)


if __name__ == "__main__":
    unittest.main()
