"""Regresiones del intervalo configurable de autoguardado."""

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QWidget

from help_dialogs import PreferencesDialog
from i18n import t
from models.autosave import (AutoSaveManager, CLAVE_INTERVALO_MINUTOS,
                             INTERVALO_MAXIMO_MIN,
                             INTERVALO_MINIMO_MIN,
                             intervalo_desde_settings,
                             normalizar_intervalo_minutos)


_APP = QApplication.instance() or QApplication([])


class _AutoguardadoFalso:
    def __init__(self):
        self.intervalos = []

    def set_interval_minutes(self, minutos):
        self.intervalos.append(minutos)


class _VentanaFalsa(QWidget):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.autosave = _AutoguardadoFalso()


class IntervaloAutoguardadoTests(unittest.TestCase):
    def test_normaliza_valores_invalidos_y_fuera_de_rango(self):
        self.assertEqual(normalizar_intervalo_minutos("invalido"), 3)
        self.assertEqual(normalizar_intervalo_minutos(0), INTERVALO_MINIMO_MIN)
        self.assertEqual(normalizar_intervalo_minutos(999), INTERVALO_MAXIMO_MIN)

    def test_manager_aplica_el_intervalo_en_milisegundos(self):
        manager = AutoSaveManager.__new__(AutoSaveManager)
        manager.timer = QTimer()
        self.addCleanup(manager.timer.stop)

        self.assertEqual(manager.set_interval_minutes(7), 7)
        self.assertEqual(manager.interval_min, 7)
        self.assertEqual(manager.timer.interval(), 7 * 60 * 1000)

    def test_lectura_compartida_usa_tres_minutos_por_defecto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            settings = QSettings(
                os.path.join(carpeta, "arranque.ini"),
                QSettings.Format.IniFormat)
            self.assertEqual(intervalo_desde_settings(settings), 3)
            settings.setValue(CLAVE_INTERVALO_MINUTOS, 9)
            self.assertEqual(intervalo_desde_settings(settings), 9)

    def test_preferencias_muestra_guarda_y_aplica_el_intervalo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            settings = QSettings(
                os.path.join(carpeta, "preferencias.ini"),
                QSettings.Format.IniFormat)
            settings.setValue("language", "es")
            settings.setValue("theme", "dark")
            settings.setValue(CLAVE_INTERVALO_MINUTOS, 7)
            ventana = _VentanaFalsa(settings)
            dialogo = PreferencesDialog(ventana)
            self.addCleanup(dialogo.close)
            self.addCleanup(ventana.close)

            self.assertEqual(dialogo.nav.item(3).text(), t("pref.autosave"))
            self.assertEqual(dialogo.autosave_interval_spin.minimum(), 1)
            self.assertEqual(dialogo.autosave_interval_spin.maximum(), 60)
            self.assertEqual(dialogo.autosave_interval_spin.value(), 7)

            dialogo.autosave_interval_spin.setValue(12)
            dialogo._save_and_accept()
            settings.sync()

            self.assertEqual(
                int(settings.value(CLAVE_INTERVALO_MINUTOS)), 12)
            self.assertEqual(ventana.autosave.intervalos, [12])


if __name__ == "__main__":
    unittest.main()
