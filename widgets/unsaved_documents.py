"""Diálogo conjunto para cerrar Imago con documentos sin guardar."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from i18n import t
import theme
from utilidades import _canvas_thumb_pixmap
from widgets.custom_titlebar import FramelessDialog


DECISION_GUARDAR = "guardar"
DECISION_DESCARTAR = "descartar"
DECISION_VOLVER = "volver"


class _FilaDocumentoPendiente(QFrame):
    """Resumen visual de un documento que impediría un cierre limpio."""

    ANCHO_MINIATURA = 150
    ALTO_MINIATURA = 110

    def __init__(self, documento, parent=None):
        super().__init__(parent)
        self.documento = documento
        self.setObjectName("UnsavedDocumentRow")
        self.setStyleSheet(
            "QFrame#UnsavedDocumentRow {"
            f" background-color: {theme.BG_DARK};"
            f" border: 1px solid {theme.BORDER}; border-radius: 5px;"
            "}"
        )

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(10, 10, 10, 10)
        raiz.setSpacing(12)

        self.miniatura = QLabel()
        self.miniatura.setObjectName("UnsavedDocumentThumbnail")
        self.miniatura.setFixedSize(self.ANCHO_MINIATURA, self.ALTO_MINIATURA)
        self.miniatura.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.miniatura.setStyleSheet(
            f"background-color: {theme.BG_WINDOW}; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER_INPUT}; border-radius: 3px;"
        )
        self._cargar_miniatura()
        raiz.addWidget(self.miniatura)

        datos = QVBoxLayout()
        datos.setSpacing(5)

        titulo = QLabel(documento.get("title") or t(
            "msg.recovered_default", default="Documento sin título"))
        titulo.setWordWrap(True)
        titulo.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
        )
        datos.addWidget(titulo)

        estado = QLabel(t("close.unsaved.status"))
        estado.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 11px; font-weight: 600;"
        )
        datos.addWidget(estado)

        ruta = documento.get("path")
        texto_ruta = ruta or t("close.unsaved.no_path")
        self.ruta = QLabel(t("close.unsaved.path", path=texto_ruta))
        self.ruta.setWordWrap(True)
        self.ruta.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ruta.setToolTip(ruta or texto_ruta)
        self.ruta.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px;"
        )
        datos.addWidget(self.ruta, 1)
        raiz.addLayout(datos, 1)

    def _cargar_miniatura(self):
        canvas = self.documento.get("canvas")
        preview = self.documento.get("preview")
        pixmap = QPixmap(preview) if isinstance(preview, QPixmap) else None
        if pixmap is None or pixmap.isNull():
            try:
                # Respaldo para lienzos que todavía no hayan entrado en la
                # barra de miniaturas. La vía normal reutiliza su caché reducida
                # y no recompone una imagen grande durante el cierre.
                pixmap = _canvas_thumb_pixmap(
                    canvas, self.ANCHO_MINIATURA - 4,
                    self.ALTO_MINIATURA - 4) if canvas is not None else None
            except Exception:
                pixmap = None
        if pixmap is None or pixmap.isNull():
            self.miniatura.setText(t(
                "recovery.no_preview", default="Vista previa no disponible"))
            self.miniatura.setWordWrap(True)
            return
        self.miniatura.setPixmap(pixmap.scaled(
            self.ANCHO_MINIATURA - 4, self.ALTO_MINIATURA - 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))


class UnsavedDocumentsDialog(FramelessDialog):
    """Presenta todos los documentos pendientes y devuelve una decisión global."""

    def __init__(self, documentos, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("msg.unsaved.title"))
        self.setModal(True)
        self._decision = DECISION_VOLVER
        self._filas = []

        self.body_layout.setContentsMargins(14, 12, 14, 14)
        self.body_layout.setSpacing(10)
        self._body.setMinimumWidth(760)

        clave_intro = (
            "close.unsaved.intro.one" if len(documentos) == 1
            else "close.unsaved.intro.many")
        introduccion = QLabel(t(clave_intro, n=len(documentos)))
        introduccion.setWordWrap(True)
        introduccion.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px;"
        )
        self.body_layout.addWidget(introduccion)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget {"
            f" background: {theme.BG_WINDOW};"
            "}"
        )
        contenido = QWidget()
        lista = QVBoxLayout(contenido)
        lista.setContentsMargins(0, 0, 0, 0)
        lista.setSpacing(8)
        for documento in documentos:
            fila = _FilaDocumentoPendiente(documento, contenido)
            self._filas.append(fila)
            lista.addWidget(fila)
        lista.addStretch(1)
        scroll.setWidget(contenido)
        scroll.setMinimumHeight(min(500, max(138, len(documentos) * 138)))
        self.body_layout.addWidget(scroll, 1)

        nota = QLabel(t("close.unsaved.save_note"))
        nota.setWordWrap(True)
        nota.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px;"
        )
        self.body_layout.addWidget(nota)

        pie = QHBoxLayout()
        volver = self._crear_boton(
            "UnsavedReturnButton", t("close.unsaved.return"),
            DECISION_VOLVER)
        pie.addWidget(volver)
        pie.addStretch(1)
        descartar = self._crear_boton(
            "UnsavedDiscardButton", t("msg.discard"),
            DECISION_DESCARTAR)
        pie.addWidget(descartar)
        guardar = self._crear_boton(
            "UnsavedSaveButton", t("msg.save"), DECISION_GUARDAR)
        guardar.setDefault(True)
        pie.addWidget(guardar)
        self.body_layout.addLayout(pie)

    def _crear_boton(self, nombre, texto, decision):
        boton = QPushButton(texto)
        boton.setObjectName(nombre)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setStyleSheet(theme.dialog_button_qss(
            f"QPushButton#{nombre}"))
        boton.clicked.connect(
            lambda _checked=False, valor=decision: self._elegir(valor))
        return boton

    def _elegir(self, decision):
        self._decision = decision
        if decision == DECISION_VOLVER:
            self.reject()
        else:
            self.accept()

    def decision(self):
        return self._decision


def preguntar_cierre_documentos(parent, documentos):
    """Abre el diálogo y trata X/Escape como «Volver a Imago»."""
    dialogo = UnsavedDocumentsDialog(documentos, parent)
    dialogo.exec()
    return dialogo.decision()
