"""Regresiones de higiene de los paquetes publicables."""

import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from verificar_distribucion import analizar_distribucion, _resolver_zip_portable


class VerificarDistribucionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.dist = self.raiz / "dist" / "Imago"
        self.dist.mkdir(parents=True)
        (self.dist / "Imago.exe").write_bytes(b"EXE")
        internal = self.dist / "_internal"
        internal.mkdir()
        (internal / "libreria.dll").write_bytes(b"DLL")
        self.instalador = self.raiz / "installer" / "ImagoSetup.exe"
        self.instalador.parent.mkdir()
        self.instalador.write_bytes(b"SETUP")
        self.portable = self.raiz / "Imago-1.0-portable.zip"
        self._crear_zip([
            ("Imago/Imago.exe", b"EXE"),
            ("Imago/_internal/libreria.dll", b"DLL"),
            ("Imago/portable.txt", b"portable"),
        ])

    def _crear_zip(self, entradas):
        with zipfile.ZipFile(self.portable, "w") as archivo:
            for nombre, datos in entradas:
                archivo.writestr(nombre, datos)

    def test_paquetes_limpios_devuelven_tamanos_y_hashes(self):
        artefactos, errores = analizar_distribucion(
            self.dist, self.instalador, self.portable)

        self.assertEqual(errores, [])
        self.assertEqual([item["nombre"] for item in artefactos],
                         ["Carpeta desplegada", "Instalador", "ZIP portable"])
        self.assertEqual(artefactos[0]["bytes"], 6)
        self.assertEqual(len(artefactos[1]["sha256"]), 64)
        self.assertEqual(len(artefactos[2]["sha256"]), 64)
        self.assertGreater(artefactos[2]["bytes_descomprimidos"], 0)

    def test_detecta_datos_caches_logs_y_marcador_ausente(self):
        (self.dist / "portable.txt").write_text("mal", encoding="utf-8")
        datos = self.dist / "datos"
        datos.mkdir()
        (datos / "Imago.ini").write_text("privado", encoding="utf-8")
        cache = self.dist / "__pycache__"
        cache.mkdir()
        (cache / "modulo.pyc").write_bytes(b"cache")
        self._crear_zip([
            ("Imago/Imago.exe", b"EXE"),
            ("Imago/datos/Imago.ini", b"privado"),
            ("Imago/imago_crash.log", b"error"),
        ])

        _, errores = analizar_distribucion(
            self.dist, self.instalador, self.portable)
        texto = "\n".join(errores)
        self.assertIn("marcador portable fuera del ZIP", texto)
        self.assertIn("datos locales del usuario", texto)
        self.assertIn("caché o log", texto)
        self.assertIn("exactamente un Imago/portable.txt", texto)
        self.assertIn("El ZIP no coincide con dist", texto)

    def test_autodeteccion_rechaza_varios_zip_para_evitar_publicar_el_viejo(self):
        anterior = Path.cwd()
        os.chdir(self.raiz)
        self.addCleanup(os.chdir, anterior)
        segundo = self.raiz / "Imago-2.0-portable.zip"
        segundo.write_bytes(b"otro")

        _, errores = _resolver_zip_portable(None)
        self.assertEqual(len(errores), 1)
        self.assertIn("varios ZIP portables", errores[0])


if __name__ == "__main__":
    unittest.main()
