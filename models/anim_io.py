# models/anim_io.py
# Exportación de animaciones GIF/WebP: las CAPAS efectivamente visibles del
# lienzo son los fotogramas (de abajo hacia arriba). Escribe con Pillow (import PEREZOSO,
# como en exif_utils: Qt no trae escritor animado); si falta, se avisa y no
# se rompe nada.

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from atomic_io import escribir_atomico
from models.layer import visible_efectiva


def _qimage_a_pil(img):
    """QImage -> PIL.Image (RGBA), pasando por los bytes RGBA8888 crudos."""
    from PIL import Image
    img = img.convertToFormat(QImage.Format_RGBA8888)
    W, H = img.width(), img.height()
    bpl = img.bytesPerLine()
    datos = bytes(img.constBits())
    # .copy() desliga la PIL.Image del buffer temporal de Qt.
    return Image.frombuffer("RGBA", (W, H), datos, "raw", "RGBA", bpl, 1).copy()


def capas_de_animacion(canvas):
    """Capas que aportan fotogramas, respetando su visibilidad y la de todos
    sus grupos. Conserva el orden del lienzo: de abajo hacia arriba."""
    return [layer for layer in canvas.layers if visible_efectiva(layer)]


def frames_de_capas(canvas):
    """Fotogramas de la animación: una imagen RGBA por capa efectivamente
    visible, de abajo hacia arriba, compuesta SUELTA con máscara, efectos y
    opacidad sobre transparente a tamaño de lienzo. Devuelve (frames, delays),
    con el frame_delay de cada capa (o None si no lo trae)."""
    frames, delays = [], []
    for layer in capas_de_animacion(canvas):
        base = QImage(canvas.base_width, canvas.base_height,
                      QImage.Format_ARGB32_Premultiplied)
        base.fill(Qt.transparent)
        p = QPainter(base)
        p.setOpacity(max(0, min(100, int(layer.opacity))) / 100.0)
        p.drawImage(0, 0, layer.render_with_effects())
        p.end()
        frames.append(base)
        delays.append(getattr(layer, "frame_delay", None))
    return frames, delays


def save_animation_frames(frames, delays, file_path, duration_ms, loop=True,
                          use_original=False, report=None, token=None):
    """Comprime fotogramas ya capturados como GIF o WebP animado.

    Es seguro ejecutarlo en un worker. ``duration_ms`` vale para todos los
    fotogramas, salvo que
    use_original sea True y las capas traigan frame_delay (importadas de un
    animado). Devuelve (ok, error), con error None, "pillow" (falta Pillow),
    "frames" (menos de 2 fotogramas), "cancelled" o "write"."""
    try:
        from PIL import Image
    except ImportError:
        return False, "pillow"

    if len(frames) < 2:
        return False, "frames"

    if use_original and any(delays):
        dur = [int(d) if d else int(duration_ms) for d in delays]
    else:
        dur = int(duration_ms)

    es_gif = file_path.lower().endswith(".gif")
    pils = []
    for indice, f in enumerate(frames):
        if token is not None and token.cancelled:
            return False, "cancelled"
        pil = _qimage_a_pil(f)
        if es_gif:
            # GIF no tiene alfa parcial: se compone sobre blanco (la
            # cuantización a paleta la hace Pillow al guardar).
            fondo = Image.new("RGB", pil.size, (255, 255, 255))
            fondo.paste(pil, mask=pil.getchannel("A"))
            pil = fondo
        pils.append(pil)
        if report is not None:
            report(5 + int(70 * (indice + 1) / len(frames)))

    extra = {}
    if loop:
        extra["loop"] = 0            # 0 = bucle infinito (GIF y WebP)
    elif not es_gif:
        extra["loop"] = 1            # WebP: una sola pasada
    # GIF sin 'loop': sin extensión de bucle = se reproduce una vez.
    def _escribir(ruta_temporal):
        if token is not None and token.cancelled:
            return False
        pils[0].save(ruta_temporal, save_all=True, append_images=pils[1:],
                     duration=dur, optimize=es_gif, **extra)
        return token is None or not token.cancelled

    try:
        if escribir_atomico(file_path, _escribir):
            if report is not None:
                report(100)
            return True, None
        if token is not None and token.cancelled:
            return False, "cancelled"
        return False, "write"
    except (OSError, ValueError):
        return False, "write"


def save_animation(canvas, file_path, duration_ms, loop=True, use_original=False,
                   report=None, token=None):
    """Captura los fotogramas y conserva la API síncrona histórica."""
    frames, delays = frames_de_capas(canvas)
    return save_animation_frames(
        frames, delays, file_path, duration_ms, loop=loop,
        use_original=use_original, report=report, token=token)
