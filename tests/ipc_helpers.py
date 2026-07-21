"""Funciones minimas importables por el subproceso real de pruebas IPC."""

import time
import os


def transformar(array, incremento=1, report=None, token=None):
    if report is not None:
        report(35)
    if token is not None and token.cancelled:
        return None
    result = array.astype("int16") + int(incremento)
    if report is not None:
        report(100)
    return {"array": result, "forma": tuple(array.shape)}


def esperar_cancelacion(array, token=None):
    while token is None or not token.cancelled:
        time.sleep(0.01)
    return None


def fallar(array):
    raise RuntimeError("fallo IPC de prueba")


def crash_nativo_simulado(array):
    os._exit(23)
