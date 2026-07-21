# ai/subproc.py
"""Ejecucion de la inferencia de IA en un PROCESO APARTE (aislamiento de crashes).

Ver ai/subproc_worker.py para el porque (access violation NATIVO de DirectML con
modelos pesados como SCUNet). Aqui vive la parte del proceso PRINCIPAL: run_model()
lanza el hijo, le pasa la funcion a ejecutar, bombea el progreso a la barra, propaga
la cancelacion y —si el hijo se cae de forma nativa usando la GPU— reintenta
automaticamente en CPU dejando un aviso para el usuario.

IMPORTANTE: este modulo NO importa onnxruntime. Todo el onnxruntime vive en el hijo,
asi un fallo nativo suyo jamas puede tumbar la GUI.

Contrato: run_model() se llama DENTRO de la funcion de trabajo del InferenceRunner
(hilo secundario), en el sitio donde antes se llamaba a la funcion ai.* directamente.
"""
import os
import sys
import time
import secrets
import shutil
import subprocess
import tempfile
import threading

from i18n import t

# Raiz del proyecto (padre de ai/): cwd del hijo para que "import ai.*" funcione.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SENTINEL = object()
_CANCEL_GRACE = 0.5

# Aviso "la GPU fallo y se reintento en CPU": lo marca el hilo de trabajo y lo
# consume la GUI (hilo principal) para mostrarlo una vez por sesion.
_gpu_fallback = None
_gpu_fallback_lock = threading.Lock()

# Modelos que YA demostraron fallar solo en la GPU en ESTA maquina: no se vuelve
# a intentar la GPU con ellos, van directos a CPU. Asi no se
# repite el crash/error, la recarga del modelo ni el aviso. Se PERSISTE en QSettings
# (clave "ai/gpu_unsafe") para no reintentar-y-fallar en cada sesion; se limpia al
# cambiar la preferencia de GPU (Preferencias -> IA), por si se actualiza el driver.
# None = todavia no cargado de disco. Se guarda como "module:func" separados por \n.
_gpu_unsafe = None

# Version del mapa de marcas: SUBELA cuando cambien los modelos detras de un tag
# module:func (las marcas viejas ya no aplican al modelo nuevo). Al arrancar, si la
# version guardada no coincide, se descartan las marcas persistidas y se reevalua la
# GPU. v3 descarta marcas antiguas creadas por errores que tambien fallaban en CPU.
_GPU_UNSAFE_VERSION = 3


def _gpu_unsafe_set():
    """Conjunto (perezoso, cargado de QSettings) de tags "module:func" que fallaron en
    la GPU. Llamar con _gpu_fallback_lock tomado."""
    global _gpu_unsafe
    if _gpu_unsafe is None:
        from app_paths import settings as app_settings
        qs = app_settings()
        if qs.value("ai/gpu_unsafe_version", 0, type=int) != _GPU_UNSAFE_VERSION:
            # Marcas de una version anterior (otros modelos): ya no valen -> reevaluar.
            qs.remove("ai/gpu_unsafe")
            qs.setValue("ai/gpu_unsafe_version", _GPU_UNSAFE_VERSION)
            _gpu_unsafe = set()
        else:
            raw = qs.value("ai/gpu_unsafe", "", type=str) or ""
            _gpu_unsafe = set(x for x in raw.split("\n") if x)
    return _gpu_unsafe


def _mark_gpu_unsafe(module, func):
    """Apunta (y persiste) que module.func falla en la GPU. Con _gpu_fallback_lock tomado."""
    s = _gpu_unsafe_set()
    tag = "%s:%s" % (module, func)
    if tag not in s:
        s.add(tag)
        from app_paths import settings as app_settings
        app_settings().setValue("ai/gpu_unsafe", "\n".join(sorted(s)))


def clear_gpu_unsafe():
    """Olvida los modelos marcados como 'GPU no apta' para que se reevalue la GPU con
    ellos (p. ej. tras actualizar el driver). Se llama al cambiar la preferencia de GPU."""
    global _gpu_unsafe
    with _gpu_fallback_lock:
        _gpu_unsafe = set()
        from app_paths import settings as app_settings
        app_settings().remove("ai/gpu_unsafe")


class InferenceProcessCrash(Exception):
    """El proceso de inferencia murio sin devolver resultado (crash nativo)."""


def _use_gpu():
    """Preferencia del usuario (Preferencias -> IA). Se lee aqui, en el proceso
    principal (que ya tiene Qt), para no cargar QtCore/QSettings en el hijo."""
    from app_paths import settings as app_settings
    return app_settings().value("ai/use_gpu", True, type=bool)


def _mark_gpu_fallback(label):
    global _gpu_fallback
    with _gpu_fallback_lock:
        _gpu_fallback = label


def pop_gpu_fallback():
    """Devuelve (y limpia) la etiqueta del ultimo reintento en CPU, o None. La GUI
    lo consulta al terminar un trabajo para avisar de que la GPU fallo."""
    global _gpu_fallback
    with _gpu_fallback_lock:
        v = _gpu_fallback
        _gpu_fallback = None
        return v


def run_model(module, func, *args, report=None, token=None, **kwargs):
    """Ejecuta `module.func(*args, **kwargs)` en un proceso aparte y devuelve su
    resultado. En el hijo se inyecta un `report`/`token` propios si la funcion los
    acepta (el `report`/`token` de aqui son del proceso principal y no cruzan).

    Si el hijo se cae de forma NATIVA (tipico de DirectML con modelos pesados) y se
    estaba usando la GPU, reintenta UNA vez en CPU y deja un aviso (pop_gpu_fallback).
    Devuelve None si se cancelo. Los errores normales de Python del hijo (que no sean
    fallo de GPU) se propagan como RuntimeError con su texto."""
    tag = "%s:%s" % (module, func)
    with _gpu_fallback_lock:
        known_bad = tag in _gpu_unsafe_set()
    # Si este modelo ya fallo en la GPU en esta maquina, va directo a CPU.
    prefer_gpu = bool(_use_gpu()) and not known_bad
    if not prefer_gpu:
        return _run_cpu(module, func, args, kwargs, report, token)

    # Intento en GPU. Un fallo solo se atribuye permanentemente al proveedor si
    # el MISMO trabajo termina bien al reintentarlo en CPU. Si CPU tambien falla
    # (modelo corrupto, entrada invalida, error de codigo...), se conserva el error
    # sin contaminar la preferencia de futuras sesiones.
    try:
        return _run_isolated(module, func, args, kwargs, force_cpu=False,
                             report=report, token=token)
    except Exception:
        if token is not None and token.cancelled:
            return None
        result = _run_cpu(module, func, args, kwargs, report, token)
        if token is not None and token.cancelled:
            return None
        with _gpu_fallback_lock:
            _mark_gpu_unsafe(module, func)
        _mark_gpu_fallback(func)
        return result


def _run_cpu(module, func, args, kwargs, report, token):
    """Ejecuta en CPU (ultima red de seguridad). Traduce un crash nativo a un mensaje
    claro; deja pasar los errores normales de Python del hijo con su texto."""
    try:
        return _run_isolated(module, func, args, kwargs, force_cpu=True,
                             report=report, token=token)
    except InferenceProcessCrash:
        if token is not None and token.cancelled:
            return None
        raise RuntimeError(t("ai.error.crash",
                             default="La operacion de IA se detuvo de forma inesperada."))


def _run_isolated(module, func, args, kwargs, force_cpu, report, token):
    """Lanza el hijo, le manda la peticion y bombea sus mensajes. Devuelve el
    resultado, None si se cancelo, o lanza InferenceProcessCrash si el hijo murio sin
    responder (crash nativo). Los ("error", ...) del hijo se relanzan como RuntimeError."""
    from multiprocessing.connection import Listener
    from ai.ipc_arrays import IPCArrayCancelled, pack_arrays, unpack_arrays

    listener = None
    proc = None
    conn = None
    cancel_deadline = None
    ipc_dir = tempfile.mkdtemp(prefix="imago_ai_ipc_")
    try:
        authkey = secrets.token_bytes(24)
        listener = Listener(("127.0.0.1", 0), authkey=authkey)
        host, port = listener.address
        # Como lanzar el hijo. En desarrollo: "python -m ai.subproc_worker ...".
        # En el .exe congelado no hay python ni "-m": se relanza el ejecutable.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--ai-worker", host, str(port), authkey.hex()]
            child_cwd = os.path.dirname(sys.executable)
        else:
            cmd = [sys.executable, "-m", "ai.subproc_worker",
                   host, str(port), authkey.hex()]
            child_cwd = _PROJECT_ROOT
        proc = subprocess.Popen(
            cmd, cwd=child_cwd,
            # El error real llega por el canal; un crash nativo se detecta por
            # el codigo de salida. El hijo no debe ensuciar la terminal.
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        conn = _accept(listener, timeout=120, proc=proc, token=token)
        if conn is None:
            if token is not None and token.cancelled:
                return None
            raise InferenceProcessCrash("no-connect")
        if token is not None and token.cancelled:
            return None
        cancelled = lambda: token is not None and token.cancelled
        try:
            packed_args = pack_arrays(args, ipc_dir, "input", cancelled)
            packed_kwargs = pack_arrays(kwargs, ipc_dir, "input", cancelled)
        except IPCArrayCancelled:
            return None
        conn.send({"module": module, "func": func, "args": packed_args,
                   "kwargs": packed_kwargs, "force_cpu": force_cpu,
                   "ipc_dir": ipc_dir})

        result = _SENTINEL
        while True:
            try:
                ready = conn.poll(0.1)
            except Exception:
                break                       # canal roto: el hijo murio
            if ready:
                try:
                    msg = conn.recv()
                except (EOFError, OSError):
                    break                   # el hijo cerro/murio a mitad
                kind = msg[0]
                if kind == "progress":
                    if report is not None:
                        report(msg[1])
                elif kind == "result":
                    if token is not None and token.cancelled:
                        result = None
                    else:
                        try:
                            result = unpack_arrays(
                                msg[1], ipc_dir, copy_arrays=True,
                                is_cancelled=cancelled)
                        except IPCArrayCancelled:
                            result = None
                    break
                elif kind == "error":
                    raise RuntimeError(msg[1])
            elif proc.poll() is not None:
                break                       # el hijo salio sin devolver resultado
            # Cancelacion: se pide por el canal; si no responde enseguida se
            # termina. No se deja al cierre de Imago esperando varios segundos.
            if token is not None and token.cancelled:
                if cancel_deadline is None:
                    try:
                        conn.send("cancel")
                    except Exception:
                        pass
                    cancel_deadline = time.monotonic() + _CANCEL_GRACE
                elif time.monotonic() > cancel_deadline:
                    break

        if result is _SENTINEL:
            if token is not None and token.cancelled:
                return None
            raise InferenceProcessCrash("no-result")
        return result
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        if listener is not None:
            try:
                listener.close()
            except Exception:
                pass
        if proc is not None:
            _terminate(proc)
        # En Windows hay que terminar primero el hijo: un memmap abierto impide
        # borrar su archivo. En POSIX el mismo orden evita temporales huerfanos.
        _cleanup_ipc_dir(ipc_dir)


def _accept(listener, timeout, proc=None, token=None):
    """listener.accept() con limite de tiempo (accept() no lo trae de serie). El hijo
    conecta ANTES de importar onnx/cargar el modelo, asi que llega en <1 s; el timeout
    solo cubre un arranque anomalo. Devuelve la conexion o None."""
    holder = {}

    def _target():
        try:
            holder["conn"] = listener.accept()
        except Exception as exc:            # el listener se cerro u otro fallo
            holder["err"] = exc

    th = threading.Thread(target=_target, daemon=True)
    th.start()
    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        if "conn" in holder:
            return holder["conn"]
        if "err" in holder:
            break
        if token is not None and token.cancelled:
            break
        if proc is not None and proc.poll() is not None:
            break
        th.join(0.05)
    if "conn" in holder:
        return holder["conn"]
    # Timeout: cerrar el listener desbloquea el accept() del hilo (que es daemon).
    try:
        listener.close()
    except Exception:
        pass
    return None


def _terminate(proc):
    """Cierra el hijo si sigue vivo (fin normal, cancelacion o error)."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=0.75)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=0.75)
        except Exception:
            pass


def _cleanup_ipc_dir(path):
    """Borra temporales tras cerrar mapas/proceso, con reintento para Windows."""
    for _attempt in range(3):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.05)
    # No se enmascara un resultado de IA correcto por un antivirus que retenga
    # brevemente el archivo; un ultimo intento tolerante evita romper el callback.
    shutil.rmtree(path, ignore_errors=True)
