# widgets/tab_thumbnails.py
"""Barra de miniaturas de pestañas (extraída de main.py TAL CUAL).

_ThumbButton (miniatura clicable con 'x' de cerrar), _ThumbStrip (tira
interior) y TabThumbnailBar (la barra completa con flechas de desplazamiento),
que MainWindow crea en __init__. Las vistas previas se invalidan por cambios
visuales del documento; no existe sondeo periódico en reposo."""
from PySide6.QtCore import Qt, QSize, QFile, QTimer
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QPushButton,
                               QSizePolicy)

from utilidades import _canvas_thumb_pixmap
import theme

class _ThumbButton(QWidget):
    """Miniatura de un documento: imagen de ancho fijo, borde azul si está activa
    y una 'x' de cerrar que solo aparece al pasar el ratón por encima."""
    W = 88
    H = 50

    def __init__(self, bar, index, canvas=None):
        super().__init__()
        self.bar = bar
        self.index = index
        self.canvas = canvas
        self.active = False
        self._pixmap = None
        self._preview_pixmap = None
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.close_btn = QPushButton("\u2715", self)
        self.close_btn.setFixedSize(16, 16)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        # X compacta de peligro; sus colores salen de la fuente unica del tema.
        self.close_btn.setStyleSheet(theme.thumbnail_close_button_qss())
        self.close_btn.move(self.W - 19, 2)
        self.close_btn.hide()
        self.close_btn.clicked.connect(self._on_close)

    def set_pixmap(self, pm):
        self._pixmap = pm
        self.update()

    def set_active(self, active):
        if active != self.active:
            self.active = active
            self.update()

    def enterEvent(self, e):
        self.close_btn.show()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.close_btn.hide()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.bar.main_window.tabs.setCurrentIndex(self.index)
        super().mousePressEvent(e)

    def _on_close(self):
        self.bar.main_window.close_tab(self.index)

    def paintEvent(self, e):
        from PySide6.QtGui import QPainter, QPen, QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.BG_WINDOW))
        if self._pixmap is not None and not self._pixmap.isNull():
            pm = self._pixmap
            x = (self.width() - pm.width()) // 2
            y = (self.height() - pm.height()) // 2
            p.drawPixmap(x, y, pm)
        if self.active:
            pen = QPen(QColor(theme.ACCENT)); pen.setWidth(2)
        else:
            pen = QPen(QColor(theme.BORDER_BUTTON)); pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))
        p.end()


class _ThumbStrip(QWidget):
    """Contenedor de las miniaturas que NUNCA impone ancho mínimo (su anchura la
    manda la ventana). Evita que la tira fuerce el ancho de la ventana."""
    def minimumSizeHint(self):
        return QSize(0, 0)


class TabThumbnailBar(QWidget):
    """Tira de miniaturas por páginas: muestra solo las que caben ENTERAS en el
    ancho disponible (nunca recortadas) y las flechas pasan página, manteniendo
    la vista siempre llena (la última página enseña las últimas que caben, no una
    sola). No impone ancho mínimo. self.tabs sigue siendo el almacén de datos."""

    STRIDE = _ThumbButton.W + 6      # ancho de miniatura + separación
    REFRESH_MS = 250                 # máximo 4 composiciones/s durante un trazo
    PREVIEW_W = 150                  # una sola caché sirve también al tooltip
    PREVIEW_H = 110

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setFixedHeight(58)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._buttons = []
        self._start = 0
        self._dirty_canvases = set()
        self._canvas_slots = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 0, 6, 0)
        root.setSpacing(4)

        self.btn_left = QPushButton()
        # Si existe icons/left_arrow.png se usa esa imagen; si no, el s\u00edmbolo \u2039.
        if QFile.exists(":/icons/left_arrow.png"):
            self.btn_left.setIcon(theme.icono(":/icons/left_arrow.png"))
            self.btn_left.setIconSize(QSize(14, 14))
        else:
            self.btn_left.setText("\u2039")
        self.btn_left.setCursor(Qt.PointingHandCursor)
        self.btn_left.setFixedSize(20, 20)
        self.btn_left.setStyleSheet(self._arrow_style())
        self.btn_left.clicked.connect(lambda: self._shift(-1))
        self.btn_left.hide()
        root.addWidget(self.btn_left)

        self._strip = _ThumbStrip()
        self._strip.setMinimumWidth(0)
        self._strip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 0, 0, 0)
        self._strip_layout.setSpacing(6)
        self._strip_layout.addStretch(1)
        root.addWidget(self._strip, stretch=1)

        self.btn_right = QPushButton()
        # Si existe icons/right_arrow.png se usa esa imagen; si no, el s\u00edmbolo \u203a.
        if QFile.exists(":/icons/right_arrow.png"):
            self.btn_right.setIcon(theme.icono(":/icons/right_arrow.png"))
            self.btn_right.setIconSize(QSize(14, 14))
        else:
            self.btn_right.setText("\u203a")
        self.btn_right.setCursor(Qt.PointingHandCursor)
        self.btn_right.setFixedSize(20, 20)
        self.btn_right.setStyleSheet(self._arrow_style())
        self.btn_right.clicked.connect(lambda: self._shift(1))
        self.btn_right.hide()
        root.addWidget(self.btn_right)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(self.REFRESH_MS)
        self._refresh_timer.timeout.connect(self._refresh_dirty_thumbs)

    def _arrow_style(self):
        return theme.arrow_button_qss()

    def _make_preview(self, canvas):
        try:
            # NO usar canvas.grab(): a zoom alto el widget puede medir
            # decenas de miles de px (p.ej. 114000x76080 ≈ 34 GB) y bloquear la
            # app. Componemos la imagen a TAMAÑO BASE y la reducimos a miniatura.
            return _canvas_thumb_pixmap(
                canvas, self.PREVIEW_W, self.PREVIEW_H)
        except Exception:
            return None

    def _connect_canvas(self, canvas):
        clave = id(canvas)
        if clave in self._canvas_slots:
            return
        signal = getattr(canvas, "contenido_visual_cambiado", None)
        if signal is None:
            return
        slot = lambda c=canvas: self.invalidate_canvas(c)
        signal.connect(slot)
        self._canvas_slots[clave] = (canvas, slot)

    def _disconnect_missing_canvases(self, canvases):
        presentes = {id(canvas) for canvas in canvases if canvas is not None}
        for clave, (canvas, slot) in list(self._canvas_slots.items()):
            if clave in presentes:
                continue
            try:
                canvas.contenido_visual_cambiado.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
            self._dirty_canvases.discard(canvas)
            del self._canvas_slots[clave]

    def _button_for_canvas(self, canvas):
        return next((b for b in self._buttons if b.canvas is canvas), None)

    def _refresh_canvas_thumb(self, canvas, button=None):
        button = button or self._button_for_canvas(canvas)
        if button is None:
            return False
        preview = self._make_preview(canvas)
        if preview is None or preview.isNull():
            return False
        button._preview_pixmap = preview
        button.set_pixmap(preview.scaled(
            _ThumbButton.W - 10, _ThumbButton.H - 10,
            Qt.KeepAspectRatio, Qt.SmoothTransformation))
        confirmar = getattr(canvas, "confirmar_miniatura_actualizada", None)
        if callable(confirmar):
            confirmar()
        actualizar_tooltip = getattr(
            self.main_window, "update_tab_tooltip", None)
        if callable(actualizar_tooltip):
            actualizar_tooltip(button.index, preview)
        return True

    def preview_for_canvas(self, canvas):
        button = self._button_for_canvas(canvas)
        return button._preview_pixmap if button is not None else None

    def invalidate_canvas(self, canvas):
        """Marca una vista previa y agrupa ráfagas sin temporizador periódico."""
        if self._button_for_canvas(canvas) is None:
            return
        self._dirty_canvases.add(canvas)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _capacity(self):
        # Cuántas miniaturas ENTERAS caben (reservando hueco para las flechas).
        avail = self.width() - 10 - 48
        if avail < self.STRIDE:
            return 1
        return max(1, (avail + 6) // self.STRIDE)

    def rebuild(self):
        tabs = self.main_window.tabs
        canvases = []
        for i in range(tabs.count()):
            marker = tabs.widget(i)
            canvases.append(getattr(marker, "canvas", None))

        anteriores = {id(b.canvas): b for b in self._buttons
                      if b.canvas is not None}
        nuevos = []
        for i, canvas in enumerate(canvases):
            btn = anteriores.pop(id(canvas), None) if canvas is not None else None
            if btn is None:
                btn = _ThumbButton(self, i, canvas)
                if canvas is not None:
                    self._connect_canvas(canvas)
                    self._refresh_canvas_thumb(canvas, btn)
            else:
                btn.index = i
            nuevos.append(btn)

        for btn in anteriores.values():
            self._strip_layout.removeWidget(btn)
            btn.setParent(None)
            btn.deleteLater()
        for btn in self._buttons:
            self._strip_layout.removeWidget(btn)
        self._buttons = nuevos
        for i, btn in enumerate(self._buttons):
            self._strip_layout.insertWidget(i, btn)
        self._disconnect_missing_canvases(canvases)
        self._update_active()
        QTimer.singleShot(0, self._relayout_active)

    def _update_active(self):
        cur = self.main_window.tabs.currentIndex()
        for i, b in enumerate(self._buttons):
            b.set_active(i == cur)

    def _refresh_dirty_thumbs(self):
        pendientes = tuple(self._dirty_canvases)
        self._dirty_canvases.clear()
        for canvas in pendientes:
            self._refresh_canvas_thumb(canvas)

    def _relayout(self, ensure_active=False):
        n = len(self._buttons)
        cap = self._capacity()
        max_start = max(0, n - cap)
        if ensure_active:
            cur = self.main_window.tabs.currentIndex()
            if 0 <= cur < n:
                if cur < self._start:
                    self._start = cur
                elif cur >= self._start + cap:
                    self._start = cur - cap + 1
        self._start = max(0, min(self._start, max_start))
        for i, b in enumerate(self._buttons):
            b.setVisible(self._start <= i < self._start + cap)
        overflow = n > cap
        self.btn_left.setVisible(overflow)
        self.btn_right.setVisible(overflow)
        if overflow:
            self.btn_left.setEnabled(self._start > 0)
            self.btn_right.setEnabled(self._start + cap < n)

    def _relayout_active(self):
        self._relayout(ensure_active=True)

    def _shift(self, direction):
        cap = self._capacity()
        self._start += direction * cap
        self._relayout(ensure_active=False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._relayout_active)


