"""Regresiones del transporte mapeado y la cancelacion del subproceso IA."""

import os
import pickle
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from ai.ipc_arrays import (IPCArrayCancelled, MMAP_MIN_BYTES, pack_arrays,
                           unpack_arrays)
from ai.runner import CancelToken
from ai.subproc import InferenceProcessCrash, _accept, _run_isolated


class _ListenerBloqueado:
    def __init__(self):
        self._closed = threading.Event()
        self.closed = False

    def accept(self):
        self._closed.wait(5.0)
        raise OSError("listener cerrado")

    def close(self):
        self.closed = True
        self._closed.set()


class _ProcesoVivo:
    @staticmethod
    def poll():
        return None


class AIIPCTests(unittest.TestCase):
    def test_array_grande_viaja_como_descriptor_pequeno(self):
        array = np.arange(700 * 600 * 3, dtype=np.uint8).reshape(600, 700, 3)
        self.assertGreater(array.nbytes, MMAP_MIN_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            packed = pack_arrays({"imagen": array}, directory, "input")
            payload = pickle.dumps(packed, protocol=pickle.HIGHEST_PROTOCOL)

            self.assertLess(len(payload), 1024)
            tag, _filename = packed["imagen"]
            with self.assertRaises(ValueError):
                unpack_arrays((tag, "../escape.npy"), directory)
            mapped = unpack_arrays(packed, directory, copy_arrays=False)["imagen"]
            try:
                self.assertIsInstance(mapped, np.memmap)
                np.testing.assert_array_equal(mapped, array)
                detached = unpack_arrays(packed, directory,
                                         copy_arrays=True)["imagen"]
                self.assertNotIsInstance(detached, np.memmap)
                np.testing.assert_array_equal(detached, array)
            finally:
                mapped._mmap.close()

    def test_transporte_real_reconstruye_entrada_resultado_y_progreso(self):
        array = np.full((600, 700, 3), 17, dtype=np.uint8)
        progress = []

        result = _run_isolated(
            "tests.ipc_helpers", "transformar", (array,), {"incremento": 5},
            force_cpu=True, report=progress.append, token=CancelToken())

        self.assertEqual(result["forma"], array.shape)
        self.assertEqual(result["array"].dtype, np.int16)
        self.assertFalse(isinstance(result["array"], np.memmap))
        self.assertTrue(np.all(result["array"] == 22))
        self.assertEqual(progress, [35, 100])

    def test_cancelar_interrumpe_la_espera_inicial(self):
        listener = _ListenerBloqueado()
        token = CancelToken()
        timer = threading.Timer(0.06, token.cancel)
        timer.start()
        start = time.monotonic()
        try:
            conn = _accept(listener, timeout=5, proc=_ProcesoVivo(), token=token)
        finally:
            timer.cancel()

        self.assertIsNone(conn)
        self.assertTrue(listener.closed)
        self.assertLess(time.monotonic() - start, 0.4)

    def test_cancelar_termina_el_trabajo_real_sin_espera_larga(self):
        array = np.zeros((600, 700, 3), dtype=np.uint8)
        token = CancelToken()
        timer = threading.Timer(0.15, token.cancel)
        timer.start()
        start = time.monotonic()
        try:
            result = _run_isolated(
                "tests.ipc_helpers", "esperar_cancelacion", (array,), {},
                force_cpu=True, report=None, token=token)
        finally:
            timer.cancel()

        self.assertIsNone(result)
        self.assertLess(time.monotonic() - start, 1.5)

    def test_cancelacion_durante_copia_y_error_limpian_temporales(self):
        array = np.zeros((1024, 1024, 4), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as root:
            ipc_dir = os.path.join(root, "ipc_cancelado")
            os.mkdir(ipc_dir)
            with self.assertRaises(IPCArrayCancelled):
                pack_arrays(array, ipc_dir, "input", lambda: True)

        with tempfile.TemporaryDirectory() as ipc_dir:
            packed = pack_arrays(array, ipc_dir, "output")
            with self.assertRaises(IPCArrayCancelled):
                unpack_arrays(packed, ipc_dir, copy_arrays=True,
                              is_cancelled=lambda: True)

        with tempfile.TemporaryDirectory() as root:
            ipc_dir = os.path.join(root, "ipc_error")
            os.mkdir(ipc_dir)
            with patch("ai.subproc.tempfile.mkdtemp", return_value=ipc_dir):
                with self.assertRaisesRegex(RuntimeError, "fallo IPC de prueba"):
                    _run_isolated(
                        "tests.ipc_helpers", "fallar", (array,), {},
                        force_cpu=True, report=None, token=CancelToken())
            self.assertFalse(os.path.exists(ipc_dir))

        with tempfile.TemporaryDirectory() as root:
            ipc_dir = os.path.join(root, "ipc_crash")
            os.mkdir(ipc_dir)
            with patch("ai.subproc.tempfile.mkdtemp", return_value=ipc_dir):
                with self.assertRaises(InferenceProcessCrash):
                    _run_isolated(
                        "tests.ipc_helpers", "crash_nativo_simulado",
                        (array,), {}, force_cpu=True, report=None,
                        token=CancelToken())
            self.assertFalse(os.path.exists(ipc_dir))


if __name__ == "__main__":
    unittest.main()
