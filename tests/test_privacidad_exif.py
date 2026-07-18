"""Regresiones del borrado físico de ubicación en bloques EXIF."""

import os
import struct
import tempfile
import unittest

from exif_utils import _patch_exif_raw, incrustar_exif_jpeg


def _crear_exif(orden="<"):
    """Crea un EXIF pequeño con GPS externo y datos ajenos como centinelas."""
    raw = bytearray(b"Exif\x00\x00" + b"\x00" * 280)
    tiff = 6
    raw[tiff:tiff + 2] = b"II" if orden == "<" else b"MM"
    struct.pack_into(orden + "H", raw, tiff + 2, 42)
    struct.pack_into(orden + "I", raw, tiff + 4, 8)

    ifd0 = tiff + 8
    struct.pack_into(orden + "H", raw, ifd0, 3)
    orientation = ifd0 + 2
    struct.pack_into(orden + "HHI", raw, orientation, 0x0112, 3, 1)
    struct.pack_into(orden + "H", raw, orientation + 8, 6)
    make = orientation + 12
    struct.pack_into(orden + "HHII", raw, make, 0x010F, 2, 6, 220)
    gps_pointer = make + 12
    struct.pack_into(orden + "HHII", raw, gps_pointer, 0x8825, 4, 1, 60)
    struct.pack_into(orden + "I", raw, gps_pointer + 12, 0)

    gps = tiff + 60
    struct.pack_into(orden + "H", raw, gps, 6)
    entries = gps + 2
    struct.pack_into(orden + "HHI", raw, entries, 0x0000, 1, 4)
    raw[entries + 8:entries + 12] = b"\x02\x03\x00\x00"
    struct.pack_into(orden + "HHI", raw, entries + 12, 0x0001, 2, 2)
    raw[entries + 20:entries + 24] = b"N\x00\x00\x00"
    struct.pack_into(orden + "HHII", raw, entries + 24, 0x0002, 5, 3, 150)
    struct.pack_into(orden + "HHI", raw, entries + 36, 0x0003, 2, 2)
    raw[entries + 44:entries + 48] = b"W\x00\x00\x00"
    struct.pack_into(orden + "HHII", raw, entries + 48, 0x0004, 5, 3, 174)
    struct.pack_into(orden + "HHII", raw, entries + 60, 0x0012, 2, 7, 198)
    struct.pack_into(orden + "I", raw, entries + 72, 0)

    latitude = struct.pack(orden + "IIIIII", 40, 1, 25, 1, 1234, 100)
    longitude = struct.pack(orden + "IIIIII", 3, 1, 42, 1, 5678, 100)
    raw[tiff + 150:tiff + 174] = latitude
    raw[tiff + 174:tiff + 198] = longitude
    raw[tiff + 198:tiff + 205] = b"WGS-84\x00"
    raw[tiff + 220:tiff + 226] = b"CANON\x00"
    raw[tiff + 240:tiff + 254] = b"THUMBNAIL_DATA"
    return bytes(raw), {
        "gps_pointer": gps_pointer,
        "gps_table": (gps, gps + 78),
        "gps_values": (
            (tiff + 150, tiff + 174),
            (tiff + 174, tiff + 198),
            (tiff + 198, tiff + 205),
        ),
        "make": (tiff + 220, tiff + 226),
        "thumbnail": (tiff + 240, tiff + 254),
        "latitude_entry": entries + 24,
    }


class PrivacidadExifTests(unittest.TestCase):
    def test_borra_fisicamente_ifd_y_valores_gps_en_ambos_ordenes(self):
        for orden in ("<", ">"):
            with self.subTest(orden=orden):
                raw, pos = _crear_exif(orden)
                limpio = _patch_exif_raw(raw, quitar_gps=True)

                self.assertIsNotNone(limpio)
                self.assertEqual(len(limpio), len(raw))
                start, end = pos["gps_table"]
                self.assertEqual(limpio[start:end], b"\x00" * (end - start))
                for start, end in pos["gps_values"]:
                    self.assertEqual(limpio[start:end], b"\x00" * (end - start))
                start, end = pos["make"]
                self.assertEqual(limpio[start:end], raw[start:end])
                start, end = pos["thumbnail"]
                self.assertEqual(limpio[start:end], raw[start:end])

                pointer = pos["gps_pointer"]
                self.assertEqual(
                    struct.unpack_from(orden + "HHI", limpio, pointer),
                    (0xEA1C, 1, 4))
                self.assertEqual(limpio[pointer + 8:pointer + 12], b"IGPS")
                self.assertEqual(
                    struct.unpack_from(orden + "H", limpio, 6 + 8 + 2 + 8)[0], 1)
                self.assertEqual(_patch_exif_raw(limpio, quitar_gps=True), limpio)

    def test_conservar_gps_solo_normaliza_la_orientacion(self):
        raw, pos = _crear_exif("<")
        conservado = _patch_exif_raw(raw, quitar_gps=False)

        self.assertIsNotNone(conservado)
        for start, end in (pos["gps_table"], *pos["gps_values"],
                           pos["make"], pos["thumbnail"]):
            self.assertEqual(conservado[start:end], raw[start:end])
        self.assertEqual(
            struct.unpack_from("<H", conservado, 6 + 8 + 2 + 8)[0], 1)

    def test_gps_malformado_omite_exif_completo_sin_tocar_el_jpeg(self):
        raw, pos = _crear_exif("<")
        dañado = bytearray(raw)
        struct.pack_into("<I", dañado, pos["latitude_entry"] + 8, 9000)
        self.assertIsNone(_patch_exif_raw(bytes(dañado), quitar_gps=True))

        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "imagen.jpg")
            original = b"\xff\xd8\xff\xd9"
            with open(ruta, "wb") as archivo:
                archivo.write(original)
            self.assertFalse(
                incrustar_exif_jpeg(ruta, bytes(dañado), incluir_gps=False))
            with open(ruta, "rb") as archivo:
                self.assertEqual(archivo.read(), original)

    def test_saneado_antiguo_omite_exif_para_no_recopiar_bytes_huerfanos(self):
        raw, pos = _crear_exif("<")
        antiguo = bytearray(raw)
        pointer = pos["gps_pointer"]
        struct.pack_into("<HHII", antiguo, pointer, 0xEA1C, 1, 4, 0)

        self.assertIsNone(_patch_exif_raw(bytes(antiguo), quitar_gps=True))
        self.assertIsNotNone(_patch_exif_raw(bytes(antiguo), quitar_gps=False))


if __name__ == "__main__":
    unittest.main()
