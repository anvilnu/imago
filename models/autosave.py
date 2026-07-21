# models/autosave.py
"""Autoguardado y recuperación ante fallos.

Cada N minutos escribe una copia de recuperación (.imago, capas completas) de
cada pestaña con cambios SIN GUARDAR en una carpeta propia, junto a un manifiesto
session.json. En un cierre LIMPIO se borran las copias de las pestañas; las que
el usuario haya decidido conservar permanecen para el siguiente arranque.

Reutiliza el formato nativo .imago (models.project_io), así que la recuperación
conserva todas las capas y sus propiedades."""

import os
import json
import re
import weakref
from datetime import datetime
from atomic_io import escribir_atomico
from PySide6.QtCore import QTimer
import app_paths
from ai.runner import InferenceRunner
from models.document_state import documento_pendiente
from models.project_io import crear_instantanea_proyecto, save_project


CLAVE_INTERVALO_MINUTOS = "autosave/interval_min"
INTERVALO_PREDETERMINADO_MIN = 3
INTERVALO_MINIMO_MIN = 1
INTERVALO_MAXIMO_MIN = 60


def normalizar_intervalo_minutos(valor):
    """Devuelve un intervalo de autoguardado válido y acotado, en minutos."""
    try:
        minutos = int(valor)
    except (TypeError, ValueError):
        minutos = INTERVALO_PREDETERMINADO_MIN
    return max(INTERVALO_MINIMO_MIN, min(INTERVALO_MAXIMO_MIN, minutos))


def intervalo_desde_settings(settings):
    """Lee de QSettings el intervalo compartido por el arranque y Preferencias."""
    return normalizar_intervalo_minutos(
        settings.value(CLAVE_INTERVALO_MINUTOS,
                       INTERVALO_PREDETERMINADO_MIN))


class AutoSaveManager:
    def __init__(self, main_window,
                 interval_min=INTERVALO_PREDETERMINADO_MIN):
        self.main = main_window
        self._counter = 0
        # Una sola cola de E/S para toda la ventana: evita que un autoguardado
        # comprima a la vez que Guardar/Exportar sobre el mismo documento y
        # reduce los picos de CPU, RAM y disco.
        runner = getattr(main_window, "_io_runner", None)
        if runner is None:
            runner = InferenceRunner(main_window)
            main_window._io_runner = runner
        self._runner = runner
        self._handle = None
        self._repetir = False
        self._detenido = False

        base = app_paths.base_datos()
        if not base:
            base = os.path.join(os.path.expanduser("~"), ".imago")
        self.dir = os.path.join(base, "imago_recuperacion")
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError:
            pass

        # Las copias que el usuario decide conservar sin abrir no pertenecen a
        # ninguna pestaña. Deben seguir en el manifiesto y sobrevivir incluso a
        # un cierre limpio posterior.
        self._entradas_diferidas = []
        self._counter = max(self._counter, self._ultimo_id_en_disco())

        self.timer = QTimer(self.main)
        self.timer.timeout.connect(self.snapshot)
        self.set_interval_minutes(interval_min)

    def set_interval_minutes(self, interval_min):
        """Cambia el intervalo y reinicia el cómputo si el timer está activo."""
        self.interval_min = normalizar_intervalo_minutos(interval_min)
        self.timer.setInterval(self.interval_min * 60 * 1000)
        return self.interval_min

    def start(self):
        self._detenido = False
        self.timer.start()

    def stop(self):
        self._detenido = True
        self.timer.stop()
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    # ------------------------------------------------------------------ util
    def _session_path(self):
        return os.path.join(self.dir, "session.json")

    def _ultimo_id_en_disco(self):
        ultimo = 0
        try:
            nombres = os.listdir(self.dir)
        except OSError:
            return ultimo
        for nombre in nombres:
            match = re.fullmatch(r"doc_(\d+)\.imago", nombre)
            if match:
                ultimo = max(ultimo, int(match.group(1)))
        return ultimo

    @staticmethod
    def _entrada_manifest(entrada):
        """Quita metadatos calculados que no forman parte de session.json."""
        salida = {"file": entrada.get("file")}
        for clave in ("title", "project_path"):
            valor = entrada.get(clave)
            if isinstance(valor, str):
                salida[clave] = valor
        miniatura = entrada.get("thumbnail")
        if (isinstance(miniatura, str)
                and re.fullmatch(r"doc_\d+\.thumb\.png", miniatura)):
            salida["thumbnail"] = miniatura
        return salida

    def _entradas_diferidas_validas(self):
        entradas = []
        vistos = set()
        for entrada in getattr(self, "_entradas_diferidas", []):
            nombre = entrada.get("file", "")
            if (not isinstance(nombre, str)
                    or not re.fullmatch(r"doc_\d+\.imago", nombre)
                    or nombre in vistos
                    or not os.path.exists(os.path.join(self.dir, nombre))):
                continue
            vistos.add(nombre)
            entradas.append(self._entrada_manifest(entrada))
        self._entradas_diferidas = entradas
        return [dict(entrada) for entrada in entradas]

    @staticmethod
    def _nombres_entrada(entrada):
        patrones = {
            "file": r"doc_\d+\.imago",
            "thumbnail": r"doc_\d+\.thumb\.png",
        }
        for clave, patron in patrones.items():
            nombre = entrada.get(clave)
            if isinstance(nombre, str) and re.fullmatch(patron, nombre):
                yield nombre

    def _miniatura_canvas(self, canvas):
        """Copia la miniatura ya calculada por la barra de pestañas.

        No se fuerza una composición nueva: en documentos grandes supondría un
        buffer del tamaño completo solo para una vista previa de 150 px.
        """
        barra = getattr(self.main, "thumbnail_bar", None)
        obtener = getattr(barra, "preview_for_canvas", None)
        if not callable(obtener):
            return None
        try:
            pixmap = obtener(canvas)
            if pixmap is None or pixmap.isNull():
                return None
            return pixmap.toImage()
        except (AttributeError, RuntimeError):
            return None

    @staticmethod
    def _guardar_miniatura(imagen, ruta):
        if imagen is None or imagen.isNull():
            return False
        return escribir_atomico(
            ruta, lambda temporal: imagen.save(temporal, "PNG"))

    def _iter_canvases(self):
        tabs = self.main.tabs
        for i in range(tabs.count()):
            marker = tabs.widget(i)
            if marker is not None and hasattr(marker, "canvas"):
                yield i, marker.canvas

    def _notificar_estado(self, estado, hora=None):
        """Actualiza el indicador sin acoplar el gestor a widgets concretos.

        Todas las llamadas del flujo normal ocurren en el hilo GUI: ``snapshot``
        parte del temporizador y los callbacks del runner vuelven a dicho hilo.
        """
        callback = getattr(self.main, "actualizar_estado_autoguardado", None)
        if callable(callback):
            callback(estado, hora)

    @staticmethod
    def _needs_recovery(canvas):
        """Una pestaña necesita copia si tiene cambios sin guardar (pila de
        deshacer no 'limpia') o es un documento recuperado aún sin guardar."""
        return documento_pendiente(canvas)

    # --------------------------------------------------------------- escribir
    def snapshot(self):
        """Captura rápido en GUI y comprime/escribe en el worker de E/S."""
        # Los tests y consumidores mínimos que construyen la clase con __new__
        # conservan el camino síncrono histórico.
        if not hasattr(self, "_runner"):
            return self._snapshot_sincrono()
        if self._detenido:
            return None
        if self._handle is not None:
            self._repetir = True
            return None

        trabajos = []
        entries = self._entradas_diferidas_validas()
        keep = {
            nombre for entrada in entries
            for nombre in self._nombres_entrada(entrada)
        }
        hay_pendientes = bool(entries)
        for i, canvas in self._iter_canvases():
            if not self._needs_recovery(canvas):
                continue
            hay_pendientes = True
            if not hasattr(canvas, "_autosave_id"):
                self._counter += 1
                canvas._autosave_id = self._counter
            fname = "doc_%d.imago" % canvas._autosave_id
            path = os.path.join(self.dir, fname)
            thumb_name = "doc_%d.thumb.png" % canvas._autosave_id
            thumb_path = os.path.join(self.dir, thumb_name)
            revision = canvas.revision_autoguardado
            if (getattr(canvas, "_autosave_revision", None) != revision
                    or not os.path.exists(path)):
                trabajos.append({
                    "canvas": weakref.ref(canvas),
                    "revision": revision,
                    "path": path,
                    "thumbnail_path": thumb_path,
                    "thumbnail": self._miniatura_canvas(canvas),
                    "snapshot": crear_instantanea_proyecto(canvas),
                })
            entries.append({
                "file": fname,
                "title": self.main.tabs.tabText(i),
                "project_path": getattr(canvas, "project_path", None),
                "thumbnail": thumb_name,
            })
            keep.update((fname, thumb_name))

        if not hay_pendientes:
            self.clear()
            return None

        self._notificar_estado("guardando")

        def trabajo(_report, token):
            snapshot_completo = True
            guardados = []
            for item in trabajos:
                if token.cancelled:
                    return None
                ok = save_project(item["snapshot"], item["path"], token=token)
                if ok and not token.cancelled:
                    self._guardar_miniatura(
                        item["thumbnail"], item["thumbnail_path"])
                guardados.append((item["canvas"], item["revision"], ok))
                if not ok:
                    snapshot_completo = False

            # Una copia fallida que ya tenía versión anterior se conserva, pero
            # no se publica un manifiesto que mezcle revisiones distintas.
            if any(not os.path.exists(os.path.join(self.dir, e["file"]))
                   for e in entries):
                snapshot_completo = False
            publicado = False
            if entries and snapshot_completo and not token.cancelled:
                def _escribir_session(ruta_temporal):
                    with open(ruta_temporal, "w", encoding="utf-8") as f:
                        json.dump({"entries": entries}, f, ensure_ascii=False)
                    return not token.cancelled

                publicado = escribir_atomico(
                    self._session_path(), _escribir_session)
                if publicado and not token.cancelled:
                    self._prune(keep)
            return guardados, publicado

        def terminado(resultado):
            self._handle = None
            if resultado is not None:
                guardados, publicado = resultado
                for ref_canvas, revision, ok in guardados:
                    canvas = ref_canvas()
                    if publicado and ok and canvas is not None:
                        if canvas.revision_autoguardado == revision:
                            canvas._autosave_revision = revision
                        else:
                            # Hubo otra edición mientras se comprimía la copia:
                            # encadenar una instantánea de la revisión nueva.
                            self._repetir = True
                if publicado:
                    self._notificar_estado(
                        "guardado", datetime.now().strftime("%H:%M:%S"))
                else:
                    self._notificar_estado("error")
            self._programar_repeticion()

        def error(_mensaje):
            self._handle = None
            self._notificar_estado("error")
            self._programar_repeticion()

        self._handle = self._runner.submit(
            trabajo, on_done=terminado, on_error=error)
        return None

    def _programar_repeticion(self):
        if self._repetir and not self._detenido:
            self._repetir = False
            QTimer.singleShot(0, self.snapshot)

    def _snapshot_sincrono(self):
        """Escribe copias de las pestañas con cambios sin guardar + el manifiesto.
        Solo reescribe un documento si cambió desde la última copia (ahorra disco).

        La revisión es monotónica e independiente de QUndoStack.index(): dos
        ramas distintas del historial pueden ocupar el mismo índice.
        """
        entries = self._entradas_diferidas_validas()
        keep = {
            nombre for entrada in entries
            for nombre in self._nombres_entrada(entrada)
        }
        hay_pendientes = bool(entries)
        snapshot_completo = True
        for i, canvas in self._iter_canvases():
            if not self._needs_recovery(canvas):
                continue
            hay_pendientes = True
            if not hasattr(canvas, "_autosave_id"):
                self._counter += 1
                canvas._autosave_id = self._counter
            fname = "doc_%d.imago" % canvas._autosave_id
            path = os.path.join(self.dir, fname)
            thumb_name = "doc_%d.thumb.png" % canvas._autosave_id
            thumb_path = os.path.join(self.dir, thumb_name)
            revision = canvas.revision_autoguardado
            if (getattr(canvas, "_autosave_revision", None) != revision
                    or not os.path.exists(path)):
                if save_project(canvas, path):
                    canvas._autosave_revision = revision
                    self._guardar_miniatura(
                        self._miniatura_canvas(canvas), thumb_path)
                else:
                    snapshot_completo = False
            # Si la copia nueva falló pero había una anterior, se conserva y se
            # mantiene en el manifiesto. Sin ningún archivo válido no se anuncia.
            if not os.path.exists(path):
                snapshot_completo = False
                continue
            entries.append({
                "file": fname,
                "title": self.main.tabs.tabText(i),
                "project_path": getattr(canvas, "project_path", None),
                "thumbnail": thumb_name,
            })
            keep.update((fname, thumb_name))

        if hay_pendientes:
            self._notificar_estado("guardando")

        if entries and snapshot_completo:
            def _escribir_session(ruta_temporal):
                with open(ruta_temporal, "w", encoding="utf-8") as f:
                    json.dump({"entries": entries}, f, ensure_ascii=False)
                return True

            # Solo se podan copias antiguas después de publicar el manifiesto
            # nuevo. Si falla, el session.json anterior y sus documentos siguen
            # formando un conjunto recuperable coherente.
            if escribir_atomico(self._session_path(), _escribir_session):
                self._prune(keep)
                self._notificar_estado(
                    "guardado", datetime.now().strftime("%H:%M:%S"))
            else:
                self._notificar_estado("error")
        elif hay_pendientes:
            self._notificar_estado("error")
        elif not hay_pendientes:
            self.clear()

    def _prune(self, keep):
        """Borra las copias .imago de pestañas que ya no necesitan recuperación."""
        try:
            for fn in os.listdir(self.dir):
                es_copia = fn.startswith("doc_") and (
                    fn.endswith(".imago") or fn.endswith(".thumb.png"))
                if es_copia and fn not in keep:
                    try:
                        os.remove(os.path.join(self.dir, fn))
                    except OSError:
                        pass
        except OSError:
            pass

    def clear(self, incluir_diferidas=False):
        """Limpia copias activas sin destruir recuperaciones conservadas.

        ``incluir_diferidas`` solo se usa para un descarte explícito del usuario.
        """
        diferidas = ([] if incluir_diferidas
                     else self._entradas_diferidas_validas())
        conservar = {
            nombre for entrada in diferidas
            for nombre in self._nombres_entrada(entrada)
        }
        if diferidas:
            conservar.add("session.json")
        try:
            for fn in os.listdir(self.dir):
                if fn in conservar:
                    continue
                try:
                    os.remove(os.path.join(self.dir, fn))
                except OSError:
                    pass
        except OSError:
            pass
        if incluir_diferidas:
            self._entradas_diferidas = []
        elif diferidas:
            def _escribir_session(ruta_temporal):
                with open(ruta_temporal, "w", encoding="utf-8") as f:
                    json.dump({"entries": diferidas}, f, ensure_ascii=False)
                return True
            escribir_atomico(self._session_path(), _escribir_session)

    # -------------------------------------------------------------- recuperar
    def pending_entries(self):
        """Lista de documentos recuperables de una sesión anterior (o [] si no hay).
        Cada entrada incluye 'path' (ruta de la copia .imago), 'title', 'project_path'."""
        sp = self._session_path()
        if not os.path.exists(sp):
            return []
        try:
            with open(sp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(data, dict):
            return []
        entradas = data.get("entries", [])
        if not isinstance(entradas, list):
            return []
        out = []
        for e in entradas:
            if not isinstance(e, dict):
                continue
            nombre = e.get("file", "")
            if (not isinstance(nombre, str)
                    or not re.fullmatch(r"doc_\d+\.imago", nombre)):
                continue
            fp = os.path.join(self.dir, nombre)
            if os.path.exists(fp):
                e = self._entrada_manifest(e)
                e["path"] = fp
                miniatura = e.get("thumbnail")
                if miniatura:
                    ruta_miniatura = os.path.join(self.dir, miniatura)
                    if os.path.exists(ruta_miniatura):
                        e["thumbnail_path"] = ruta_miniatura
                try:
                    e["modified_at"] = os.path.getmtime(fp)
                except OSError:
                    e["modified_at"] = None
                out.append(e)
        return out

    def defer_entries(self, entries):
        """Conserva copias sin pestaña para otra decisión o sesión."""
        actuales = {
            entrada.get("file"): entrada
            for entrada in self._entradas_diferidas_validas()
        }
        for entrada in entries:
            nombre = entrada.get("file")
            if (isinstance(nombre, str)
                    and re.fullmatch(r"doc_\d+\.imago", nombre)
                    and os.path.exists(os.path.join(self.dir, nombre))):
                actuales[nombre] = self._entrada_manifest(entrada)
        self._entradas_diferidas = list(actuales.values())

    def adopt_recovery(self, canvas, entry):
        """Vincula una copia abierta a su nuevo lienzo sin reescribirla."""
        nombre = entry.get("file", "")
        match = (re.fullmatch(r"doc_(\d+)\.imago", nombre)
                 if isinstance(nombre, str) else None)
        if match:
            identificador = int(match.group(1))
            canvas._autosave_id = identificador
            self._counter = max(self._counter, identificador)
        canvas._autosave_revision = canvas.revision_autoguardado
        self._entradas_diferidas = [
            diferida for diferida in self._entradas_diferidas_validas()
            if diferida.get("file") != nombre
        ]

    def discard_entries(self, entries):
        """Descarta únicamente las copias elegidas por el usuario."""
        nombres = {entrada.get("file") for entrada in entries}
        for entrada in entries:
            for nombre in self._nombres_entrada(entrada):
                try:
                    os.remove(os.path.join(self.dir, nombre))
                except OSError:
                    pass
        self._entradas_diferidas = [
            diferida for diferida in self._entradas_diferidas_validas()
            if diferida.get("file") not in nombres
        ]
