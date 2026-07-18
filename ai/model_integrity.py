"""Marca persistente y comprobacion de integridad de modelos de IA.

La marca permite que el arranque normal solo compare tamano y fecha de los
ficheros. Ante cualquier cambio, o cuando ONNX Runtime no puede cargar un
modelo, se recalculan los SHA-256 completos.
"""

import json
import hashlib
import os


MARKER_VERSION = 1
MARKER_SUFFIX = ".validado.json"


def sha256_of(path, chunk=1 << 20):
    """Calcula el SHA-256 sin cargar pesos grandes completos en memoria."""
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def marker_path(model_path):
    """Ruta de la marca asociada al archivo ONNX principal."""
    return os.fspath(model_path) + MARKER_SUFFIX


def file_state(path):
    """Metadatos baratos que detectan cambios normales sin releer el modelo."""
    state = os.stat(path)
    return {
        "tamano": state.st_size,
        "mtime_ns": state.st_mtime_ns,
    }


def load_marker(model_path):
    """Carga una marca valida sintacticamente; devuelve None si no existe o falla."""
    try:
        with open(marker_path(model_path), "r", encoding="utf-8") as source:
            marker = json.load(source)
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(marker, dict) or marker.get("version") != MARKER_VERSION:
        return None
    if marker.get("principal") != os.path.basename(os.fspath(model_path)):
        return None
    files = marker.get("archivos")
    if not isinstance(files, dict) or not files:
        return None
    for name, info in files.items():
        if (not isinstance(name, str) or os.path.basename(name) != name or
                not isinstance(info, dict) or not info.get("sha256")):
            return None
    if marker["principal"] not in files:
        return None
    return marker


def marker_stats_match(model_path, marker):
    """True si todos los ficheros conservan los metadatos guardados."""
    directory = os.path.dirname(os.path.abspath(os.fspath(model_path)))
    try:
        return all(
            file_state(os.path.join(directory, name)) == {
                "tamano": info.get("tamano"),
                "mtime_ns": info.get("mtime_ns"),
            }
            for name, info in marker["archivos"].items()
        )
    except OSError:
        return False


def verify_marked_model(model_path, sha256_func=sha256_of, force=False):
    """Verifica una instalacion a partir de su marca.

    Devuelve ``None`` si no hay una marca legible, ``False`` si falta o se
    corrompio algun fichero y ``True`` si el conjunto es integro.
    """
    marker = load_marker(model_path)
    if marker is None:
        return None
    if not force and marker_stats_match(model_path, marker):
        return True
    directory = os.path.dirname(os.path.abspath(os.fspath(model_path)))
    try:
        for name, info in marker["archivos"].items():
            path = os.path.join(directory, name)
            if (not os.path.isfile(path) or
                    sha256_func(path).lower() != info["sha256"].lower()):
                return False
    except OSError:
        return False
    return True
