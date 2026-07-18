"""Gestor de copias de recuperación mostrado al iniciar Imago."""

import os

from PySide6.QtCore import QDateTime, QLocale, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from i18n import t
import theme
from widgets.custom_titlebar import FramelessDialog


class _FilaRecuperacion(QFrame):
    """Una copia y su decisión exclusiva: abrir, conservar o descartar."""

    ANCHO_MINIATURA = 150
    ALTO_MINIATURA = 110

    def __init__(self, entrada, parent=None):
        super().__init__(parent)
        self.entrada = entrada
        self.setObjectName("RecoveryRow")
        self.setStyleSheet(
            "QFrame#RecoveryRow {"
            f" background-color: {theme.BG_DARK};"
            f" border: 1px solid {theme.BORDER}; border-radius: 5px;"
            "}"
        )

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(10, 10, 10, 10)
        raiz.setSpacing(12)

        self.miniatura = QLabel()
        self.miniatura.setObjectName("RecoveryThumbnail")
        self.miniatura.setFixedSize(self.ANCHO_MINIATURA, self.ALTO_MINIATURA)
        self.miniatura.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.miniatura.setStyleSheet(
            f"background-color: {theme.BG_WINDOW}; color: {theme.TEXT_MUTED};"
            f" border: 1px solid {theme.BORDER_INPUT}; border-radius: 3px;"
        )
        self._cargar_miniatura()
        raiz.addWidget(self.miniatura)

        datos = QVBoxLayout()
        datos.setSpacing(4)
        titulo = QLabel(entrada.get("title") or t("msg.recovered_default"))
        titulo.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: 600;"
        )
        datos.addWidget(titulo)

        fecha = QLabel(t(
            "recovery.date", default="Copia: {date}",
            date=self._texto_fecha(entrada.get("modified_at"))))
        fecha.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 11px;")
        datos.addWidget(fecha)

        ruta = entrada.get("project_path")
        if ruta:
            texto_ruta = ruta
        else:
            texto_ruta = t(
                "recovery.no_original", default="Sin archivo original asociado")
        self.ruta = QLabel(t(
            "recovery.original_path", default="Original: {path}",
            path=texto_ruta))
        self.ruta.setWordWrap(True)
        self.ruta.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ruta.setToolTip(ruta or texto_ruta)
        self.ruta.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        datos.addWidget(self.ruta, 1)

        acciones = QHBoxLayout()
        acciones.setSpacing(6)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._botones = {}
        for accion, clave, predeterminada in (
                ("open", "recovery.action.open", True),
                ("keep", "recovery.action.keep", False),
                ("discard", "recovery.action.discard", False)):
            boton = QPushButton(t(clave))
            boton.setCheckable(True)
            boton.setChecked(predeterminada)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(theme.labeled_toggle_qss())
            boton.setMinimumHeight(28)
            self._grupo.addButton(boton)
            self._botones[accion] = boton
            acciones.addWidget(boton)
        acciones.addStretch(1)
        datos.addLayout(acciones)
        raiz.addLayout(datos, 1)

    def _cargar_miniatura(self):
        ruta = self.entrada.get("thumbnail_path")
        pixmap = QPixmap(ruta) if ruta and os.path.exists(ruta) else QPixmap()
        if pixmap.isNull():
            self.miniatura.setText(t(
                "recovery.no_preview", default="Vista previa no disponible"))
            self.miniatura.setWordWrap(True)
            return
        self.miniatura.setPixmap(pixmap.scaled(
            self.ANCHO_MINIATURA - 4, self.ALTO_MINIATURA - 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    @staticmethod
    def _texto_fecha(timestamp):
        if timestamp is None:
            return t("recovery.unknown_date", default="Fecha desconocida")
        fecha = QDateTime.fromSecsSinceEpoch(int(timestamp)).toLocalTime()
        return QLocale().toString(fecha, QLocale.FormatType.ShortFormat)

    def accion(self):
        for accion, boton in self._botones.items():
            if boton.isChecked():
                return accion
        return "keep"

    def set_accion(self, accion):
        """Auxiliar explícito usado también por las pruebas de regresión."""
        boton = self._botones.get(accion)
        if boton is not None:
            boton.setChecked(True)


class RecoveryManagerDialog(FramelessDialog):
    """Decide individualmente qué hacer con cada copia recuperable."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("recovery.manager.title"))
        self.setModal(True)
        self._filas = []

        self.body_layout.setContentsMargins(14, 12, 14, 14)
        self.body_layout.setSpacing(10)
        self._body.setMinimumWidth(760)

        introduccion = QLabel(t("recovery.manager.intro", n=len(entries)))
        introduccion.setWordWrap(True)
        introduccion.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        self.body_layout.addWidget(introduccion)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {theme.BG_WINDOW}; }}"
        )
        contenido = QWidget()
        lista = QVBoxLayout(contenido)
        lista.setContentsMargins(0, 0, 0, 0)
        lista.setSpacing(8)
        for entrada in entries:
            fila = _FilaRecuperacion(entrada, contenido)
            self._filas.append(fila)
            lista.addWidget(fila)
        lista.addStretch(1)
        scroll.setWidget(contenido)
        scroll.setMinimumHeight(min(500, max(138, len(entries) * 138)))
        self.body_layout.addWidget(scroll, 1)

        nota = QLabel(t("recovery.manager.keep_note"))
        nota.setWordWrap(True)
        nota.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        self.body_layout.addWidget(nota)

        pie = QHBoxLayout()
        pie.addStretch(1)
        continuar = QPushButton(t("recovery.manager.continue"))
        continuar.setObjectName("RecoveryContinueButton")
        continuar.setDefault(True)
        continuar.setStyleSheet(theme.dialog_button_qss(
            "QPushButton#RecoveryContinueButton"))
        continuar.clicked.connect(self.accept)
        pie.addWidget(continuar)
        self.body_layout.addLayout(pie)

    def decisiones(self):
        return [(fila.entrada, fila.accion()) for fila in self._filas]
