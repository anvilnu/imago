"""Buffers dispersos y conversiones locales para herramientas de pincel.

Las herramientas que solo actúan alrededor del cursor no deben convertir la
capa completa a NumPy. Este módulo mantiene coberturas por teselas y ofrece
lectura/escritura RGBA de rectángulos pequeños sobre un QImage.
"""

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter


class CoberturaDispersa:
    """Máscara float32 por teselas, creada solo en las zonas tocadas."""

    LADO_TESELA = 256

    def __init__(self, ancho, alto):
        self.ancho = int(ancho)
        self.alto = int(alto)
        self._teselas = {}

    def _tesela(self, tx, ty, crear=False):
        clave = (tx, ty)
        tesela = self._teselas.get(clave)
        if tesela is None and crear:
            tesela = np.zeros(
                (self.LADO_TESELA, self.LADO_TESELA), dtype=np.float32)
            self._teselas[clave] = tesela
        return tesela

    def _trozos(self, x0, y0, x1, y1, crear=False):
        lado = self.LADO_TESELA
        for ty in range(y0 // lado, (y1 - 1) // lado + 1):
            gy0 = max(y0, ty * lado)
            gy1 = min(y1, (ty + 1) * lado)
            for tx in range(x0 // lado, (x1 - 1) // lado + 1):
                gx0 = max(x0, tx * lado)
                gx1 = min(x1, (tx + 1) * lado)
                tesela = self._tesela(tx, ty, crear)
                yield (tesela,
                       slice(gy0 - ty * lado, gy1 - ty * lado),
                       slice(gx0 - tx * lado, gx1 - tx * lado),
                       slice(gy0 - y0, gy1 - y0),
                       slice(gx0 - x0, gx1 - x0))

    def maximo(self, x0, y0, valores):
        """Acumula `valores` mediante máximo, sin solapar opacidad."""
        h, w = valores.shape
        if w <= 0 or h <= 0:
            return
        for tesela, tsy, tsx, vy, vx in self._trozos(
                x0, y0, x0 + w, y0 + h, crear=True):
            np.maximum(tesela[tsy, tsx], valores[vy, vx],
                       out=tesela[tsy, tsx])

    def sumar_saturado(self, x0, y0, valores):
        """Suma dosis y limita la cobertura acumulada al intervalo 0..1."""
        h, w = valores.shape
        if w <= 0 or h <= 0:
            return
        for tesela, tsy, tsx, vy, vx in self._trozos(
                x0, y0, x0 + w, y0 + h, crear=True):
            region = tesela[tsy, tsx]
            np.minimum(region + valores[vy, vx], 1.0, out=region)

    def region(self, x0, y0, x1, y1):
        """Materializa solo el rectángulo solicitado; lo no tocado vale cero."""
        salida = np.zeros((max(0, y1 - y0), max(0, x1 - x0)),
                          dtype=np.float32)
        if salida.size == 0:
            return salida
        for tesela, tsy, tsx, vy, vx in self._trozos(
                x0, y0, x1, y1, crear=False):
            if tesela is not None:
                salida[vy, vx] = tesela[tsy, tsx]
        return salida

    @property
    def bytes_asignados(self):
        return sum(tesela.nbytes for tesela in self._teselas.values())


class ImagenPremultiplicadaDispersa:
    """Estado RGBA float32 premultiplicado, cargado por teselas bajo demanda.

    Dedo y Licuar conservan aquí la precisión float de todo el trazo sin crear
    el antiguo array H×W×4. Las teselas aún no visitadas se leen de la imagen
    original cuando una operación local necesita muestrearlas.
    """

    LADO_TESELA = 256

    def __init__(self, imagen):
        self._origen = QImage(imagen)
        self.ancho = imagen.width()
        self.alto = imagen.height()
        self._teselas = {}

    def _tesela(self, tx, ty):
        clave = (tx, ty)
        tesela = self._teselas.get(clave)
        if tesela is not None:
            return tesela
        lado = self.LADO_TESELA
        x0, y0 = tx * lado, ty * lado
        x1, y1 = min(self.ancho, x0 + lado), min(self.alto, y0 + lado)
        rgba = imagen_rgba_region(self._origen, x0, y0, x1, y1)
        tesela = rgba.astype(np.float32)
        tesela[..., :3] *= tesela[..., 3:4] / 255.0
        self._teselas[clave] = tesela
        return tesela

    def _trozos(self, x0, y0, x1, y1):
        lado = self.LADO_TESELA
        for ty in range(y0 // lado, (y1 - 1) // lado + 1):
            gy0 = max(y0, ty * lado)
            gy1 = min(y1, (ty + 1) * lado)
            for tx in range(x0 // lado, (x1 - 1) // lado + 1):
                gx0 = max(x0, tx * lado)
                gx1 = min(x1, (tx + 1) * lado)
                yield (self._tesela(tx, ty),
                       slice(gy0 - ty * lado, gy1 - ty * lado),
                       slice(gx0 - tx * lado, gx1 - tx * lado),
                       slice(gy0 - y0, gy1 - y0),
                       slice(gx0 - x0, gx1 - x0))

    def region(self, x0, y0, x1, y1):
        salida = np.empty((y1 - y0, x1 - x0, 4), dtype=np.float32)
        for tesela, tsy, tsx, sy, sx in self._trozos(x0, y0, x1, y1):
            salida[sy, sx] = tesela[tsy, tsx]
        return salida

    def escribir_region(self, x0, y0, valores):
        h, w = valores.shape[:2]
        for tesela, tsy, tsx, sy, sx in self._trozos(
                x0, y0, x0 + w, y0 + h):
            tesela[tsy, tsx] = valores[sy, sx]

    @property
    def bytes_asignados(self):
        return sum(tesela.nbytes for tesela in self._teselas.values())


def imagen_rgba_region(imagen, x0, y0, x1, y1):
    """Copia un ROI de QImage como ndarray RGBA uint8 independiente."""
    w, h = x1 - x0, y1 - y0
    sub = imagen.copy(x0, y0, w, h).convertToFormat(QImage.Format_RGBA8888)
    bpl = sub.bytesPerLine()
    datos = np.frombuffer(sub.constBits(), np.uint8).reshape(h, bpl)
    return datos[:, :w * 4].reshape(h, w, 4).copy()


def escribir_rgba_region(imagen, x0, y0, valores):
    """Vuelca un ndarray RGBA uint8 sobre un QImage usando modo Source."""
    valores = np.ascontiguousarray(valores, dtype=np.uint8)
    h, w = valores.shape[:2]
    parche = QImage(valores.data, w, h, 4 * w, QImage.Format_RGBA8888)
    painter = QPainter(imagen)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.drawImage(x0, y0, parche)
    painter.end()


def mascara_seleccion_region(canvas, x0, y0, x1, y1):
    """Máscara float32 dura de la selección para un ROI, o None si no hay."""
    seleccion = getattr(canvas, "selection", None)
    if seleccion is None or seleccion.isEmpty():
        return None
    w, h = x1 - x0, y1 - y0
    mascara = QImage(w, h, QImage.Format_Grayscale8)
    mascara.fill(0)
    painter = QPainter(mascara)
    painter.translate(-x0, -y0)
    painter.setClipPath(seleccion)
    painter.fillRect(x0, y0, w, h, QColor(Qt.white))
    painter.end()
    bpl = mascara.bytesPerLine()
    datos = np.frombuffer(mascara.constBits(), np.uint8).reshape(h, bpl)
    return (datos[:, :w] > 127).astype(np.float32)
