"""Conservación de metadatos EXIF al reescribir un JPEG.

Imago no recomprime la imagen para conservar los metadatos: el JPEG lo sigue
escribiendo el codificador de Qt (QImageWriter) y aquí sólo se INCRUSTA el
bloque EXIF del archivo original como un segmento APP1, byte a byte (sin volver
a comprimir los píxeles). Así se conservan fecha, cámara/objetivo, GPS, la
miniatura embebida, etc.

CLAVE: se inyecta el EXIF CRUDO original tal cual (parcheado IN SITU, sin
cambiar de tamaño), NO una re-serialización con Pillow. Pillow (Image.Exif.
tobytes) reescribe el TIFF de una forma que los lectores estrictos como exiv2
—el que usan KDE/Dolphin, Gwenview, etc.— RECHAZAN ("no parece imagen TIFF"),
además de descartar la miniatura. Parcheando los bytes originales se conserva un
TIFF válido idéntico al de la cámara.

Dos retoques in situ (mismo número de bytes, offsets intactos):
- Orientación (tag 0x0112 de IFD0) -> 1: cargar_imagen_orientada() ya aplicó la
  rotación a los píxeles al abrir; dejar la orientación original haría que los
  visores volvieran a girar la foto.
- Si no se quiere conservar el GPS, se sobrescriben con ceros la tabla GPS y
  todos sus valores externos antes de neutralizar el puntero 0x8825. Si el
  bloque no se puede validar por completo, se descarta todo el EXIF: la
  privacidad prevalece sobre conservar metadatos posiblemente dañados.

El EXIF se coloca justo tras el marcador SOI (antes del APP0/JFIF que escribe
Qt), que es como lo ponen las cámaras. Pillow sólo se usa para LEER el bloque
del original (import perezoso: si faltara, el guardado sigue, sólo que sin EXIF).
"""
from __future__ import annotations

import struct
from atomic_io import escribir_atomico


_TIFF_TYPE_SIZES = {
    1: 1,   # BYTE
    2: 1,   # ASCII
    3: 2,   # SHORT
    4: 4,   # LONG
    5: 8,   # RATIONAL
    6: 1,   # SBYTE
    7: 1,   # UNDEFINED
    8: 2,   # SSHORT
    9: 4,   # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
}
_GPS_WIPED_MARKER = b"IGPS"


def leer_exif(ruta):
    """Devuelve los bytes EXIF crudos de una imagen de disco, o None si no los
    tiene o no se pueden leer. No decodifica los píxeles (Pillow es perezoso)."""
    try:
        from PIL import Image
        with Image.open(ruta) as im:
            return im.info.get("exif")
    except Exception:
        return None


def _ifd_bounds(buf, tiff_start, fmt, offset):
    """Valida un IFD TIFF y devuelve (inicio, entradas, fin), o None."""
    if offset < 8:
        return None
    start = tiff_start + offset
    if start < tiff_start or start + 2 > len(buf):
        return None
    count = struct.unpack_from(fmt + "H", buf, start)[0]
    entries_start = start + 2
    end = entries_start + count * 12 + 4
    if end > len(buf):
        return None
    return start, entries_start, end


def _gps_ranges(buf, tiff_start, fmt, gps_offset, protected):
    """Obtiene todos los rangos que pertenecen al GPS IFD, ya validados.

    Incluye la tabla completa y cada valor que no cabe inline. Los rangos no
    pueden invadir la estructura de IFD0, pues borrarlos corrompería el TIFF.
    """
    bounds = _ifd_bounds(buf, tiff_start, fmt, gps_offset)
    if bounds is None:
        return None
    start, entries_start, end = bounds
    if start < protected[1] and end > protected[0]:
        return None
    if struct.unpack_from(fmt + "I", buf, end - 4)[0] != 0:
        return None
    ranges = [(start, end)]
    count = (end - entries_start - 4) // 12
    for index in range(count):
        entry = entries_start + index * 12
        tag = struct.unpack_from(fmt + "H", buf, entry)[0]
        if tag > 0x001F:
            return None
        value_type = struct.unpack_from(fmt + "H", buf, entry + 2)[0]
        value_count = struct.unpack_from(fmt + "I", buf, entry + 4)[0]
        unit_size = _TIFF_TYPE_SIZES.get(value_type)
        if unit_size is None:
            return None
        value_size = value_count * unit_size
        if value_size <= 4:
            continue
        value_offset = struct.unpack_from(fmt + "I", buf, entry + 8)[0]
        value_start = tiff_start + value_offset
        value_end = value_start + value_size
        if value_offset < 8 or value_start < tiff_start or value_end > len(buf):
            return None
        if value_start < protected[1] and value_end > protected[0]:
            return None
        ranges.append((value_start, value_end))
    return ranges


def _wipe_gps(buf, tiff_start, fmt, gps_entry, gps_offset, ifd0_range):
    """Sobrescribe físicamente GPS y convierte su puntero en Padding."""
    ranges = _gps_ranges(buf, tiff_start, fmt, gps_offset, ifd0_range)
    if ranges is None:
        return False
    for start, end in ranges:
        buf[start:end] = b"\x00" * (end - start)
    struct.pack_into(fmt + "H", buf, gps_entry, 0xEA1C)  # Padding
    struct.pack_into(fmt + "H", buf, gps_entry + 2, 1)   # BYTE
    struct.pack_into(fmt + "I", buf, gps_entry + 4, 4)
    buf[gps_entry + 8:gps_entry + 12] = _GPS_WIPED_MARKER
    return True


def _patch_exif_raw(raw, quitar_gps=False):
    """Normaliza orientación y, opcionalmente, borra físicamente el GPS.

    Conserva el tamaño, la miniatura, las maker notes y todos los offsets. Si
    se pide quitar GPS pero no se puede validar y sobrescribir todo su IFD,
    devuelve None para que el guardado omita el EXIF completo.
    """
    try:
        if not raw or raw[:6] != b"Exif\x00\x00":
            return None
        buf = bytearray(raw)
        tiff_start = 6
        if len(buf) < tiff_start + 8:
            return None
        byte_order = bytes(buf[tiff_start:tiff_start + 2])
        if byte_order == b"II":
            fmt = "<"
        elif byte_order == b"MM":
            fmt = ">"
        else:
            return None
        if struct.unpack_from(fmt + "H", buf, tiff_start + 2)[0] != 42:
            return None
        ifd0_offset = struct.unpack_from(fmt + "I", buf, tiff_start + 4)[0]
        bounds = _ifd_bounds(buf, tiff_start, fmt, ifd0_offset)
        if bounds is None:
            return None
        ifd0_start, entries_start, ifd0_end = bounds
        count = (ifd0_end - entries_start - 4) // 12
        gps_entries = []
        legacy_gps_padding = False
        for index in range(count):
            entry = entries_start + index * 12
            tag = struct.unpack_from(fmt + "H", buf, entry)[0]
            if tag == 0x0112:
                value_type = struct.unpack_from(fmt + "H", buf, entry + 2)[0]
                value_count = struct.unpack_from(fmt + "I", buf, entry + 4)[0]
                if value_type == 3 and value_count == 1:
                    struct.pack_into(fmt + "H", buf, entry + 8, 1)
            elif tag == 0x8825:
                gps_entries.append(entry)
            elif tag == 0xEA1C:
                is_imago_padding = (
                    struct.unpack_from(fmt + "H", buf, entry + 2)[0] == 1
                    and struct.unpack_from(fmt + "I", buf, entry + 4)[0] == 4)
                if is_imago_padding:
                    marker = bytes(buf[entry + 8:entry + 12])
                    legacy_gps_padding = legacy_gps_padding or marker == b"\x00" * 4

        if quitar_gps:
            if gps_entries:
                if len(gps_entries) != 1:
                    return None
                gps_entry = gps_entries[0]
                value_type = struct.unpack_from(fmt + "H", buf, gps_entry + 2)[0]
                value_count = struct.unpack_from(fmt + "I", buf, gps_entry + 4)[0]
                if value_type != 4 or value_count != 1:
                    return None
                gps_offset = struct.unpack_from(fmt + "I", buf, gps_entry + 8)[0]
                if not _wipe_gps(
                        buf, tiff_start, fmt, gps_entry, gps_offset,
                        (ifd0_start, ifd0_end)):
                    return None
            elif legacy_gps_padding:
                # Versiones anteriores de Imago borraban el offset y dejaban
                # los bytes GPS huérfanos. Ya no es posible localizarlos con
                # seguridad: se omite todo el EXIF para no volver a copiarlos.
                return None
        return bytes(buf)
    except (IndexError, OverflowError, struct.error, ValueError):
        return None


def incrustar_exif_jpeg(ruta_jpeg, exif_bytes, incluir_gps=True):
    """Inserta el EXIF del original (orientación normalizada y, opcionalmente, sin
    GPS) en un JPEG ya escrito, como segmento APP1 tras el SOI, SIN recomprimir.
    Devuelve True si lo incrustó.

    No hace nada (devuelve False) si no hay EXIF, si no reconoce la cabecera, si
    el archivo no es un JPEG válido, si ya trae un APP1 'Exif' o si el bloque no
    cabe en un único segmento (límite de 64 KB del formato)."""
    if not exif_bytes:
        return False
    payload = _patch_exif_raw(exif_bytes, quitar_gps=not incluir_gps)
    if not payload:
        return False
    # APP1 = FFE1 | longitud(2 bytes, se incluye a sí misma) | payload('Exif\0\0'+TIFF)
    if len(payload) + 2 > 0xFFFF:  # no cabe en un solo segmento: no se incrusta
        return False
    app1 = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    try:
        with open(ruta_jpeg, "rb") as f:
            datos = f.read()
    except OSError:
        return False
    if datos[:2] != b"\xff\xd8":          # no es un JPEG (falta el marcador SOI)
        return False
    if b"Exif\x00\x00" in datos[:4096]:   # ya trae EXIF: no duplicar el segmento
        return False
    # Justo tras el SOI, antes del APP0/JFIF (como lo colocan las cámaras).
    nuevo = datos[:2] + app1 + datos[2:]
    def _escribir(ruta_temporal):
        with open(ruta_temporal, "wb") as f:
            f.write(nuevo)
        return True

    return escribir_atomico(ruta_jpeg, _escribir)
