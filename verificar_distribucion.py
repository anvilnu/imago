"""Comprueba la higiene y el tamaño de los artefactos de distribución.

Es una verificación de solo lectura: no construye, corrige ni elimina archivos.
Devuelve un código distinto de cero si falta una salida o si una distribución
incluye datos locales, cachés, logs o un marcador portable en el lugar erróneo.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from pathlib import Path, PurePosixPath
import sys
import zipfile


_SUFIJOS_CACHE = {".pyc", ".pyo"}


def _mib(bytes_count):
    return bytes_count / (1024 * 1024)


def _tamano_directorio(ruta):
    return sum(archivo.stat().st_size for archivo in ruta.rglob("*")
               if archivo.is_file())


def _sha256(ruta):
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _es_cache_o_log(partes, nombre):
    partes_lower = tuple(parte.lower() for parte in partes)
    nombre_lower = nombre.lower()
    return (
        "__pycache__" in partes_lower
        or Path(nombre_lower).suffix in _SUFIJOS_CACHE
        or nombre_lower.endswith(".log")
    )


def _rutas_locales_en_directorio(ruta):
    hallazgos = []
    for archivo in ruta.rglob("*"):
        if not archivo.is_file():
            continue
        relativa = archivo.relative_to(ruta)
        partes = relativa.parts
        if archivo.name.lower() == "portable.txt":
            hallazgos.append((relativa, "marcador portable fuera del ZIP"))
        elif any(parte.lower() == "datos" for parte in partes):
            hallazgos.append((relativa, "datos locales del usuario"))
        elif _es_cache_o_log(partes, archivo.name):
            hallazgos.append((relativa, "caché o log"))
    return hallazgos


def _ruta_zip(nombre):
    """Normaliza también los separadores que usa Compress-Archive en Windows."""
    return PurePosixPath(nombre.replace("\\", "/"))


def _analizar_zip(ruta, errores, dist_dir=None):
    try:
        with zipfile.ZipFile(ruta) as archivo_zip:
            entradas = [
                (info, _ruta_zip(info.filename))
                for info in archivo_zip.infolist()
                if not info.is_dir() and not info.filename.endswith(("/", "\\"))
            ]
    except (OSError, zipfile.BadZipFile) as exc:
        errores.append(f"El ZIP portable no es legible: {exc}")
        return None

    nombres_lista = [str(nombre).lower() for _, nombre in entradas]
    nombres = set(nombres_lista)
    duplicados = sorted(nombre for nombre, cantidad
                        in Counter(nombres_lista).items() if cantidad > 1)
    if duplicados:
        errores.append(
            "El ZIP portable contiene rutas duplicadas: "
            + ", ".join(duplicados[:5]))
    peligrosas = [nombre for _, nombre in entradas if ".." in nombre.parts]
    if peligrosas:
        errores.append("El ZIP portable contiene rutas con '..'.")
    enlaces = [nombre for info, nombre in entradas
               if ((info.external_attr >> 16) & 0o170000) == 0o120000]
    if enlaces:
        errores.append("El ZIP portable contiene enlaces simbólicos.")
    marcadores = [nombre for _, nombre in entradas
                  if str(nombre).lower() == "imago/portable.txt"]
    if len(marcadores) != 1:
        errores.append(
            "El ZIP portable debe contener exactamente un Imago/portable.txt "
            f"(encontrados: {len(marcadores)}).")
    if "imago/imago.exe" not in nombres:
        errores.append("El ZIP portable no contiene Imago/Imago.exe.")
    fuera_de_raiz = [nombre for _, nombre in entradas
                     if not nombre.parts or nombre.parts[0].lower() != "imago"]
    if fuera_de_raiz:
        errores.append("El ZIP portable contiene archivos fuera de la carpeta Imago.")

    locales = []
    for _, nombre in entradas:
        partes = nombre.parts
        if any(parte.lower() == "datos" for parte in partes):
            locales.append((nombre, "datos locales del usuario"))
        elif _es_cache_o_log(partes, nombre.name):
            locales.append((nombre, "caché o log"))
    for nombre, motivo in locales[:10]:
        errores.append(f"El ZIP incluye {motivo}: {nombre}")
    if len(locales) > 10:
        errores.append(f"El ZIP incluye otros {len(locales) - 10} artefactos locales.")

    if dist_dir is not None and Path(dist_dir).is_dir():
        esperados = {
            "imago/" + archivo.relative_to(dist_dir).as_posix().lower():
                archivo.stat().st_size
            for archivo in Path(dist_dir).rglob("*") if archivo.is_file()
        }
        actuales = {
            str(nombre).lower(): info.file_size
            for info, nombre in entradas
            if str(nombre).lower() != "imago/portable.txt"
        }
        faltan = sorted(set(esperados) - set(actuales))
        sobran = sorted(set(actuales) - set(esperados))
        distintos = sorted(nombre for nombre in set(esperados) & set(actuales)
                            if esperados[nombre] != actuales[nombre])
        if faltan:
            errores.append(
                "El ZIP no coincide con dist: faltan " + ", ".join(faltan[:5]))
        if sobran:
            errores.append(
                "El ZIP no coincide con dist: sobran " + ", ".join(sobran[:5]))
        if distintos:
            errores.append(
                "El ZIP no coincide con dist en tamaño: "
                + ", ".join(distintos[:5]))

    return sum(info.file_size for info, _ in entradas)


def analizar_distribucion(dist_dir, instalador, portable_zip,
                          incluir_instalador=True):
    """Devuelve artefactos medidos y errores de higiene encontrados."""
    dist_dir = Path(dist_dir)
    instalador = Path(instalador)
    portable_zip = Path(portable_zip)
    artefactos = []
    errores = []

    if not dist_dir.is_dir():
        errores.append(f"No existe la distribución desplegada: {dist_dir}")
    else:
        ejecutable = dist_dir / "Imago.exe"
        if not ejecutable.is_file():
            errores.append(f"Falta el ejecutable: {ejecutable}")
        for relativa, motivo in _rutas_locales_en_directorio(dist_dir)[:10]:
            errores.append(f"La distribución incluye {motivo}: {relativa}")
        artefactos.append({
            "nombre": "Carpeta desplegada",
            "ruta": str(dist_dir),
            "bytes": _tamano_directorio(dist_dir),
            "sha256": None,
        })

    if incluir_instalador:
        if not instalador.is_file():
            errores.append(f"No existe el instalador: {instalador}")
        else:
            artefactos.append({
                "nombre": "Instalador",
                "ruta": str(instalador),
                "bytes": instalador.stat().st_size,
                "sha256": _sha256(instalador),
            })

    if not portable_zip.is_file():
        errores.append(f"No existe el ZIP portable: {portable_zip}")
    else:
        descomprimido = _analizar_zip(portable_zip, errores, dist_dir)
        artefactos.append({
            "nombre": "ZIP portable",
            "ruta": str(portable_zip),
            "bytes": portable_zip.stat().st_size,
            "bytes_descomprimidos": descomprimido,
            "sha256": _sha256(portable_zip),
        })
    return artefactos, errores


def _resolver_zip_portable(ruta_explicita):
    if ruta_explicita:
        return Path(ruta_explicita), []
    candidatos = sorted(Path.cwd().glob("Imago-*-portable.zip"))
    if len(candidatos) == 1:
        return candidatos[0], []
    if not candidatos:
        return Path("Imago-*-portable.zip"), [
            "No se encontró ningún Imago-*-portable.zip."]
    return candidatos[0], [
        "Hay varios ZIP portables; indica cuál publicar con --portable: "
        + ", ".join(str(ruta) for ruta in candidatos)]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verifica tamaños e higiene de la distribución de Imago.")
    parser.add_argument("--dist", default="dist/Imago")
    parser.add_argument("--instalador", default="installer/ImagoSetup.exe")
    parser.add_argument("--portable", help="ZIP a comprobar; se autodetecta si se omite")
    parser.add_argument("--omitir-instalador", action="store_true",
                        help="No exige instalador cuando Inno Setup no está disponible")
    args = parser.parse_args(argv)

    portable, errores_resolucion = _resolver_zip_portable(args.portable)
    artefactos, errores = analizar_distribucion(
        args.dist, args.instalador, portable,
        incluir_instalador=not args.omitir_instalador)
    errores = errores_resolucion + errores

    print("Artefactos de distribución:")
    for artefacto in artefactos:
        detalle = f"{_mib(artefacto['bytes']):.2f} MiB"
        descomprimido = artefacto.get("bytes_descomprimidos")
        if descomprimido is not None:
            detalle += f" ({_mib(descomprimido):.2f} MiB descomprimidos)"
        print(f"- {artefacto['nombre']}: {detalle} | {artefacto['ruta']}")
        if artefacto["sha256"]:
            print(f"  SHA-256: {artefacto['sha256']}")

    if errores:
        print("\nDistribución NO apta para publicar:", file=sys.stderr)
        for error in errores:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("\nDistribución apta para publicar: no contiene datos locales, cachés ni logs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
