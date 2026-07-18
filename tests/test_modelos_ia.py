"""Regresiones de instalacion e integridad de los modelos de IA."""

import hashlib
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from ai.model_integrity import marker_path
from ai.model_manager import (ModelInfo, _file_names, _publish_install,
                              is_installed, make_download_task, path_for)
from ai.runner import CancelToken, clear_sessions, get_session


def _model(key="prueba", content=b"modelo correcto", **kwargs):
    return ModelInfo(
        key=key, nombre="Prueba", descripcion="Prueba", licencia="MIT",
        url="https://example.invalid/model.onnx",
        sha256=hashlib.sha256(content).hexdigest(),
        filename=kwargs.pop("filename", key + ".onnx"),
        size_bytes=kwargs.pop("size_bytes", len(content)), **kwargs)


class _FakeSessionOptions:
    def __init__(self):
        self.log_severity_level = 0
        self.enable_mem_pattern = True


class ModelIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.models_patch = patch("ai.model_manager.models_dir",
                                  return_value=self.temp.name)
        self.models_patch.start()

    def tearDown(self):
        clear_sessions()
        self.models_patch.stop()
        self.temp.cleanup()

    def _write(self, model, name, content):
        path = os.path.join(self.temp.name, name)
        with open(path, "wb") as output:
            output.write(content)
        return path

    def test_marca_evita_releer_y_detecta_un_modelo_modificado(self):
        content = b"modelo correcto"
        model = _model(content=content)
        main = self._write(model, model.filename, content)

        self.assertTrue(is_installed(model))
        self.assertTrue(os.path.isfile(marker_path(main)))
        with patch("ai.model_manager._sha256_of",
                   side_effect=AssertionError("no debe recalcular")):
            self.assertTrue(is_installed(model))

        with open(main, "ab") as output:
            output.write(b"alterado")
        self.assertFalse(is_installed(model))
        self.assertFalse(os.path.exists(marker_path(main)))

    def test_datos_externos_ausentes_impiden_declarar_instalado(self):
        main_content = b"onnx"
        model = _model(
            content=main_content,
            data_url="https://example.invalid/model.onnx.data",
            data_sha256=hashlib.sha256(b"data").hexdigest())
        self._write(model, model.filename, main_content)

        self.assertFalse(is_installed(model))

    def test_zip_se_prepara_completo_antes_de_publicarse(self):
        model = _model(key="archivo", content=b"zip", archive=True,
                       filename="archivo.onnx", size_bytes=1024)
        source_zip = os.path.join(self.temp.name, "origen.zip")
        with zipfile.ZipFile(source_zip, "w") as archive:
            archive.writestr("pesos/archivo.onnx", b"onnx nuevo")
            archive.writestr("pesos/archivo.data", b"datos nuevos")

        def fake_download(_url, destination, _digest, _token, progress):
            shutil.copyfile(source_zip, destination)
            progress(100)
            return True

        with patch("ai.model_manager._download_verify", side_effect=fake_download):
            result = make_download_task(model)(lambda _pct: None, CancelToken())

        self.assertEqual(result, path_for(model))
        self.assertTrue(is_installed(model))
        for name in _file_names(model):
            self.assertTrue(os.path.isfile(os.path.join(self.temp.name, name)))

        # Un ZIP incompleto falla dentro del staging y conserva lo ya instalado.
        with zipfile.ZipFile(source_zip, "w") as archive:
            archive.writestr("pesos/archivo.onnx", b"onnx incompleto")
        with patch("ai.model_manager._download_verify", side_effect=fake_download):
            with self.assertRaises(RuntimeError):
                make_download_task(model)(lambda _pct: None, CancelToken())
        with open(path_for(model), "rb") as source:
            self.assertEqual(source.read(), b"onnx nuevo")
        self.assertTrue(is_installed(model))

    def test_error_al_publicar_restaura_la_instalacion_anterior(self):
        old = b"modelo anterior"
        model = _model(content=old)
        main = self._write(model, model.filename, old)
        self.assertTrue(is_installed(model))
        with open(marker_path(main), "rb") as source:
            old_marker = source.read()

        staging = tempfile.mkdtemp(prefix="staging-", dir=self.temp.name)
        try:
            self._write(model, os.path.relpath(
                os.path.join(staging, model.filename), self.temp.name), b"nuevo")
            with patch("ai.model_manager._write_validation_marker",
                       side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    _publish_install(model, staging,
                                     {model.filename: hashlib.sha256(b"nuevo").hexdigest()})
            with open(main, "rb") as source:
                self.assertEqual(source.read(), old)
            with open(marker_path(main), "rb") as source:
                self.assertEqual(source.read(), old_marker)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def test_error_de_carga_recalcula_hash_y_explica_la_corrupcion(self):
        content = b"modelo correcto"
        model = _model(content=content)
        main = self._write(model, model.filename, content)
        self.assertTrue(is_installed(model))
        with open(main, "ab") as output:
            output.write(b"roto")

        fake_ort = types.SimpleNamespace(
            SessionOptions=_FakeSessionOptions,
            InferenceSession=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("fallo de carga")))
        with patch.dict("sys.modules", {"onnxruntime": fake_ort}):
            with self.assertRaisesRegex(RuntimeError, "incompleto o dañado"):
                get_session(main, ["CPUExecutionProvider"])


if __name__ == "__main__":
    unittest.main()
