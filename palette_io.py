"""Lectura tolerante de formatos habituales de paletas de color."""

import colorsys
import os
import re
import struct

from PySide6.QtGui import QColor


EXTENSIONES_PALETA = (".gpl", ".ase", ".aco", ".act", ".pal",
                      ".txt", ".hex", ".css")
MAX_BYTES_PALETA = 16 * 1024 * 1024


def _sin_duplicados(colores):
    salida = []
    vistos = set()
    for color in colores or ():
        if not isinstance(color, QColor) or not color.isValid():
            continue
        clave = color.rgba()
        if clave in vistos:
            continue
        vistos.add(clave)
        salida.append(QColor(color))
    return salida


def _texto(datos):
    try:
        return datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        return datos.decode("latin-1", errors="replace")


def _parse_gpl(datos):
    lineas = _texto(datos).splitlines()
    if not lineas or "gimp palette" not in lineas[0].strip().lower():
        return None
    colores = []
    for linea in lineas[1:]:
        limpia = linea.strip()
        if (not limpia or limpia.startswith("#")
                or limpia.lower().startswith(("name:", "columns:"))):
            continue
        partes = limpia.split()
        if len(partes) < 3:
            continue
        try:
            r, g, b = (max(0, min(255, int(valor)))
                       for valor in partes[:3])
        except ValueError:
            continue
        colores.append(QColor(r, g, b))
    return colores


def _parse_jasc(datos):
    lineas = [linea.strip() for linea in _texto(datos).splitlines()
              if linea.strip()]
    if len(lineas) < 3 or lineas[0].upper() != "JASC-PAL":
        return None
    try:
        cantidad = max(0, int(lineas[2]))
    except ValueError:
        return None
    colores = []
    for linea in lineas[3:3 + cantidad]:
        partes = linea.replace(",", " ").split()
        if len(partes) < 3:
            continue
        try:
            r, g, b = (max(0, min(255, int(valor)))
                       for valor in partes[:3])
        except ValueError:
            continue
        colores.append(QColor(r, g, b))
    return colores


def _parse_riff_pal(datos):
    if (len(datos) < 12 or datos[:4] != b"RIFF"
            or datos[8:12] != b"PAL "):
        return None
    posicion = 12
    while posicion + 8 <= len(datos):
        tipo = datos[posicion:posicion + 4]
        tamano = struct.unpack_from("<I", datos, posicion + 4)[0]
        inicio = posicion + 8
        fin = inicio + tamano
        if fin > len(datos):
            return None
        if tipo == b"data" and tamano >= 4:
            cantidad = struct.unpack_from("<H", datos, inicio + 2)[0]
            if 4 + cantidad * 4 > tamano:
                return None
            return [QColor(*datos[inicio + 4 + i * 4:
                                  inicio + 7 + i * 4])
                    for i in range(cantidad)]
        posicion = fin + (tamano & 1)
    return None


def _parse_act(datos):
    if len(datos) not in (768, 772):
        return None
    cantidad = 256
    transparente = None
    if len(datos) == 772:
        cantidad = struct.unpack_from(">H", datos, 768)[0] or 256
        cantidad = min(256, cantidad)
        indice = struct.unpack_from(">H", datos, 770)[0]
        transparente = indice if indice < cantidad else None
    colores = []
    for i in range(cantidad):
        color = QColor(*datos[i * 3:i * 3 + 3])
        if i == transparente:
            color.setAlpha(0)
        colores.append(color)
    return colores


def _lab_a_rgb(luz, componente_a, componente_b):
    """Convierte CIE Lab (D50 aproximado) a sRGB."""
    fy = (luz + 16.0) / 116.0
    fx = fy + componente_a / 500.0
    fz = fy - componente_b / 200.0

    def inversa(valor):
        cubo = valor ** 3
        return cubo if cubo > 0.008856 else (valor - 16.0 / 116.0) / 7.787

    x = 0.96422 * inversa(fx)
    y = 1.00000 * inversa(fy)
    z = 0.82521 * inversa(fz)
    r = 3.1338561 * x - 1.6168667 * y - 0.4906146 * z
    g = -0.9787684 * x + 1.9161415 * y + 0.0334540 * z
    b = 0.0719453 * x - 0.2289914 * y + 1.4052427 * z

    def gamma(valor):
        valor = max(0.0, min(1.0, valor))
        return (12.92 * valor if valor <= 0.0031308
                else 1.055 * valor ** (1.0 / 2.4) - 0.055)

    return QColor.fromRgbF(gamma(r), gamma(g), gamma(b))


def _aco_color(espacio, valores):
    if espacio == 0:  # RGB
        return QColor.fromRgbF(*(valor / 65535.0 for valor in valores[:3]))
    if espacio == 1:  # HSB/HSV
        h, s, v = (valor / 65535.0 for valor in valores[:3])
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
        return QColor.fromRgbF(r, g, b)
    if espacio == 2:  # CMYK: Adobe guarda 0=100 %, 65535=0 %
        c, m, y, k = (1.0 - valor / 65535.0 for valor in valores)
        return QColor.fromCmykF(c, m, y, k)
    if espacio == 7:  # Lab: L 0..10000, a/b con signo y dos decimales
        a = struct.unpack(">h", struct.pack(">H", valores[1]))[0] / 100.0
        b = struct.unpack(">h", struct.pack(">H", valores[2]))[0] / 100.0
        return _lab_a_rgb(valores[0] / 100.0, a, b)
    if espacio == 8:  # Escala de grises 0..10000
        gris = max(0.0, min(1.0, valores[0] / 10000.0))
        return QColor.fromRgbF(gris, gris, gris)
    return None


def _seccion_aco(datos, posicion):
    if posicion + 4 > len(datos):
        return None
    version, cantidad = struct.unpack_from(">HH", datos, posicion)
    if version not in (1, 2):
        return None
    posicion += 4
    colores = []
    for _ in range(cantidad):
        if posicion + 10 > len(datos):
            return None
        espacio, *valores = struct.unpack_from(">HHHHH", datos, posicion)
        posicion += 10
        color = _aco_color(espacio, valores)
        if color is not None and color.isValid():
            colores.append(color)
        if version == 2:
            if posicion + 4 > len(datos):
                return None
            longitud = struct.unpack_from(">I", datos, posicion)[0]
            posicion += 4
            bytes_nombre = longitud * 2
            if posicion + bytes_nombre > len(datos):
                return None
            posicion += bytes_nombre
    return version, colores, posicion


def _parse_aco(datos):
    primera = _seccion_aco(datos, 0)
    if primera is None:
        return None
    _version, colores, posicion = primera
    # Muchos ACO incluyen primero la sección v1 y después la v2 con nombres.
    segunda = _seccion_aco(datos, posicion) if posicion < len(datos) else None
    return segunda[1] if segunda is not None else colores


def _parse_ase(datos):
    if len(datos) < 12 or datos[:4] != b"ASEF":
        return None
    cantidad = struct.unpack_from(">I", datos, 8)[0]
    posicion = 12
    colores = []
    for _ in range(cantidad):
        if posicion + 6 > len(datos):
            return None
        tipo, tamano = struct.unpack_from(">HI", datos, posicion)
        posicion += 6
        fin = posicion + tamano
        if fin > len(datos):
            return None
        if tipo == 0x0001:
            if posicion + 2 > fin:
                return None
            longitud = struct.unpack_from(">H", datos, posicion)[0]
            cursor = posicion + 2 + longitud * 2
            if cursor + 4 > fin:
                return None
            modelo = datos[cursor:cursor + 4]
            cursor += 4
            componentes = {b"RGB ": 3, b"CMYK": 4,
                           b"LAB ": 3, b"Gray": 1}.get(modelo)
            if componentes is not None and cursor + componentes * 4 + 2 <= fin:
                valores = struct.unpack_from(">" + "f" * componentes,
                                             datos, cursor)
                if modelo == b"RGB ":
                    color = QColor.fromRgbF(*valores)
                elif modelo == b"CMYK":
                    color = QColor.fromCmykF(*valores)
                elif modelo == b"Gray":
                    gris = max(0.0, min(1.0, valores[0]))
                    color = QColor.fromRgbF(gris, gris, gris)
                else:
                    color = _lab_a_rgb(valores[0] * 100.0,
                                       valores[1] * 128.0,
                                       valores[2] * 128.0)
                if color.isValid():
                    colores.append(color)
        posicion = fin
    return colores


def _color_hex(valor, alfa_final=False):
    valor = valor.strip().lstrip("#")
    if len(valor) in (3, 4):
        valor = "".join(caracter * 2 for caracter in valor)
    try:
        numero = int(valor, 16)
    except ValueError:
        return None
    if len(valor) == 6:
        return QColor((numero >> 16) & 255, (numero >> 8) & 255, numero & 255)
    if len(valor) == 8:
        if alfa_final:  # CSS: RRGGBBAA
            return QColor((numero >> 24) & 255, (numero >> 16) & 255,
                          (numero >> 8) & 255, numero & 255)
        return QColor((numero >> 16) & 255, (numero >> 8) & 255,
                      numero & 255, (numero >> 24) & 255)
    return None


def _parse_css(datos):
    texto = _texto(datos)
    colores = []
    for valor in re.findall(r"(?<![\w-])#([0-9a-fA-F]{3,8})(?![\w-])", texto):
        if len(valor) in (3, 4, 6, 8):
            color = _color_hex(valor, alfa_final=True)
            if color is not None:
                colores.append(color)
    patron_rgb = re.compile(r"rgba?\s*\(([^)]*)\)", re.IGNORECASE)
    for coincidencia in patron_rgb.finditer(texto):
        partes = [p for p in re.split(r"[,/\s]+", coincidencia.group(1).strip())
                  if p]
        if len(partes) < 3:
            continue
        try:
            rgb = [round(float(p[:-1]) * 2.55) if p.endswith("%")
                   else round(float(p)) for p in partes[:3]]
            if not all(0 <= valor <= 255 for valor in rgb):
                continue
            alfa = 255
            if len(partes) >= 4:
                alfa = (round(float(partes[3][:-1]) * 2.55)
                        if partes[3].endswith("%")
                        else round(float(partes[3]) * 255.0))
            colores.append(QColor(*rgb, max(0, min(255, alfa))))
        except ValueError:
            continue
    return colores


def _parse_lista_texto(datos, alfa_final=False):
    colores = []
    for linea in _texto(datos).splitlines():
        limpia = linea.split(";", 1)[0].strip()
        if not limpia or limpia.startswith("//"):
            continue
        coincidencia = re.fullmatch(r"#?([0-9a-fA-F]{3,8})", limpia)
        if coincidencia and len(coincidencia.group(1)) in (3, 4, 6, 8):
            color = _color_hex(coincidencia.group(1), alfa_final=alfa_final)
            if color is not None:
                colores.append(color)
            continue
        partes = limpia.replace(",", " ").split()
        if len(partes) >= 3:
            try:
                r, g, b = (int(valor) for valor in partes[:3])
            except ValueError:
                continue
            if all(0 <= valor <= 255 for valor in (r, g, b)):
                colores.append(QColor(r, g, b))
    return colores


def cargar_paleta(ruta):
    """Devuelve colores únicos de una paleta compatible, o ``None`` si no lo es."""
    try:
        with open(ruta, "rb") as archivo:
            datos = archivo.read(MAX_BYTES_PALETA + 1)
    except OSError:
        return None
    if not datos or len(datos) > MAX_BYTES_PALETA:
        return None

    extension = os.path.splitext(os.fspath(ruta))[1].lower()
    if datos.startswith(b"ASEF"):
        colores = _parse_ase(datos)
    elif datos.startswith(b"RIFF"):
        colores = _parse_riff_pal(datos)
    elif _texto(datos[:64]).lstrip().lower().startswith("gimp palette"):
        colores = _parse_gpl(datos)
    elif _texto(datos[:64]).lstrip().upper().startswith("JASC-PAL"):
        colores = _parse_jasc(datos)
    elif extension == ".aco":
        colores = _parse_aco(datos)
    elif extension == ".act":
        colores = _parse_act(datos)
    elif extension == ".css":
        colores = _parse_css(datos)
    elif extension in (".txt", ".hex"):
        colores = _parse_lista_texto(datos, alfa_final=(extension == ".hex"))
    else:
        return None
    if colores is None:
        return None
    return _sin_duplicados(colores)
