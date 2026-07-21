# ai/model_manager.py
"""Gestor de modelos de IA: catalogo + descarga BAJO DEMANDA.

Los modelos NO se empaquetan con Imago (mantenerlo ligero): cada uno se descarga
la primera vez que se usa su funcion, se verifica por hash SHA-256 y se cachea en
la carpeta de datos del usuario (misma raiz que la recuperacion automatica). Se
pueden borrar para liberar espacio.

Este modulo tiene dos capas:
  - Logica pura (sin Qt): catalogo, rutas, verificacion, descarga (funcion de
    trabajo para el InferenceRunner) y borrado.
  - UI: ModelManagerDialog (FramelessDialog) "Modelos de IA".

IMPORTANTE (licencias): solo modelos con licencia REDISTRIBUIBLE (ver
propuesta_ia.md). Fijar url+sha256 de cada modelo ANTES de habilitar su descarga;
mientras esten a None, la fila se muestra pero la descarga queda deshabilitada.
"""

import os
import json
import shutil
import hashlib
import tempfile
import urllib.request
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QWidget, QProgressBar)

import app_paths
import theme
from i18n import t
from widgets.custom_titlebar import FramelessDialog, imago_question
from PySide6.QtWidgets import QMessageBox
from ai.runner import InferenceRunner, onnx_available, clear_sessions
from ai.model_integrity import (MARKER_VERSION, file_state, load_marker,
                                marker_path, marker_stats_match)


# ===========================================================================
#  CATALOGO
# ===========================================================================
class ModelInfo:
    """Descripcion de un modelo del catalogo. `url`/`sha256` a None => todavia
    no configurado (la descarga aparece deshabilitada)."""

    def __init__(self, key, nombre, descripcion, licencia,
                 url=None, sha256=None, size_bytes=0, filename=None,
                 archive=False, data_url=None, data_sha256=None):
        self.key = key
        self.nombre = nombre
        self.descripcion = descripcion
        self.licencia = licencia
        self.url = url
        self.sha256 = sha256          # hash del fichero descargado (.onnx o .zip)
        self.size_bytes = size_bytes
        self.filename = filename or f"{key}.onnx"
        # archive=True: la URL es un ZIP con el modelo en formato de DATOS
        # EXTERNOS (un .onnx pequeño + un .data grande). Se descarga, se verifica
        # el hash del ZIP y se EXTRAEN sus .onnx/.data (aplanados) a la carpeta de
        # modelos. `filename` es el .onnx principal.
        self.archive = archive
        # data_url: modelo de DATOS EXTERNOS en DOS ficheros SEPARADOS (el .onnx y
        # su .data, cada uno con su URL/hash). El .onnx referencia el .data por
        # "<filename>.data", asi que el companion se guarda con ese nombre exacto.
        self.data_url = data_url
        self.data_sha256 = data_sha256

    @property
    def configurado(self):
        return bool(self.url) and bool(self.sha256)


# Catalogo. Los modelos con url/sha256 a None estan PENDIENTES de configurar
# (fila visible pero descarga deshabilitada): se rellenan al fijar el modelo y su
# licencia. Fuente de los pesos: releases del proyecto rembg (danielgatis/rembg),
# derivados de los repos originales (Apache-2.0), redistribuibles.
CATALOG = [
    ModelInfo(
        key="isnet-general-use",
        nombre=t("ai.model.isnet.name", default="ISNet (uso general)"),
        descripcion=t("ai.model.isnet.desc",
                      default="Eliminacion automatica de fondo (segmentacion)."),
        licencia="Apache-2.0",
        url="https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
            "isnet-general-use.onnx",
        sha256="60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a",
        size_bytes=178648008,
    ),
    ModelInfo(
        key="u2net",
        nombre="U2Net",
        descripcion=t("ai.model.u2net.desc",
                      default="Eliminacion de fondo (alternativa mas ligera de ISNet)."),
        licencia="Apache-2.0",
        url=None, sha256=None, size_bytes=0,
    ),
    # LaMa (Apache-2.0): inpainting de alta calidad; reconstruye el fondo tras el
    # objeto borrado mucho mejor que alternativas ligeras (MI-GAN dejaba una mancha).
    # Usa convoluciones de Fourier (FFC) que DirectML no soporta -> en GPUs por
    # DirectML cae a CPU (rapido: solo procesa un recorte de 512); en NVIDIA va por CUDA.
    ModelInfo(
        key="lama",
        nombre="LaMa",
        descripcion=t("ai.model.lama.desc",
                      default="Borrado inteligente de objetos (inpainting)."),
        licencia="Apache-2.0",
        url="https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
        sha256="1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6",
        size_bytes=208044816,
    ),
    # Real-ESRGAN general x4 v3 (repo xinntao/Real-ESRGAN, BSD-3): modelo compacto
    # y ligero (~5 MB), entrada de tamano libre, factor x4.
    ModelInfo(
        key="realesrgan",
        nombre="Real-ESRGAN (x4)",
        descripcion=t("ai.model.realesrgan.desc",
                      default="Aumentar la resolucion (super-resolucion)."),
        licencia="BSD-3-Clause",
        url="https://huggingface.co/Samo629/real-esrgan-onnx/resolve/main/"
            "realesr-general-x4v3.onnx",
        sha256="ee28b94a5d06ff32c4920370417e094d1dc7aae4e568e2502afb3371377e41fd",
        size_bytes=4866421,
    ),
    # DDColor (Qualcomm AI Hub, pesos originales Apache-2.0). ZIP con datos
    # externos (.onnx + .data). El hash es el del ZIP.
    ModelInfo(
        key="ddcolor",
        nombre="DDColor",
        descripcion=t("ai.model.ddcolor.desc",
                      default="Colorizacion automatica de fotos en blanco y negro."),
        licencia="Apache-2.0",
        url="https://qaihub-public-assets.s3.us-west-2.amazonaws.com/qai-hub-models/"
            "models/ddcolor/releases/v0.56.0/ddcolor-onnx-float.zip",
        sha256="b9e784e2fc1520adc7f948e6c5a0a33aee0af452da68d643813fdf2012508b42",
        size_bytes=206162324,
        archive=True,
    ),
    # SCUNet (denoise real, Apache-2.0). Datos externos en DOS ficheros (.onnx +
    # .onnx.data). El .onnx referencia su .data por "<filename>.data".
    # NOTA: su transformer Swin revienta DirectML -> en AMD/Intel cae a CPU (lento pero
    # excelente); ai_denoise avisa de que puede tardar varios minutos. Se prefirió su
    # calidad a NAFNet (rápido pero con menos calidad/costuras).
    ModelInfo(
        key="scunet-denoise",
        nombre=t("ai.model.scunet.name", default="SCUNet (reducir ruido)"),
        descripcion=t("ai.model.scunet.desc",
                      default="Reducir el ruido de la foto."),
        licencia="Apache-2.0",
        filename="scunet_color_real_psnr.onnx",
        url="https://huggingface.co/Heliosoph/scunet-onnx/resolve/main/"
            "scunet_color_real_psnr.onnx",
        sha256="231be201ab413dbc999d7951caa9844846b93a12a40a41e037d6b5888ed4e88c",
        data_url="https://huggingface.co/Heliosoph/scunet-onnx/resolve/main/"
                 "scunet_color_real_psnr.onnx.data",
        data_sha256="98825ea1210b641c71e5f052f582c70c49fd44b35387ebe2c034268c17df3feb",
        size_bytes=76936854,
    ),
    # Restauracion de caras: detector YuNet (Apache-2.0, ~0.2 MB) + GFPGAN v1.4
    # (Apache-2.0, ~340 MB). Ambos de un solo fichero.
    ModelInfo(
        key="yunet",
        nombre=t("ai.model.yunet.name", default="YuNet (detector de caras)"),
        descripcion=t("ai.model.yunet.desc",
                      default="Detecta caras (para restaurarlas)."),
        licencia="Apache-2.0",
        url="https://huggingface.co/bukuroo/YuNet-ONNX/resolve/main/yunet.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        size_bytes=232589,
    ),
    ModelInfo(
        key="gfpgan",
        nombre=t("ai.model.gfpgan.name", default="GFPGAN (restaurar caras)"),
        descripcion=t("ai.model.gfpgan.desc",
                      default="Restaura y mejora las caras de la foto."),
        licencia="Apache-2.0",
        url="https://huggingface.co/neurobytemind/GFPGANv1.4.onnx/resolve/main/"
            "GFPGANv1.4.onnx",
        sha256="cd7311b8d9e13cdb1e208b12363182da58c7bf45e26d1aa67bbeac4751aae92e",
        size_bytes=340256686,
    ),
    # DeepLabV3+ MobileNetV2 (Kalray, Apache-2.0, ~8 MB): segmentacion semantica
    # (21 clases Pascal VOC) para "seleccionar por objeto".
    ModelInfo(
        key="deeplab",
        nombre=t("ai.model.deeplab.name", default="DeepLab (segmentación)"),
        descripcion=t("ai.model.deeplab.desc",
                      default="Seleccionar objetos por su tipo (persona, coche...)."),
        licencia="Apache-2.0",
        url="https://huggingface.co/Kalray/deeplabv3plus-mobilenetv2/resolve/main/"
            "deeplab-mb2_bilinear.onnx",
        sha256="e793c4e28c2f1768c08901b9169342317de382e7773cd9fd622aaf63b5fecb27",
        size_bytes=8438125,
    ),
    # MiDaS v21 small (MIT): estimacion de profundidad para el bokeh por
    # profundidad. Un solo fichero (~66 MB).
    ModelInfo(
        key="midas-small",
        nombre=t("ai.model.midas.name", default="MiDaS (profundidad)"),
        descripcion=t("ai.model.midas.desc",
                      default="Estimar la profundidad para el bokeh."),
        licencia="MIT",
        url="https://huggingface.co/Heliosoph/midas-small-onnx/resolve/main/"
            "midas_v21_small_256.onnx",
        sha256="b0a5b3f12625137e626805167907fe0410665bec671685d59daaa2daab19f977",
        size_bytes=66389153,
    ),
    # PP-OCR (Apache-2.0): deteccion de texto (DBNet movil v5) + reconocimiento
    # latino (PP-OCRv5 movil, 34 idiomas incl. espanol). Conversiones ONNX
    # OFICIALES de PaddlePaddle en Hugging Face.
    ModelInfo(
        key="ocr-det",
        nombre=t("ai.model.ocrdet.name", default="PP-OCR (detectar texto)"),
        descripcion=t("ai.model.ocrdet.desc",
                      default="Encuentra las zonas con texto (OCR)."),
        licencia="Apache-2.0",
        filename="ppocr_det.onnx",
        url="https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det_onnx/"
            "resolve/main/inference.onnx",
        sha256="a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d",
        size_bytes=4826518,
    ),
    ModelInfo(
        key="ocr-rec-latin",
        nombre=t("ai.model.ocrrec.name", default="PP-OCR (leer texto latino)"),
        descripcion=t("ai.model.ocrrec.desc",
                      default="Lee el texto detectado (OCR, alfabeto latino)."),
        licencia="Apache-2.0",
        filename="ppocr_rec_latin.onnx",
        url="https://huggingface.co/PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx/"
            "resolve/main/inference.onnx",
        sha256="7888113072263cb471b93f66dd5e2ad70548dc526fa1ace760d0d973dd121498",
        size_bytes=8042023,
    ),
]


def get_model(key):
    for m in CATALOG:
        if m.key == key:
            return m
    return None


# ===========================================================================
#  RUTAS / ESTADO EN DISCO
# ===========================================================================
def models_dir():
    """Carpeta de cache de modelos, en los datos del usuario (misma raiz que la
    recuperacion automatica). Se crea si no existe."""
    base = app_paths.base_datos()
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".imago")
    d = os.path.join(base, "modelos_ia")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def path_for(model):
    """Ruta local (instalada o no) del archivo .onnx de un modelo."""
    return os.path.join(models_dir(), model.filename)


def _disk_files(model):
    """Ficheros en disco que componen el modelo: el .onnx principal y, en los
    modelos de datos externos (archive), su .data companero (mismo nombre)."""
    main = path_for(model)
    files = [main]
    if model.archive:
        files.append(os.path.splitext(main)[0] + ".data")
    elif model.data_url:
        files.append(main + ".data")   # <filename>.data (nombre que espera el .onnx)
    return files


def is_installed(model):
    """True solo si estan todos los ficheros y su integridad esta validada.

    La marca evita releer modelos de cientos de MB en cada consulta. Si falta o
    cambian los metadatos, se recalculan los hashes completos.
    """
    return verify_installation(model)


def installed_size(model):
    total = 0
    for p in _disk_files(model):
        try:
            if os.path.isfile(p):
                total += os.path.getsize(p)
        except OSError:
            pass
    return total


def total_installed_size():
    return sum(installed_size(m) for m in CATALOG)


def delete_model(model):
    """Borra los archivos del modelo (si existen). Limpia la cache de sesiones por
    si estaba cargado."""
    # En Windows una sesion puede mantener el ONNX abierto e impedir borrarlo.
    clear_sessions()
    for p in _disk_files(model) + [marker_path(path_for(model))]:
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


# ===========================================================================
#  VERIFICACION Y DESCARGA
# ===========================================================================
def _sha256_of(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def verify_file(path, sha256):
    return os.path.isfile(path) and _sha256_of(path).lower() == sha256.lower()


def _file_names(model):
    """Nombres base exactos que forman una instalacion."""
    names = [model.filename]
    if model.archive:
        names.append(os.path.splitext(model.filename)[0] + ".data")
    elif model.data_url:
        names.append(model.filename + ".data")
    return names


def _catalog_signature(model):
    data = {
        "key": model.key,
        "filename": model.filename,
        "sha256": model.sha256,
        "archive": bool(model.archive),
        "data_sha256": model.data_sha256,
    }
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _expected_hashes(model):
    names = _file_names(model)
    if model.archive:
        return None
    hashes = {names[0]: model.sha256}
    if model.data_url:
        hashes[names[1]] = model.data_sha256
    return hashes


def _remove_marker(model):
    try:
        os.remove(marker_path(path_for(model)))
    except OSError:
        pass


def _write_validation_marker(model, hashes):
    """Publica atomicamente la marca de una instalacion ya completa."""
    from atomic_io import escribir_atomico

    directory = models_dir()
    entries = {}
    for name in _file_names(model):
        path = os.path.join(directory, name)
        entries[name] = {"sha256": hashes[name], **file_state(path)}
    marker = {
        "version": MARKER_VERSION,
        "modelo": model.key,
        "principal": model.filename,
        "catalogo": _catalog_signature(model),
        "archivos": entries,
    }

    def write(temp_path):
        with open(temp_path, "w", encoding="utf-8", newline="\n") as output:
            json.dump(marker, output, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
        return True

    if not escribir_atomico(marker_path(path_for(model)), write):
        raise OSError(t("ai.models.marker_fail"))


def verify_installation(model, force=False):
    """Comprueba el conjunto completo y renueva su marca cuando sea necesario."""
    files = _disk_files(model)
    if not all(os.path.isfile(path) for path in files):
        _remove_marker(model)
        return False

    marker = load_marker(path_for(model))
    marker_matches_catalog = bool(
        marker and marker.get("modelo") == model.key and
        marker.get("catalogo") == _catalog_signature(model) and
        set(marker["archivos"]) == set(_file_names(model)))
    if marker_matches_catalog and not force and marker_stats_match(path_for(model), marker):
        return True

    expected = _expected_hashes(model)
    if expected is None:
        # En un ZIP el catalogo conoce el hash del archivo contenedor. Una vez
        # extraido, los hashes fiables son los que se guardaron al instalarlo.
        if not marker_matches_catalog:
            _remove_marker(model)
            return False
        expected = {name: info["sha256"]
                    for name, info in marker["archivos"].items()}

    actual = {}
    try:
        for name, expected_hash in expected.items():
            path = os.path.join(models_dir(), name)
            digest = _sha256_of(path)
            if not expected_hash or digest.lower() != expected_hash.lower():
                _remove_marker(model)
                return False
            actual[name] = digest
        _write_validation_marker(model, actual)
    except OSError:
        _remove_marker(model)
        return False
    return True


def _extract_model_zip(zip_path, model, destination, token=None):
    """Extrae el conjunto exacto en una carpeta privada, nunca sobre el activo."""
    expected = set(_file_names(model))
    found = {}
    max_total = max(int(model.size_bytes or 0) * 3, 64 << 20)
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = os.path.basename(info.filename)
            if name not in expected:
                continue
            if name in found or info.is_dir() or info.flag_bits & 0x1:
                raise RuntimeError(t("ai.models.archive_invalid"))
            total += info.file_size
            if total > max_total:
                raise RuntimeError(t("ai.models.archive_invalid"))
            target = os.path.join(destination, name)
            with archive.open(info) as source, open(target, "wb") as output:
                while True:
                    if token is not None and token.cancelled:
                        return False
                    block = source.read(1 << 20)
                    if not block:
                        break
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            found[name] = target
    if set(found) != expected:
        raise RuntimeError(t("ai.models.archive_invalid"))
    return True


def _validate_staged(model, directory):
    """Devuelve los hashes reales si la descarga preparada es coherente."""
    expected = _expected_hashes(model)
    actual = {}
    for name in _file_names(model):
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            raise RuntimeError(t("ai.models.install_incomplete"))
        digest = _sha256_of(path)
        if expected is not None and digest.lower() != expected[name].lower():
            raise RuntimeError(t("ai.models.hash_fail"))
        actual[name] = digest
    return actual


def _publish_install(model, staging, hashes):
    """Publica el conjunto validado; ante error restaura la instalacion anterior."""
    # Cerrar primero cualquier descriptor de ONNX Runtime: Windows no permite
    # reemplazar un fichero que siga abierto.
    clear_sessions()
    destination = models_dir()
    names = _file_names(model)
    live = {name: os.path.join(destination, name) for name in names}
    backups = {}
    marker = marker_path(path_for(model))
    published = []
    try:
        for index, path in enumerate(list(live.values()) + [marker]):
            if os.path.isfile(path):
                backup = os.path.join(staging, ".anterior-%d" % index)
                os.replace(path, backup)
                backups[path] = backup
        # El ONNX se publica el ultimo: nunca apunta durante la publicacion a
        # un companion antiguo. La marca, que declara la instalacion util, va despues.
        for name in names[1:] + names[:1]:
            os.replace(os.path.join(staging, name), live[name])
            published.append(live[name])
        _write_validation_marker(model, hashes)
    except Exception:
        if marker in backups or published:
            _remove_marker(model)
        for path in reversed(published):
            try:
                os.remove(path)
            except OSError:
                pass
        for path, backup in backups.items():
            try:
                os.replace(backup, path)
            except OSError:
                pass
        raise


def _download_verify(url, dest, sha256, token, report_progress):
    """Descarga `url` a dest+'.part', verifica su sha256 y lo renombra a dest.
    Devuelve True, o False si se cancelo. Lanza en error de red o hash. El
    report_progress recibe 0..100 del PROPIO fichero."""
    part = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Imago"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as out:
                while True:
                    if token.cancelled:
                        return False
                    chunk = resp.read(1 << 16)   # 64 KB
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        report_progress(min(100, done * 100 // total))
        if token.cancelled:
            return False
        if not verify_file(part, sha256):
            raise RuntimeError(t("ai.models.hash_fail",
                default="La verificacion del archivo fallo (hash incorrecto)."))
        os.replace(part, dest)
        return True
    finally:
        if os.path.isfile(part):     # nunca dejar un .part a medias
            try:
                os.remove(part)
            except OSError:
                pass


def make_download_task(model):
    """Devuelve una funcion de trabajo fn(report_progress, token) apta para
    InferenceRunner.submit(): descarga el modelo (uno o varios ficheros), verifica
    los hashes y lo deja instalado. Devuelve la ruta final del .onnx, o None si se
    cancelo. Lanza excepcion (texto legible) en error o hash incorrecto."""
    def task(report_progress, token):
        if not model.configurado:
            raise RuntimeError(t("ai.models.pending",
                                 default="Modelo pendiente de configurar."))
        final = path_for(model)
        report_progress(0)
        staging = tempfile.mkdtemp(prefix=".%s-" % model.key, dir=models_dir())
        try:
            if model.archive:
                zip_dest = os.path.join(staging, "descarga.zip")
                if not _download_verify(model.url, zip_dest, model.sha256, token,
                                        report_progress):
                    return None
                try:
                    if not _extract_model_zip(zip_dest, model, staging, token):
                        return None
                except zipfile.BadZipFile as exc:
                    raise RuntimeError(t("ai.models.archive_invalid")) from exc
                try:
                    os.remove(zip_dest)
                except OSError:
                    pass
            elif model.data_url:
                data_dest = os.path.join(staging, model.filename + ".data")
                if not _download_verify(model.data_url, data_dest, model.data_sha256,
                                        token, lambda p: report_progress(min(98, p))):
                    return None
                main_dest = os.path.join(staging, model.filename)
                if not _download_verify(model.url, main_dest, model.sha256,
                                        token, lambda p: None):
                    return None
            else:
                main_dest = os.path.join(staging, model.filename)
                if not _download_verify(model.url, main_dest, model.sha256,
                                        token, report_progress):
                    return None

            hashes = _validate_staged(model, staging)
            _publish_install(model, staging, hashes)
            if not verify_installation(model, force=True):
                raise RuntimeError(t("ai.models.install_incomplete"))
            report_progress(100)
            return final
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return task


# ===========================================================================
#  UTILIDAD DE FORMATO
# ===========================================================================
def format_size(num_bytes):
    if not num_bytes:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(num_bytes)} {unit}"
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} GB"


# ===========================================================================
#  DIALOGO "Modelos de IA"
# ===========================================================================
class _ModelRow(QWidget):
    """Fila de un modelo: nombre + descripcion + licencia + estado, y un boton
    Descargar / Borrar segun este instalado o no."""

    def __init__(self, model, dialog):
        super().__init__()
        self.model = model
        self.dialog = dialog

        # Aspecto de "tarjeta" (las columnas del grid no admiten lineas HLine
        # entre filas, asi que cada modelo lleva su propio marco tenue). Un
        # QWidget normal NO pinta el borde/fondo del stylesheet sin este atributo.
        self.setObjectName("ModelCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ModelCard {{ border: 1px solid {theme.BORDER};"
            f" border-radius: 5px; background: {theme.BG_DARK}; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(model.nombre)
        name.setStyleSheet(f"color: {theme.TEXT}; font-weight: bold; font-size: 13px;")
        desc = QLabel(model.descripcion)
        desc.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        desc.setWordWrap(True)
        meta = QLabel(self._meta_text())
        meta.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        self._meta_label = meta
        info.addWidget(name)
        info.addWidget(desc)
        info.addWidget(meta)
        lay.addLayout(info, 1)

        self.button = QPushButton()
        self.button.setStyleSheet(theme.dialog_button_qss("QPushButton"))
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self._on_click)
        lay.addWidget(self.button, 0, Qt.AlignTop)

        self.refresh()

    def _meta_text(self):
        lic = t("ai.models.license", default="Licencia: {lic}", lic=self.model.licencia)
        if is_installed(self.model):
            size = format_size(installed_size(self.model))
            estado = t("ai.models.installed", default="Instalado")
        elif not self.model.configurado:
            size = "—"
            estado = t("ai.models.pending", default="Pendiente de configurar")
        else:
            size = format_size(self.model.size_bytes)
            estado = t("ai.models.not_installed", default="No instalado")
        return f"{estado}  ·  {lic}  ·  {size}"

    def refresh(self):
        self._meta_label.setText(self._meta_text())
        if is_installed(self.model):
            self.button.setText(t("ai.models.delete", default="Borrar"))
            self.button.setEnabled(True)
        else:
            self.button.setText(t("ai.models.download", default="Descargar"))
            self.button.setEnabled(self.model.configurado
                                   and not self.dialog.is_busy())

    def _on_click(self):
        if is_installed(self.model):
            self.dialog.request_delete(self.model, self)
        else:
            self.dialog.request_download(self.model, self)


class ModelManagerDialog(FramelessDialog):
    """Dialogo modal frameless para descargar / borrar los modelos de IA."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("ai.models.title", default="Modelos de IA"))
        self.setModal(True)
        self._runner = InferenceRunner(self)
        self._active_handle = None
        self._active_row = None
        self._rows = []

        self.body_layout.setContentsMargins(16, 12, 16, 14)
        self.body_layout.setSpacing(10)

        # Aviso si onnxruntime no esta instalado (los modelos no se ejecutaran).
        if not onnx_available():
            warn = QLabel(t("ai.models.no_onnx",
                default="onnxruntime no esta instalado: los modelos no podran "
                        "ejecutarse hasta instalarlo (pip install onnxruntime)."))
            warn.setWordWrap(True)
            warn.setStyleSheet(
                f"color: {theme.TEXT}; background: {theme.BG_DARK};"
                f" border: 1px solid {theme.BORDER}; border-radius: 4px;"
                f" padding: 8px; font-size: 11px;")
            self.body_layout.addWidget(warn)

        # Modelos en DOS columnas (ya son muchos): un grid de tarjetas.
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for i, model in enumerate(CATALOG):
            row = _ModelRow(model, self)
            self._rows.append(row)
            grid.addWidget(row, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body_layout.addLayout(grid)

        # Zona de progreso (oculta hasta que hay una descarga).
        self.progress = QProgressBar()
        self.progress.setStyleSheet(theme.progressbar_qss())
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        self.body_layout.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        self.status.setVisible(False)
        self.body_layout.addWidget(self.status)

        # Pie: total en disco + Cancelar (descarga) / Cerrar.
        foot = QHBoxLayout()
        self.total_label = QLabel(self._total_text())
        self.total_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        foot.addWidget(self.total_label)
        foot.addStretch(1)

        self.cancel_btn = QPushButton(t("common.cancel", default="Cancelar"))
        self.cancel_btn.setStyleSheet(theme.dialog_button_qss("QPushButton"))
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_download)
        foot.addWidget(self.cancel_btn)

        self.close_btn = QPushButton(t("common.close", default="Cerrar"))
        self.close_btn.setStyleSheet(theme.dialog_button_qss("QPushButton"))
        self.close_btn.clicked.connect(self.accept)
        foot.addWidget(self.close_btn)
        self.body_layout.addLayout(foot)

        self._body.setMinimumWidth(860)

    # ------------------------------------------------------------- estado
    def is_busy(self):
        return self._active_handle is not None

    def _total_text(self):
        return t("ai.models.total", default="En disco: {size}",
                 size=format_size(total_installed_size()))

    def _refresh_all(self):
        for row in self._rows:
            row.refresh()
        self.total_label.setText(self._total_text())

    # ------------------------------------------------------------- borrar
    def request_delete(self, model, row):
        if self.is_busy():
            return
        resp = imago_question(
            self, t("ai.models.title", default="Modelos de IA"),
            t("ai.models.confirm_delete",
              default="¿Borrar el modelo {name}?", name=model.nombre))
        if resp != QMessageBox.Yes:
            return
        delete_model(model)
        self._refresh_all()

    # ------------------------------------------------------------ descargar
    def request_download(self, model, row):
        if self.is_busy() or not model.configurado:
            return
        self._active_row = row
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status.setText(t("ai.models.downloading",
            default="Descargando {name}...", name=model.nombre))
        self.status.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.close_btn.setEnabled(False)
        self._refresh_all()   # deshabilita los botones de las filas (busy)

        self._active_handle = self._runner.submit(
            make_download_task(model),
            on_done=lambda path, m=model: self._on_download_done(m, path),
            on_error=lambda msg, m=model: self._on_download_error(m, msg),
            on_progress=self.progress.setValue,
        )

    def _cancel_download(self):
        if self._active_handle is not None:
            self._active_handle.cancel()
        self._finish_download()

    def _on_download_done(self, model, path):
        if path is None:      # cancelada
            self._finish_download()
            return
        self._finish_download()

    def _on_download_error(self, model, message):
        self._finish_download()
        self.status.setText(t("ai.models.dl_error",
            default="No se pudo descargar: {err}", err=message))
        self.status.setVisible(True)

    def _finish_download(self):
        self._active_handle = None
        self._active_row = None
        self.progress.setVisible(False)
        self.status.setVisible(False)
        self.cancel_btn.setVisible(False)
        self.close_btn.setEnabled(True)
        self._refresh_all()

    def reject(self):
        # Si hay una descarga en curso, cancelarla antes de cerrar.
        if self._active_handle is not None:
            self._active_handle.cancel()
        super().reject()
