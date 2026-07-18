# menu_archivo.py
"""Acciones del menú Archivo de la ventana principal (mixin de MainWindow).

Extraído de main.py TAL CUAL (sin cambios de comportamiento): nuevo documento,
abrir (con PSD/SVG/animados y recuperación de autoguardado), guardar/guardar
como, imprimir, exportar (PDF/ORA/animación), calidad y filtros de formato,
y la lista de archivos recientes. MainWindow hereda de AccionesMenuArchivo,
así que los menús siguen conectando con self.* igual que antes."""
import os
from enum import Enum, auto

from PySide6.QtCore import Qt, QTimer, QFile
from PySide6.QtGui import QAction, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QWidget

from i18n import t
from atomic_io import ReemplazoAtomico, escribir_atomico
from new_dialog import ImageSizeDialog
from utilidades import cargar_imagen_orientada, _PILLOW_EXTRA
from widgets.custom_titlebar import imago_warning, imago_critical, imago_question
import theme


class ResultadoGuardado(Enum):
    """Resultado explícito de Guardar/Guardar como para los flujos de cierre."""

    EXITO = auto()
    CANCELADO = auto()
    ERROR = auto()


class _RecentItem(QWidget):
    """Fila del menu 'Abrir recientes': miniatura + nombre, clicable."""

    def __init__(self, path, pixmap, on_click):
        super().__init__()
        self._on_click = on_click
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 14, 4)
        lay.setSpacing(10)
        thumb = QLabel()
        thumb.setFixedSize(44, 44)
        thumb.setAlignment(Qt.AlignCenter)
        if pixmap is not None:
            thumb.setPixmap(pixmap)
        lay.addWidget(thumb)
        name = QLabel(os.path.basename(path))
        name.setStyleSheet(f"color:{theme.TEXT}; font-family:{theme.FONT}; font-size:12px; background: transparent;")
        lay.addWidget(name)
        lay.addStretch()
        self.setToolTip(path)
        self.setStyleSheet(
            "_RecentItem { background: transparent; }"
            "_RecentItem:hover { background-color: %s; }"
            "QLabel { background: transparent; }" % theme.ACCENT_DARK)

    def mouseReleaseEvent(self, event):
        self._on_click()


class AccionesMenuArchivo:
    def _tab_index_for_canvas(self, canvas):
        if not hasattr(self.tabs, "count"):
            return self.tabs.currentIndex()
        for indice in range(self.tabs.count()):
            marker = self.tabs.widget(indice)
            if marker is not None and getattr(marker, "canvas", None) is canvas:
                return indice
        return -1

    def _io_set_busy(self, busy, mensaje=None):
        """Presenta una operación de archivo sin bloquear la interacción Qt."""
        self._io_busy = bool(busy)
        acciones = [
            getattr(self, nombre, None) for nombre in (
                "save_action", "save_as_action", "export_pdf_action",
                "export_ora_action", "export_anim_action", "close_tab_action")
        ]
        acciones.extend(getattr(self, "_ai_actions", ()))
        if busy:
            self._io_action_states = [
                (accion, accion.isEnabled()) for accion in acciones
                if accion is not None
            ]
            for accion, _estado in self._io_action_states:
                accion.setEnabled(False)
        else:
            for accion, estado in getattr(self, "_io_action_states", ()):
                try:
                    accion.setEnabled(estado)
                except RuntimeError:
                    pass
            self._io_action_states = []

        # La barra es compartida con IA. No se pisan dos indicadores: si una IA
        # ya la posee, el guardado sigue funcionando y usa solo el mensaje.
        bar = getattr(self, "ai_progress_bar", None)
        btn = getattr(self, "ai_cancel_btn", None)
        mostrar = bool(busy and not getattr(self, "_ai_busy", False))
        if bar is not None and (mostrar or not getattr(self, "_ai_busy", False)):
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setVisible(mostrar)
        if btn is not None and (mostrar or not getattr(self, "_ai_busy", False)):
            btn.setVisible(mostrar)
            if mostrar:
                btn.setToolTip(t("io.cancel.tip"))
            elif not getattr(self, "_ai_busy", False):
                btn.setToolTip(t("ai.cancel.tip", default="Cancelar la operación de IA en curso"))
        if busy and mensaje and hasattr(self, "status_bar"):
            self.status_bar.showMessage(mensaje)

    def _io_progress(self, porcentaje):
        if getattr(self, "_ai_busy", False):
            return
        bar = getattr(self, "ai_progress_bar", None)
        if bar is not None:
            bar.setValue(max(0, min(100, int(porcentaje))))

    def _io_cancel_current(self):
        """Cancela el trabajo visible y libera su bucle Qt anidado."""
        handle = getattr(self, "_io_handle", None)
        if handle is None:
            return
        handle.cancel()
        self._io_handle = None
        self._io_cancelado = True
        bucle = getattr(self, "_io_event_loop", None)
        if bucle is not None:
            bucle.quit()

    def _ejecutar_trabajo_io(self, trabajo, mensaje):
        """Ejecuta ``trabajo(report, token)`` fuera del GUI y espera sin congelar.

        Devuelve ``(completado, resultado)``. En dobles de prueba que no son
        QObject conserva un camino directo para no exigir un QApplication.
        """
        from PySide6.QtCore import QObject, QEventLoop
        from PySide6.QtWidgets import QApplication
        from ai.runner import CancelToken, InferenceRunner

        if QApplication.instance() is None or not isinstance(self, QObject):
            token = CancelToken()
            try:
                self._io_error_message = None
                return True, trabajo(lambda _pct: None, token)
            except Exception as exc:
                self._io_error_message = str(exc)
                return False, None
        if getattr(self, "_io_handle", None) is not None:
            return False, None

        if getattr(self, "_io_runner", None) is None:
            self._io_runner = InferenceRunner(self)
        estado = {"completado": False, "resultado": None, "error": None}
        bucle = QEventLoop(self)
        self._io_event_loop = bucle
        self._io_cancelado = False

        def terminado(resultado):
            estado["completado"] = True
            estado["resultado"] = resultado
            self._io_handle = None
            bucle.quit()

        def error(mensaje_error):
            estado["error"] = mensaje_error
            self._io_handle = None
            bucle.quit()

        self._io_set_busy(True, mensaje)
        self._io_handle = self._io_runner.submit(
            trabajo, on_done=terminado, on_error=error,
            on_progress=self._io_progress)
        bucle.exec()
        cancelado = self._io_cancelado
        self._io_error_message = estado["error"]
        self._io_event_loop = None
        self._io_set_busy(False)
        if cancelado and hasattr(self, "status_bar"):
            self.status_bar.showMessage(t("status.io.cancelled"), 3000)
        return estado["completado"] and not cancelado, estado["resultado"]

    def new_file(self):
        # El tamaño del portapapeles ya NO se vuelca aquí: lo gobierna la casilla
        # 'Tamaño del portapapeles' del propio diálogo (desactivada por defecto).
        dialog = ImageSizeDialog(self, width=800, height=600,
                                 title=t("dlg.new", default="Nuevo"), show_fill=True)
        if dialog.exec() == ImageSizeDialog.Accepted:
            width, height = dialog.get_values()
            fill_color = self._resolve_new_canvas_fill(dialog.get_fill())
            self.create_new_tab_canvas(width, height, f"{t('dlg.untitled')} {self.tabs.count()}",
                                       dpi=dialog.get_dpi(), fill_color=fill_color)
            # SOLUCIÓN: Esperamos un instante a que la pestaña sea visible antes de ajustar el tamaño
            QTimer.singleShot(20, self.fit_canvas_to_screen)

    def _resolve_new_canvas_fill(self, fill_id):
        """Traduce la opción de Fondo del diálogo Nuevo a un QColor con el que
        rellenar el lienzo. 'primary' = color de la paleta (primario del lienzo
        activo, o negro si no hay ninguno). 'transparent' devuelve un color con
        alfa 0. None (diálogo sin desplegable) devuelve None → relleno blanco."""
        from PySide6.QtGui import QColor
        from PySide6.QtCore import Qt as _Qt
        if fill_id == "white":
            return QColor(_Qt.white)
        if fill_id == "black":
            return QColor(_Qt.black)
        if fill_id == "transparent":
            return QColor(_Qt.transparent)
        if fill_id == "primary":
            current = self.get_current_canvas()
            if current is not None and hasattr(current, "brush_color"):
                return QColor(current.brush_color)
            return QColor(_Qt.black)
        return None

    def _check_recovery(self):
        """Muestra el gestor de las copias dejadas por una sesión interrumpida."""
        if not hasattr(self, 'autosave'):
            return
        entries = self.autosave.pending_entries()
        if not entries:
            return
        from PySide6.QtWidgets import QDialog
        from widgets.recovery_manager import RecoveryManagerDialog

        # Desde este momento ninguna limpieza automática puede borrar estas
        # copias. Cerrar el gestor con la X equivale a conservarlas todas.
        self.autosave.defer_entries(entries)
        dialog = RecoveryManagerDialog(entries, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        decisiones = dialog.decisiones()
        abrir = [entrada for entrada, accion in decisiones if accion == "open"]
        descartar = [entrada for entrada, accion in decisiones
                     if accion == "discard"]
        if descartar:
            self.autosave.discard_entries(descartar)
        self._restore_recovery(abrir)

        # Publica en un único manifiesto los lienzos abiertos y las copias que
        # siguen diferidas; las que no pudieron abrirse también se conservan.
        self.autosave.snapshot()

    def _restore_recovery(self, entries):
        """Reabre en pestañas cada documento de recuperación y lo marca como NO
        guardado (para que avise al cerrar y se siga autoguardando)."""
        from models.project_io import load_project
        restored = 0
        for e in entries:
            completado, data = AccionesMenuArchivo._ejecutar_trabajo_io(
                self, lambda report, token, ruta=e["path"]: load_project(
                    ruta, report=report, token=token),
                t("status.io.loading"))
            if not completado or not data:
                continue
            title = e.get("title") or t("msg.recovered_default")
            canvas = self.create_new_tab_canvas(data["width"], data["height"], title)
            canvas.apply_project_data(data)
            if e.get("project_path"):
                canvas.project_path = e["project_path"]
            canvas.recovered_dirty = True   # aún sin guardar de verdad
            adoptar = getattr(self.autosave, "adopt_recovery", None)
            if callable(adoptar):
                adoptar(canvas, e)
            restored += 1
        if restored:
            self._close_pristine_tabs(except_index=self.tabs.currentIndex())
            self.status_bar.showMessage(t("status.recovered", n=restored), 6000)
        return restored

    def _close_pristine_tabs(self, except_index):
        """Cierra las pestañas con lienzos en blanco totalmente intactos:
        sin ninguna acción en el historial, sin proyecto asociado y con su
        única capa inicial. Se llama al abrir una imagen o proyecto para
        que el lienzo de bienvenida no estorbe. Recorremos al revés porque
        eliminar pestañas desplaza los índices."""
        for i in range(self.tabs.count() - 1, -1, -1):
            if i == except_index:
                continue
            marker = self.tabs.widget(i)
            if not marker or not hasattr(marker, 'canvas'):
                continue
            c = marker.canvas
            pristine = (getattr(c, 'is_welcome_canvas', False)  # Solo el lienzo del arranque
                        and c.undo_stack.count() == 0           # Ni un solo trazo u operación
                        and c.project_path is None              # Nunca guardado como proyecto
                        and getattr(c, 'image_path', None) is None  # ni como imagen
                        and len(c.layers) == 1)                 # Solo su capa Fondo inicial
            if pristine:
                self._retirar_y_destruir_pestana(i)

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, t("dlg.open_title"), self.last_opened_dir, self._supported_open_filter())
        if file_path:
            self.open_path(file_path)

    def open_path(self, file_path):
        """Abre una ruta concreta (del dialogo o de 'Abrir recientes'). El .imago
        restaura el proyecto con capas; cualquier otra imagen se carga y queda
        ASOCIADA al archivo, de modo que Ctrl+S la sobrescribira (Opcion A)."""
        if not file_path:
            return
        if not os.path.exists(file_path):
            imago_warning(self, t("msg.open.title"), t("msg.open.not_found", file_path=file_path))
            self._remove_recent(file_path)
            return

        self.last_opened_dir = os.path.dirname(file_path)
        self.settings.setValue("last_opened_dir", self.last_opened_dir)

        # PROYECTO IMAGO: restaurar todas las capas
        if file_path.lower().endswith(".imago"):
            from models.project_io import load_project
            completado, data = AccionesMenuArchivo._ejecutar_trabajo_io(
                self, lambda report, token: load_project(
                    file_path, report=report, token=token),
                t("status.io.loading"))
            if not completado:
                if not getattr(self, "_io_cancelado", False):
                    imago_critical(
                        self, t("msg.error.open_proj"),
                        getattr(self, "_io_error_message", None)
                        or t("msg.error.open_proj"))
                return
            canvas = self.create_new_tab_canvas(data["width"], data["height"],
                                                os.path.basename(file_path))
            canvas.apply_project_data(data)
            canvas.project_path = file_path
            canvas.image_path = None
            canvas.undo_stack.setClean()
            QTimer.singleShot(20, self.fit_canvas_to_screen)
            self._close_pristine_tabs(except_index=self.tabs.currentIndex())
            self._add_recent(file_path)
            return

        # PHOTOSHOP: importar .psd/.psb con capas (solo LECTURA; se guarda como .imago)
        if file_path.lower().endswith((".psd", ".psb")):
            self._open_psd(file_path)
            return

        # SVG: vectorial, sin píxeles propios; se pregunta a qué tamaño rasterizarlo
        if file_path.lower().endswith((".svg", ".svgz")):
            self._open_svg(file_path)
            return

        # GIF/WebP ANIMADO: se ofrece abrir los fotogramas como capas. Si solo
        # tiene un fotograma (o se responde que no), sigue el flujo normal.
        if file_path.lower().endswith((".gif", ".webp")):
            if self._open_animated(file_path):
                return

        # IMAGEN PLANA: se carga (con su rotación EXIF) y queda asociada al archivo
        def cargar_plana(report, token):
            report(10)
            imagen = cargar_imagen_orientada(file_path)
            if token.cancelled:
                return QImage(), None
            exif = None
            if not imagen.isNull():
                from exif_utils import leer_exif
                exif = leer_exif(file_path)
            report(100)
            return imagen, exif

        completado, carga = AccionesMenuArchivo._ejecutar_trabajo_io(
            self, cargar_plana, t("status.io.loading"))
        if not completado:
            return
        loaded_image, source_exif = carga
        if not loaded_image.isNull():
            converted_image = loaded_image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            canvas = self.create_new_tab_canvas(loaded_image.width(), loaded_image.height(),
                                                os.path.basename(file_path), converted_image)
            # Conservar la resolución (PPP) del archivo si la trae, para que se
            # mantenga al volver a guardar. dotsPerMeterX -> PPP = dpm * 0.0254.
            dpm = loaded_image.dotsPerMeterX()
            if dpm > 0:
                canvas.dpi = round(dpm * 0.0254, 2)
            canvas.image_path = file_path
            canvas.project_path = None
            # EXIF de origen (fecha, cámara, GPS...): se guarda para reincrustarlo
            # tal cual al reescribir un JPEG, sin recomprimir (ver exif_utils.py).
            canvas.source_exif = source_exif
            canvas.image_quality = self._default_quality(
                os.path.splitext(file_path)[1].lstrip("."))
            canvas.undo_stack.setClean()
            QTimer.singleShot(20, self.fit_canvas_to_screen)
            self._close_pristine_tabs(except_index=self.tabs.currentIndex())
            self._add_recent(file_path)
        else:
            # AVIF/HEIC/JXL sin su plugin de Pillow: aviso con el paquete que falta
            ext = os.path.splitext(file_path)[1].lower().lstrip(".")
            paquete = _PILLOW_EXTRA.get(ext)
            import importlib.util as _ilu
            modulo = "pillow_jxl" if ext == "jxl" else "pillow_heif"
            if paquete and _ilu.find_spec(modulo) is None:
                imago_warning(self, t("msg.open.title"),
                              t("msg.open.plugin_needed", fmt=ext.upper(), pkg=paquete))
            else:
                imago_warning(self, t("msg.open.title"), t("msg.error.open_img", file_path=file_path))


    def _open_psd(self, file_path):
        """Importa un archivo de Photoshop como proyecto con capas (ver
        models/psd_io.py: correspondencias y limites). El lienzo queda SIN
        archivo asociado: Ctrl+S lleva a 'Guardar como' (.imago por defecto),
        nunca se sobrescribe el PSD."""
        try:
            from models.psd_io import load_psd
        except ImportError:
            imago_warning(self, t("msg.psd.title"), t("msg.psd.missing_dep"))
            return
        completado, data = AccionesMenuArchivo._ejecutar_trabajo_io(
            self, lambda report, token: load_psd(
                file_path, report=report, token=token),
            t("status.io.loading"))
        if not completado:
            if getattr(self, "_io_cancelado", False):
                return
            mensaje = getattr(self, "_io_error_message", "") or ""
            if "psd_tools" in mensaje:
                imago_warning(self, t("msg.psd.title"), t("msg.psd.missing_dep"))
            else:
                imago_critical(self, t("msg.psd.title"), mensaje)
            return

        canvas = self.create_new_tab_canvas(data["width"], data["height"],
                                            os.path.basename(file_path))
        canvas.apply_project_data(data)
        canvas.project_path = None   # sin archivo asociado: no se pisa el PSD
        canvas.image_path = None
        if data.get("dpi"):
            canvas.dpi = data["dpi"]
        canvas.undo_stack.setClean()
        QTimer.singleShot(20, self.fit_canvas_to_screen)
        self._close_pristine_tabs(except_index=self.tabs.currentIndex())
        self._add_recent(file_path)

        if data.get("aplanado"):
            imago_warning(self, t("msg.psd.title"), t("msg.psd.flattened"))
        elif data.get("omitidas"):
            omitidas = data["omitidas"]
            nombres = "\n".join(f"•  {n}" for n in omitidas[:8])
            if len(omitidas) > 8:
                nombres += "\n•  …"
            imago_warning(self, t("msg.psd.title"),
                          t("msg.psd.omitted", n=len(omitidas), names=nombres))
        self.status_bar.showMessage(
            t("status.psd_imported", name=os.path.basename(file_path),
              n=len(data["layers"])), 5000)

    def _open_svg(self, file_path):
        """Importa un SVG RASTERIZADO: al ser vectorial no tiene tamano en
        pixeles, asi que un dialogo pregunta a cual rasterizarlo (por defecto
        el declarado por el propio SVG, con la proporcion enlazada). El lienzo
        queda SIN archivo asociado: Ctrl+S lleva a 'Guardar como' (Imago no
        escribe SVG, nunca se pisa el original)."""
        try:
            from PySide6.QtSvg import QSvgRenderer
        except ImportError:
            imago_warning(self, t("msg.open.title"),
                          t("msg.error.open_img", file_path=file_path))
            return
        def inspeccionar_svg(report, token):
            renderer = QSvgRenderer(file_path)
            report(100)
            return renderer.isValid(), renderer.defaultSize()

        completado, inspeccion = AccionesMenuArchivo._ejecutar_trabajo_io(
            self, inspeccionar_svg, t("status.io.loading"))
        if not completado:
            return
        valido, base = inspeccion
        if not valido:
            imago_warning(self, t("msg.open.title"),
                          t("msg.error.open_img", file_path=file_path))
            return
        w = base.width() if base.width() > 0 else 512
        h = base.height() if base.height() > 0 else 512

        from new_dialog import SvgSizeDialog
        dlg = SvgSizeDialog(self, w, h)
        if not dlg.exec():
            return
        w, h = dlg.get_values()

        def rasterizar(report, token):
            if token.cancelled:
                return QImage()
            render_worker = QSvgRenderer(file_path)
            image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            render_worker.render(painter)
            painter.end()
            report(100)
            return image if not token.cancelled else QImage()

        completado, image = AccionesMenuArchivo._ejecutar_trabajo_io(
            self, rasterizar, t("status.io.loading"))
        if not completado or image.isNull():
            return

        canvas = self.create_new_tab_canvas(w, h, os.path.basename(file_path), image)
        canvas.image_path = None
        canvas.project_path = None
        canvas.undo_stack.setClean()
        QTimer.singleShot(20, self.fit_canvas_to_screen)
        self._close_pristine_tabs(except_index=self.tabs.currentIndex())
        self._add_recent(file_path)

    def show_image_properties(self):
        """Imagen > Propiedades de imagen: visor de metadatos (dimensiones,
        PPP, archivo, EXIF con enlace al mapa e histograma). Solo lectura."""
        canvas = self.get_current_canvas()
        if not canvas:
            return
        from properties_dialog import ImagePropertiesDialog
        dlg = ImagePropertiesDialog(self, canvas)
        dlg.exec()

    MAX_FOTOGRAMAS = 240   # tope de capas al importar una animación

    def _open_animated(self, file_path):
        """Si el GIF/WebP tiene VARIOS fotogramas, ofrece abrirlos como capas
        (uno por capa, de abajo hacia arriba, guardando su duración en
        layer.frame_delay). Devuelve True si lo abrió así; False para que el
        que llama siga el flujo normal de imagen plana (un solo fotograma o
        respuesta negativa). El lienzo queda SIN archivo asociado (Ctrl+S no
        debe machacar la animación original con una imagen plana)."""
        from PySide6.QtGui import QImageReader
        from PySide6.QtWidgets import QMessageBox
        def contar_fotogramas(report, token):
            lector = QImageReader(file_path)
            lector.setAutoTransform(True)
            report(100)
            return lector.imageCount()

        completado, n = AccionesMenuArchivo._ejecutar_trabajo_io(
            self, contar_fotogramas, t("status.io.loading"))
        if not completado:
            return False
        if n <= 1:
            return False
        resp = imago_question(
            self, t("msg.anim.title"),
            t("msg.anim.as_layers", name=os.path.basename(file_path), n=n),
            QMessageBox.Yes | QMessageBox.No)
        if resp != QMessageBox.Yes:
            return False

        truncado = n > self.MAX_FOTOGRAMAS
        limite = min(n, self.MAX_FOTOGRAMAS)

        def decodificar(report, token):
            lector = QImageReader(file_path)
            lector.setAutoTransform(True)
            fotogramas = []
            for indice in range(limite):
                if token.cancelled:
                    return None
                imagen = lector.read()
                if imagen.isNull():
                    break
                fotogramas.append((
                    imagen.convertToFormat(QImage.Format_ARGB32),
                    max(0, int(lector.nextImageDelay()))))
                report(int(100 * (indice + 1) / limite))
            return fotogramas

        completado, fotogramas = AccionesMenuArchivo._ejecutar_trabajo_io(
            self, decodificar, t("status.io.loading"))
        if not completado or not fotogramas:
            return False

        from models.layer import Layer
        layers = []
        W, H = fotogramas[0][0].width(), fotogramas[0][0].height()
        for i, (img, delay) in enumerate(fotogramas):
            layer = Layer(W, H, name=t("layer.frame", i=i + 1))
            if img.width() == W and img.height() == H:
                layer.image = img
            else:
                # Fotograma de otro tamaño (raro): se pinta sobre el lienzo.
                painter = QPainter(layer.image)
                painter.drawImage(0, 0, img)
                painter.end()
            layer.frame_delay = delay
            layers.append(layer)
        if len(layers) < 2 or W is None:
            return False

        canvas = self.create_new_tab_canvas(W, H, os.path.basename(file_path))
        canvas.apply_project_data({
            "width": W, "height": H, "layers": layers,
            "active_layer_index": 0, "layer_counter": len(layers),
            "guides": [],
        })
        canvas.image_path = None
        canvas.project_path = None
        canvas.undo_stack.setClean()
        QTimer.singleShot(20, self.fit_canvas_to_screen)
        self._close_pristine_tabs(except_index=self.tabs.currentIndex())
        self._add_recent(file_path)
        msg = t("status.anim_opened", n=len(layers))
        if truncado:
            msg += " " + t("status.anim_truncated", max=self.MAX_FOTOGRAMAS)
        self.status_bar.showMessage(msg, 5000)
        return True

    def confirm_flatten_warning(self, canvas):
        """Avisa de que el archivo guardado fusionará las capas. Devuelve False si se cancela."""
        if len(canvas.layers) <= 1:
            return True  # Una sola capa: no hay nada que avisar
        from PySide6.QtWidgets import QMessageBox
        resp = imago_question(
            self, t("msg.save.title"),
            t("msg.save.flatten2"),
            QMessageBox.Ok | QMessageBox.Cancel
        )
        return resp == QMessageBox.Ok

    def save_file(self):
        """Ctrl+S: guarda en el archivo ASOCIADO (proyecto .imago o imagen). Si el
        lienzo aun no tiene archivo, pregunta donde (Guardar como).

        Devuelve ResultadoGuardado para que cerrar una pestaña o Imago nunca
        confunda una cancelación o un error con un guardado correcto.
        """
        canvas = self.get_current_canvas()
        if not canvas:
            return ResultadoGuardado.CANCELADO
        if getattr(canvas, 'project_path', None):
            return self._save_project(canvas, canvas.project_path)
        elif getattr(canvas, 'image_path', None):
            # Pregunta opciones (con tamaño aproximado).
            return self._save_image(canvas, canvas.image_path)
        return self.save_file_as()

    def save_file_as(self):
        """Ctrl+Shift+S: pregunta ubicacion y formato. El .imago guarda el proyecto
        con capas; cualquier otro formato aplana y guarda una imagen (y el lienzo
        queda asociado a ese archivo). Devuelve ResultadoGuardado."""
        canvas = self.get_current_canvas()
        if not canvas:
            return ResultadoGuardado.CANCELADO
        start = (getattr(canvas, 'image_path', None)
                 or getattr(canvas, 'project_path', None)
                 or self.last_opened_dir)
        # Tipo por defecto = formato ACTUAL del lienzo (si abriste un PNG, sale
        # PNG). Un lienzo nuevo sin archivo arranca en PNG para no forzar
        # .imago; pero si YA tiene varias capas (p. ej. un PSD importado),
        # se ofrece .imago para no perderlas sin querer.
        if getattr(canvas, 'image_path', None):
            cur_ext = os.path.splitext(canvas.image_path)[1].lower().lstrip('.')
        elif getattr(canvas, 'project_path', None):
            cur_ext = 'imago'
        elif len(canvas.layers) > 1:
            cur_ext = 'imago'
        else:
            cur_ext = 'png'
        full_filter = self._supported_save_filter()
        sel_filter = self._filter_for_ext(cur_ext, full_filter) or full_filter.split(';;')[0]
        file_path, selected = QFileDialog.getSaveFileName(
            self, t("dlg.save_as_title"), start, full_filter, sel_filter)
        if not file_path:
            return ResultadoGuardado.CANCELADO
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        if not ext:
            ext = self._ext_from_filter(selected)
            file_path += "." + ext
        if ext == "imago":
            return self._save_project(canvas, file_path)
        if not self.confirm_flatten_warning(canvas):
            return ResultadoGuardado.CANCELADO
        return self._save_image(canvas, file_path)   # quality None -> preguntar

    def print_file(self):
        """Ctrl+P: imprime el lienzo activo aplanado (capas visibles sobre
        blanco: el papel no tiene alfa). El dialogo es PROPIO (PrintDialog,
        un FramelessDialog con el tema de Imago; el QPrintDialog de Qt es
        NATIVO en Windows y no respetaria los colores): impresora o PDF,
        copias, orientacion, papel, color/grises, doble cara y escala, con
        vista previa de la pagina. La imagen sale a su tamano real segun los
        PPP del lienzo (reducida solo si no cabe) o ajustada a la pagina,
        siempre centrada."""
        canvas = self.get_current_canvas()
        if not canvas:
            return
        try:
            from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
        except ImportError:
            imago_critical(self, t("msg.error.title"), t("msg.error.print_support"))
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPageLayout
        from print_dialog import PrintDialog

        image = canvas.render_flat_image(background=Qt.white)
        dpi = float(getattr(canvas, 'dpi', 96.0)) or 96.0
        doc_name = self.tabs.tabText(self.tabs.currentIndex()) or "Imago"

        dlg = PrintDialog(image, dpi, self)
        if not dlg.exec():
            return
        cfg = dlg.get_settings()

        ruta_pdf = None
        reemplazo_pdf = None
        if cfg["pdf"]:
            base = os.path.splitext(doc_name)[0] + ".pdf"
            start = os.path.join(self.last_opened_dir or "", base)
            ruta_pdf, _sel = QFileDialog.getSaveFileName(
                self, t("dlg.print_pdf_save"), start, t("dlg.filter.pdf"))
            if not ruta_pdf:
                return
            if not ruta_pdf.lower().endswith(".pdf"):
                ruta_pdf += ".pdf"
            try:
                reemplazo_pdf = ReemplazoAtomico(ruta_pdf)
            except OSError:
                imago_critical(self, t("msg.error.title"), t("msg.error.print"))
                return
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(reemplazo_pdf.ruta)
        else:
            printer = QPrinter(QPrinterInfo.printerInfo(cfg["printer"]),
                               QPrinter.PrinterMode.HighResolution)
            printer.setCopyCount(cfg["copies"])
            printer.setDuplex(cfg["duplex"])
        printer.setDocName(doc_name)
        printer.setPageSize(cfg["page_size"])
        printer.setPageOrientation(QPageLayout.Orientation.Landscape if cfg["landscape"]
                                   else QPageLayout.Orientation.Portrait)
        printer.setColorMode(QPrinter.ColorMode.GrayScale if cfg["gray"]
                             else QPrinter.ColorMode.Color)
        if cfg["gray"]:
            # Grises garantizados en cualquier motor (el de PDF ignora ColorMode).
            image = image.convertToFormat(QImage.Format_Grayscale8)

        painter = QPainter(printer)
        if not painter.isActive():
            if reemplazo_pdf is not None:
                reemplazo_pdf.cancelar()
            imago_critical(self, t("msg.error.title"), t("msg.error.print"))
            return
        page = printer.pageRect(QPrinter.Unit.DevicePixel)
        # Tamano natural sobre el papel: pixeles / PPP del lienzo, pasados a
        # la resolucion de la impresora. 'Tamano real' solo reduce si no cabe;
        # 'Ajustar a la pagina' tambien amplia.
        w = image.width() * printer.resolution() / dpi
        h = image.height() * printer.resolution() / dpi
        ajuste = min(page.width() / w, page.height() / h)
        escala = ajuste if cfg["fit"] else min(1.0, ajuste)
        w *= escala
        h *= escala
        destino = QRectF((page.width() - w) / 2.0, (page.height() - h) / 2.0, w, h)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(destino, image, QRectF(image.rect()))
        painter.end()
        if ruta_pdf:
            # Cerrar los objetos Qt antes de sustituir el PDF en Windows.
            del painter
            del printer
            if not reemplazo_pdf.confirmar():
                reemplazo_pdf.cancelar()
                imago_critical(self, t("msg.error.title"), t("msg.error.print"))
                return
            reemplazo_pdf.cancelar()
            self.status_bar.showMessage(
                t("status.print_pdf", name=os.path.basename(ruta_pdf)), 4000)
        else:
            self.status_bar.showMessage(t("status.print_sent", name=doc_name), 4000)

    def export_pdf(self):
        """Archivo > Exportar PDF: crea un PDF cuya pagina mide EXACTAMENTE lo
        que la imagen (segun los PPP del lienzo), sin papel ni margenes. Es
        distinto de Imprimir > PDF, que centra la imagen en una hoja A4/Carta.
        Se aplana sobre blanco (como al imprimir: la pagina no tiene alfa)."""
        canvas = self.get_current_canvas()
        if not canvas:
            return
        from PySide6.QtCore import QMarginsF, QRectF, QSizeF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter

        doc_name = self.tabs.tabText(self.tabs.currentIndex()) or "Imago"
        base = os.path.splitext(doc_name)[0] + ".pdf"
        start = os.path.join(self.last_opened_dir or "", base)
        ruta_pdf, _sel = QFileDialog.getSaveFileName(
            self, t("dlg.print_pdf_save"), start, t("dlg.filter.pdf"))
        if not ruta_pdf:
            return
        if not ruta_pdf.lower().endswith(".pdf"):
            ruta_pdf += ".pdf"

        image = canvas.render_flat_image(background=Qt.white)
        dpi = float(getattr(canvas, 'dpi', 96.0)) or 96.0

        def _escribir_pdf(ruta_temporal, token):
            if token.cancelled:
                return False
            writer = QPdfWriter(ruta_temporal)
            writer.setTitle(os.path.splitext(doc_name)[0])
            writer.setResolution(int(round(dpi)))
            # Página en puntos tipográficos (1 pt = 1/72"): píxeles / PPP * 72.
            pagina = QPageSize(QSizeF(image.width() * 72.0 / dpi,
                                      image.height() * 72.0 / dpi),
                               QPageSize.Unit.Point,
                               matchPolicy=QPageSize.SizeMatchPolicy.ExactMatch)
            writer.setPageSize(pagina)
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))

            painter = QPainter(writer)
            if not painter.isActive():
                return False
            # Con la resolución igualada a los PPP, el rect de pintado coincide
            # con la imagen; se dibuja estirando por si el redondeo desvía 1 px.
            destino = QRectF(0, 0, writer.width(), writer.height())
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(destino, image, QRectF(image.rect()))
            painter.end()
            # QPdfWriter debe liberar su descriptor antes del os.replace en Windows.
            del painter
            del writer
            return not token.cancelled

        def trabajo(report, token):
            report(10)
            ok = escribir_atomico(
                ruta_pdf, lambda ruta: _escribir_pdf(ruta, token))
            report(100)
            return ok

        completado, ok = AccionesMenuArchivo._ejecutar_trabajo_io(
            self,
            trabajo, t("status.io.exporting"))
        if not completado:
            return
        if not ok:
            imago_critical(self, t("msg.error.title"), t("msg.error.print"))
            return
        self.status_bar.showMessage(
            t("status.print_pdf", name=os.path.basename(ruta_pdf)), 4000)

    def export_ora(self):
        """Archivo > Exportar OpenRaster: guarda las CAPAS en un .ora, el
        formato de intercambio que abren GIMP y Krita. Es un EXPORT: no asocia
        el lienzo al archivo (el proyecto nativo sigue siendo el .imago)."""
        canvas = self.get_current_canvas()
        if not canvas:
            return
        from models.project_io import crear_instantanea_ora, save_ora
        doc_name = self.tabs.tabText(self.tabs.currentIndex()) or "Imago"
        base = os.path.splitext(doc_name)[0] + ".ora"
        start = os.path.join(self.last_opened_dir or "", base)
        ruta, _sel = QFileDialog.getSaveFileName(
            self, t("dlg.ora_save"), start, t("dlg.filter.ora"))
        if not ruta:
            return
        if not ruta.lower().endswith(".ora"):
            ruta += ".ora"
        instantanea = crear_instantanea_ora(canvas)
        completado, ok = AccionesMenuArchivo._ejecutar_trabajo_io(
            self,
            lambda report, token: save_ora(
                instantanea, ruta, report=report, token=token),
            t("status.io.exporting"))
        if not completado:
            return
        if ok:
            self.last_opened_dir = os.path.dirname(ruta)
            self.settings.setValue("last_opened_dir", self.last_opened_dir)
            self.status_bar.showMessage(
                t("status.ora_saved", name=os.path.basename(ruta)), 4000)
        else:
            imago_critical(self, t("msg.error.title"), t("msg.error.ora"))

    def preview_animation(self):
        """Archivo > Previsualizar animación: reproduce las capas VISIBLES
        como fotogramas en un diálogo (el MISMO montaje que la exportación,
        vía frames_de_capas), sin tocar el lienzo ni el historial. Todo Qt:
        no necesita Pillow."""
        canvas = self.get_current_canvas()
        if not canvas:
            return
        from models.anim_io import frames_de_capas
        frames, delays = frames_de_capas(canvas)
        if len(frames) < 2:
            imago_warning(self, t("dlg.anim_preview"), t("msg.anim.need_layers"))
            return
        default_ms = next((d for d in delays if d), 100)
        from new_dialog import AnimPreviewDialog
        dlg = AnimPreviewDialog(self, frames, delays, default_ms=default_ms)
        dlg.exec()

    def export_animation(self):
        """Archivo > Exportar animación: las capas efectivamente visibles pasan
        a ser los fotogramas de un GIF o WebP animado (de abajo hacia arriba,
        cada una con su opacidad, máscara y efectos). Escribe Pillow (import
        perezoso en models/anim_io.py); si falta, se avisa y no se rompe nada."""
        canvas = self.get_current_canvas()
        if not canvas:
            return
        from models.anim_io import capas_de_animacion
        visibles = capas_de_animacion(canvas)
        if len(visibles) < 2:
            imago_warning(self, t("dlg.anim_export"), t("msg.anim.need_layers"))
            return
        delays = [getattr(l, "frame_delay", None) for l in visibles]
        default_ms = next((d for d in delays if d), 100)

        from new_dialog import AnimExportDialog
        dlg = AnimExportDialog(self, default_ms=default_ms,
                               has_original=any(delays))
        if not dlg.exec():
            return
        ms, usar_orig, bucle = dlg.get_values()

        doc_name = self.tabs.tabText(self.tabs.currentIndex()) or "Imago"
        base = os.path.splitext(doc_name)[0] + ".gif"
        start = os.path.join(self.last_opened_dir or "", base)
        filtro = t("dlg.filter.gif") + ";;" + t("dlg.filter.webp")
        ruta, sel = QFileDialog.getSaveFileName(
            self, t("dlg.anim_export"), start, filtro)
        if not ruta:
            return
        if not ruta.lower().endswith((".gif", ".webp")):
            ruta += ".webp" if "webp" in (sel or "").lower() else ".gif"

        from models.anim_io import frames_de_capas, save_animation_frames
        frames, delays_capturados = frames_de_capas(canvas)
        completado, resultado = AccionesMenuArchivo._ejecutar_trabajo_io(
            self,
            lambda report, token: save_animation_frames(
                frames, delays_capturados, ruta, ms, loop=bucle,
                use_original=usar_orig, report=report, token=token),
            t("status.io.exporting"))
        if not completado:
            return
        ok, err = resultado
        if ok:
            self.last_opened_dir = os.path.dirname(ruta)
            self.settings.setValue("last_opened_dir", self.last_opened_dir)
            self.status_bar.showMessage(
                t("status.anim_saved", name=os.path.basename(ruta)), 4000)
        else:
            msg = t("msg.anim.pillow") if err == "pillow" else t("msg.error.anim")
            imago_critical(self, t("msg.error.title"), msg)

    def _save_project(self, canvas, file_path):
        """Escribe el .imago, actualiza el estado y devuelve ResultadoGuardado."""
        from models.project_io import crear_instantanea_proyecto, save_project

        self.last_opened_dir = os.path.dirname(file_path)
        self.settings.setValue("last_opened_dir", self.last_opened_dir)

        revision = getattr(canvas, "revision_autoguardado", None)
        instantanea = crear_instantanea_proyecto(canvas)
        completado, ok = AccionesMenuArchivo._ejecutar_trabajo_io(
            self,
            lambda report, token: save_project(
                instantanea, file_path, report=report, token=token),
            t("status.io.saving"))
        if not completado:
            return (ResultadoGuardado.CANCELADO if getattr(self, "_io_cancelado", False)
                    else ResultadoGuardado.ERROR)
        if ok:
            canvas.project_path = file_path  # asociamos el .imago al lienzo
            canvas.image_path = None         # ya no esta ligado a una imagen plana
            # Si el usuario editó durante la compresión, el archivo es válido
            # pero corresponde a la instantánea: el estado nuevo sigue pendiente.
            if getattr(canvas, "revision_autoguardado", None) == revision:
                canvas.undo_stack.setClean()
                canvas.recovered_dirty = False
            indice = AccionesMenuArchivo._tab_index_for_canvas(self, canvas)
            if indice >= 0:
                self.tabs.setTabText(indice, os.path.basename(file_path))
            self._update_window_title()
            self._add_recent(file_path)
            self.status_bar.showMessage(t("status.saved_proj", name=os.path.basename(file_path)), 4000)
            return ResultadoGuardado.EXITO
        imago_critical(self, t("msg.error.title"), t("msg.error.save_proj"))
        return ResultadoGuardado.ERROR

    def _save_image(self, canvas, file_path, settings=None):
        """Aplana las capas visibles y guarda una imagen. settings None -> se
        preguntan las opciones (calidad/compresion, profundidad, tamano aprox.);
        un dict -> se usa tal cual. Deja el lienzo asociado a la imagen (Opcion A)
        y devuelve ResultadoGuardado."""
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtGui import QImageWriter, QImage
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        # Formatos con canal alfa: aplanamos sobre fondo TRANSPARENTE para no perder
        # la transparencia. Los que no lo soportan (JPG, BMP...) sobre blanco.
        _alpha_fmt = {"png", "webp", "tif", "tiff", "ico", "icns", "gif", "tga", "xpm", "cur"}
        _bg = _Qt.transparent if ext in _alpha_fmt else _Qt.white
        final_image = canvas.render_flat_image(background=_bg)
        if settings is None:
            default = getattr(canvas, 'image_quality', -1)
            if default is None or default < 0:
                default = self._default_quality(ext)
            settings, ok = self._ask_quality(ext, final_image, default)
            if not ok:
                return ResultadoGuardado.CANCELADO
        self.last_opened_dir = os.path.dirname(file_path)
        self.settings.setValue("last_opened_dir", self.last_opened_dir)
        img = final_image
        q = settings.get("quality", -1)
        dpi_v = float(getattr(canvas, 'dpi', 96.0))
        # Resolución de impresión (PPP) como metadato del archivo (pHYs en PNG,
        # densidad en JPEG...). dpm = puntos por metro = PPP / 0.0254.
        dpm = int(round(dpi_v / 0.0254))
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)
        conservar_exif = self.settings.value("save/keep_exif", True, type=bool)
        conservar_gps = self.settings.value("save/keep_gps", True, type=bool)
        source_exif = getattr(canvas, 'source_exif', None)
        revision = getattr(canvas, "revision_autoguardado", None)

        def trabajo(report, token):
            imagen = QImage(img)
            datos_png8 = None
            if settings.get("indexed8"):
                # La cuantización Pillow es una de las fases pesadas y se hace
                # íntegramente aquí, nunca en el hilo GUI.
                from utilidades import png8_bytes
                nivel = 6 if q is None or q < 0 else round(q * 9 / 100)
                datos_png8 = png8_bytes(
                    imagen, settings.get("colors", 256),
                    settings.get("dither", False), nivel, dpi=(dpi_v, dpi_v))
                if datos_png8 is None:
                    imagen = imagen.convertToFormat(QImage.Format_Indexed8)
            if token.cancelled:
                return False
            report(35)

            def _escribir_imagen(ruta_temporal):
                if token.cancelled:
                    return False
                if datos_png8 is not None:
                    with open(ruta_temporal, "wb") as fh:
                        fh.write(datos_png8)
                    escrito_temporal = True
                else:
                    writer = QImageWriter(ruta_temporal)
                    if q is not None and q >= 0:
                        writer.setQuality(q)
                    if settings.get("optimized") and hasattr(writer, "setOptimizedWrite"):
                        writer.setOptimizedWrite(True)
                    if settings.get("progressive") and hasattr(writer, "setProgressiveScanWrite"):
                        writer.setProgressiveScanWrite(True)
                    escrito_temporal = writer.write(imagen)

                if (escrito_temporal and ext in ("jpg", "jpeg")
                        and conservar_exif and not token.cancelled):
                    from exif_utils import incrustar_exif_jpeg
                    incrustar_exif_jpeg(
                        ruta_temporal, source_exif, incluir_gps=conservar_gps)
                return escrito_temporal and not token.cancelled

            ok = escribir_atomico(file_path, _escribir_imagen)
            report(100)
            return ok

        completado, escrito = AccionesMenuArchivo._ejecutar_trabajo_io(
            self,
            trabajo, t("status.io.saving"))
        if not completado:
            return (ResultadoGuardado.CANCELADO if getattr(self, "_io_cancelado", False)
                    else ResultadoGuardado.ERROR)
        if escrito:
            canvas.image_path = file_path
            canvas.project_path = None
            canvas.image_quality = settings.get("quality", -1)
            if getattr(canvas, "revision_autoguardado", None) == revision:
                canvas.undo_stack.setClean()
                canvas.recovered_dirty = False
            indice = AccionesMenuArchivo._tab_index_for_canvas(self, canvas)
            if indice >= 0:
                self.tabs.setTabText(indice, os.path.basename(file_path))
            self._update_window_title()
            self._add_recent(file_path)
            self.status_bar.showMessage(t("status.saved_img", name=os.path.basename(file_path)), 4000)
            return ResultadoGuardado.EXITO
        imago_critical(self, t("msg.error.title"), t("msg.error.save_img"))
        return ResultadoGuardado.ERROR

    def _default_quality(self, ext):
        """Calidad/compresion por defecto de cada formato (para Ctrl+S y como
        valor inicial del dialogo). -1 = sin parametro."""
        ext = ext.lower()
        if ext in ("jpg", "jpeg", "webp"):
            return 92
        if ext == "png":
            return 70
        return -1

    def _ask_quality(self, ext, image, default):
        """Devuelve (settings, ok). Muestra el dialogo de opciones solo en formatos
        que lo admiten (JPEG/WebP/PNG); en el resto devuelve ({'quality': -1}, True)
        sin molestar. settings es un dict: quality + extras del formato."""
        ext = ext.lower()
        if ext not in ("jpg", "jpeg", "webp", "png"):
            return {"quality": -1}, True
        from new_dialog import QualityDialog
        dlg = QualityDialog(ext, image, default, self)
        if dlg.exec():
            s = {"quality": dlg.value()}
            s.update(dlg.options())
            return s, True
        return None, False

    def _filter_for_ext(self, ext, full_filter):
        """Devuelve la entrada del filtro (p.ej. 'PNG (*.png)') correspondiente
        a una extension, para preseleccionarla en 'Guardar como'."""
        ext = ext.lower()
        needle = f"*.{ext}"
        for part in full_filter.split(";;"):
            lp, rp = part.find("("), part.rfind(")")
            if lp == -1 or rp == -1:
                continue
            pats = [q.lower() for q in part[lp + 1:rp].split()]
            if needle in pats:
                return part
        return None

    def _ext_from_filter(self, flt):
        import re
        m = re.search(r"\*\.(\w+)", flt or "")
        return m.group(1).lower() if m else "png"

    def _supported_open_filter(self):
        """Filtro de Abrir: .imago + todos los formatos que Qt sabe LEER (más
        AVIF/HEIC/JXL si están sus plugins opcionales de Pillow)."""
        from PySide6.QtGui import QImageReader
        exts = {bytes(b).decode().lower() for b in QImageReader.supportedImageFormats()}
        import importlib.util as _ilu
        if _ilu.find_spec("pillow_heif") is not None:
            exts |= {"avif", "heic", "heif"}
        if _ilu.find_spec("pillow_jxl") is not None:
            exts.add("jxl")
        exts = sorted(exts)
        img = " ".join(f"*.{e}" for e in exts)
        allp = "*.imago *.psd *.psb " + img
        return (f"{t('dlg.filter.all_supported')} ({allp});;"
                f"{t('dlg.filter.imago')} (*.imago);;"
                f"{t('dlg.filter.psd')} (*.psd *.psb);;"
                f"{t('dlg.filter.images')} ({img});;"
                f"{t('dlg.filter.all_files')} (*.*)")

    def _supported_save_filter(self):
        """Filtro de Guardar como: .imago primero + todos los formatos que Qt sabe
        ESCRIBIR, agrupando equivalentes (jpg/jpeg, tif/tiff)."""
        from PySide6.QtGui import QImageWriter
        exts = {bytes(b).decode().lower() for b in QImageWriter.supportedImageFormats()}
        parts = [f"{t('dlg.filter.imago')} (*.imago)"]
        groups = [("JPEG", ["jpg", "jpeg"]), ("PNG", ["png"]), ("BMP", ["bmp"]),
                  ("GIF", ["gif"]), ("WebP", ["webp"]), ("TIFF", ["tif", "tiff"]),
                  (t("fmt.win_icon"), ["ico"]), ("Targa", ["tga"]), ("ICNS", ["icns"]),
                  ("WBMP", ["wbmp"]), ("PPM", ["ppm"]), ("PGM", ["pgm"]),
                  ("PBM", ["pbm"]), ("XBM", ["xbm"]), ("XPM", ["xpm"])]
        used = set()
        for name, es in groups:
            present = [e for e in es if e in exts]
            if present:
                pats = " ".join(f"*.{e}" for e in present)
                parts.append(f"{name} ({pats})")
                used.update(present)
        for e in sorted(exts - used):
            parts.append(f"{e.upper()} (*.{e})")
        return ";;".join(parts)

    # -------------------------------------------------- Archivos recientes
    def _load_recent(self):
        val = self.settings.value("recent_files", [])
        if isinstance(val, str):
            val = [val] if val else []
        return list(val) if val else []

    def _add_recent(self, path):
        path = os.path.abspath(path)
        recent = [p for p in self._load_recent()
                  if os.path.normcase(p) != os.path.normcase(path)]
        recent.insert(0, path)
        recent = recent[:10]
        self.settings.setValue("recent_files", recent)
        # NO se reconstruye aquí: el submenú se rebuild-ea en su aboutToShow.
        # _add_recent se llama desde open_path, que suele venir DENTRO del clic de
        # un widget que se destruye en el acto (miniatura de la pantalla de inicio,
        # que on_tab_changed desmonta al abrir la pestaña); recrear ahí los
        # QWidgetAction/miniaturas del menú PETA (access violation en shiboken,
        # PySide6 6.11/py3.14). Al reconstruir solo al abrir el menú se evita.

    def _remove_recent(self, path):
        path = os.path.abspath(path)
        recent = [p for p in self._load_recent()
                  if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("recent_files", recent)
        # Se refleja al reabrir el menú (aboutToShow); ver _rebuild_recent_menu.

    def _clear_recent(self):
        self.settings.setValue("recent_files", [])
        # El menú se refleja al reabrirse (aboutToShow); ver _rebuild_recent_menu.
        # La pantalla de bienvenida NO se entera sola, así que si está visible la
        # reconstruimos para que sus miniaturas de recientes desaparezcan ya.
        self._refresh_welcome_recents()

    def _refresh_welcome_recents(self):
        """Reconstruye la pantalla de bienvenida si está visible (sin lienzos
        abiertos), para reflejar cambios en la lista de recientes (p. ej. al
        borrarla). Con algún lienzo abierto no hace nada."""
        if self.tabs.count() != 0:
            return
        for i in reversed(range(self.content_layout.count())):
            w = self.content_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.content_layout.addWidget(self._build_welcome_widget())
        self._sync_ruler_overlay_geometry()

    def _thumbnail_pixmap(self, path, size=44):
        """Miniatura cuadrada de 'size' px para los recientes (menu o pantalla de
        inicio). .imago -> icono del proyecto; imagen -> version reducida del archivo."""
        from PySide6.QtCore import Qt
        if path.lower().endswith(".imago"):
            if QFile.exists(":/icons/imago.png"):
                return QPixmap(":/icons/imago.png").scaled(
                    size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            return None
        img = cargar_imagen_orientada(path)
        if img.isNull():
            return None
        return QPixmap.fromImage(img).scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _rebuild_recent_menu(self):
        """Reconstruye el submenu 'Abrir recientes' con miniatura + nombre. Lo
        dispara el aboutToShow del menú (pila limpia, aún no visible): así nunca
        se recrean sus QWidgetAction anidados en otro handler ni con el menú a la
        vista (lo que provocaba access violations en shiboken)."""
        from PySide6.QtWidgets import QWidgetAction
        menu = getattr(self, "recent_menu", None)
        if menu is None:
            return
        # NO usar menu.clear(): destruye SÍNCRONAMENTE las QWidgetAction y sus
        # widgets de miniatura, y con PySide6 6.11/py3.14 eso PETA (SIGSEGV en
        # shiboken releaseWrapper) cuando la reconstrucción ocurre dentro de otro
        # handler (clic en una miniatura de la pantalla de inicio, soltar un
        # archivo arrastrado...): open_path → _add_recent → aquí. Se retiran del
        # menú y su destrucción se DIFIERE al bucle de eventos.
        for act in list(menu.actions()):
            menu.removeAction(act)
            act.deleteLater()
        stored = self._load_recent()
        recent = [p for p in stored if os.path.exists(p)]
        if len(recent) != len(stored):
            self.settings.setValue("recent_files", recent)  # purga los que ya no existen
        # Referencias fuertes a las acciones vivas: sin ellas, el recolector puede
        # soltar los wrappers Python y la posterior destrucción C++ se confunde.
        self._recent_actions = []
        if not recent:
            empty = QAction(t("menu.recent.empty"), self)
            empty.setEnabled(False)
            menu.addAction(empty)
            self._recent_actions.append(empty)
            return
        for path in recent:
            wa = QWidgetAction(menu)
            wa.setDefaultWidget(_RecentItem(path, self._thumbnail_pixmap(path),
                                            lambda p=path: self._open_recent(p)))
            menu.addAction(wa)
            self._recent_actions.append(wa)
        clear_act = QAction(t("menu.recent.clear"), self)
        clear_act.triggered.connect(self._clear_recent)
        menu.addSeparator()
        menu.addAction(clear_act)
        self._recent_actions.append(clear_act)

    def _open_recent(self, path):
        # Los recientes son QWidgetAction con widget propio: el widget captura el
        # clic, así que Qt NO cierra el menú por su cuenta y cerrar solo el
        # submenú deja abierto el menú 'Archivo' padre. Cerramos TODA la cadena de
        # menús emergentes visibles antes de abrir.
        from PySide6.QtWidgets import QApplication, QMenu
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMenu) and w.isVisible():
                w.hide()
        self.open_path(path)

    # ------------------------------------------------ Procesamiento por lotes
    def batch_process(self):
        """Archivo ▸ Procesar por lotes...: redimensionar/convertir/marca de
        agua sobre una carpeta entera (batch_dialog.py). El runner se crea una
        vez y vive en MainWindow: sobrevive al diálogo, de modo que cancelar
        cierra la GUI al momento sin dejar señales hacia objetos destruidos.
        Es un runner PROPIO (no el de IA): un lote nunca encola detrás de una
        inferencia ni al revés."""
        from batch_dialog import BatchDialog
        if getattr(self, "_batch_runner", None) is None:
            from ai.runner import InferenceRunner
            self._batch_runner = InferenceRunner(self)
        dlg = BatchDialog(self, self._batch_runner)
        dlg.exec()


