"""Transporte de arrays NumPy grandes entre los procesos de IA.

``multiprocessing.connection`` serializa sus mensajes con pickle. Para una foto
de decenas de MiB eso crea otro bloque igual de grande en RAM y despues lo copia
al socket local. Este modulo sustituye solo los arrays grandes por descriptores
de archivos ``.npy`` mapeables dentro de un directorio temporal privado del
trabajo. Los escalares y objetos pequenos siguen viajando normalmente.

El formato ``.npy`` conserva forma, dtype y endian, funciona igual en
Windows/Linux y se abre con ``allow_pickle=False``. Nunca se acepta una ruta
absoluta ni un nombre que escape del directorio autorizado.
"""

import os
import uuid


MMAP_MIN_BYTES = 256 * 1024
_ARRAY_TAG = "__imago_mmap_array_v1__"


class IPCArrayCancelled(Exception):
    """Se cancelo el trabajo mientras se copiaba un array al transporte."""


def _array_path(directory, filename):
    """Resuelve un nombre simple y rechaza cualquier escape del directorio."""
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        raise ValueError("Descriptor IPC de array no valido")
    root = os.path.realpath(os.path.abspath(directory))
    path = os.path.realpath(os.path.abspath(os.path.join(root, filename)))
    if os.path.commonpath((root, path)) != root:
        raise ValueError("Descriptor IPC fuera del directorio autorizado")
    return path


def _is_descriptor(value):
    return (isinstance(value, tuple) and len(value) == 2
            and value[0] == _ARRAY_TAG and isinstance(value[1], str))


def _write_array(array, directory, prefix, is_cancelled=None):
    import numpy as np
    from numpy.lib.format import open_memmap

    filename = "%s_%s.npy" % (prefix, uuid.uuid4().hex)
    path = _array_path(directory, filename)
    mapped = open_memmap(path, mode="w+", dtype=array.dtype,
                         shape=array.shape, fortran_order=False)
    mmap_obj = getattr(mapped, "_mmap", None)
    try:
        if array.ndim == 0:
            if is_cancelled is not None and is_cancelled():
                raise IPCArrayCancelled()
            mapped[...] = array
        else:
            # Copias de unos 16 MiB: acotan la latencia de Cancelar incluso con
            # panoramas o lotes mucho mayores que una foto habitual.
            bytes_slice = max(1, int(array[0:1].nbytes))
            step = max(1, (16 * 1024 * 1024) // bytes_slice)
            for start in range(0, array.shape[0], step):
                if is_cancelled is not None and is_cancelled():
                    raise IPCArrayCancelled()
                mapped[start:start + step] = array[start:start + step]
        mapped.flush()
    finally:
        del mapped
        if mmap_obj is not None:
            mmap_obj.close()
    return (_ARRAY_TAG, filename)


def pack_arrays(value, directory, prefix="array", is_cancelled=None):
    """Reemplaza recursivamente arrays grandes por descriptores ``.npy``.

    Los arrays con objetos no se mapean: ``allow_pickle=False`` es una frontera
    deliberada de seguridad. Los arrays pequenos conservan el camino pickle,
    cuyo coste es menor que crear un archivo y mapearlo.
    """
    import numpy as np

    if (isinstance(value, np.ndarray) and value.nbytes >= MMAP_MIN_BYTES
            and not value.dtype.hasobject):
        return _write_array(value, directory, prefix, is_cancelled)
    if isinstance(value, tuple):
        return tuple(pack_arrays(item, directory, prefix, is_cancelled)
                     for item in value)
    if isinstance(value, list):
        return [pack_arrays(item, directory, prefix, is_cancelled)
                for item in value]
    if isinstance(value, dict):
        return {key: pack_arrays(item, directory, prefix, is_cancelled)
                for key, item in value.items()}
    return value


def _read_array(directory, filename, copy_array, is_cancelled=None):
    import numpy as np

    path = _array_path(directory, filename)
    mapped = np.load(path, mmap_mode="r" if copy_array else "c",
                     allow_pickle=False)
    if not copy_array:
        return mapped
    mmap_obj = getattr(mapped, "_mmap", None)
    try:
        result = np.empty(mapped.shape, dtype=mapped.dtype, order="C")
        if mapped.ndim == 0:
            if is_cancelled is not None and is_cancelled():
                raise IPCArrayCancelled()
            result[...] = mapped
        else:
            bytes_slice = max(1, int(mapped[0:1].nbytes))
            step = max(1, (16 * 1024 * 1024) // bytes_slice)
            for start in range(0, mapped.shape[0], step):
                if is_cancelled is not None and is_cancelled():
                    raise IPCArrayCancelled()
                result[start:start + step] = mapped[start:start + step]
        return result
    finally:
        del mapped
        if mmap_obj is not None:
            mmap_obj.close()


def unpack_arrays(value, directory, copy_arrays=False, is_cancelled=None):
    """Reconstruye recursivamente los descriptores creados por ``pack_arrays``.

    En el hijo, ``copy_arrays=False`` entrega ``memmap`` de copia-en-escritura:
    una funcion puede modificarlo sin alterar el archivo de entrada. En el
    principal, ``copy_arrays=True`` desliga el resultado antes de borrar el
    directorio temporal y terminar el proceso.
    """
    if _is_descriptor(value):
        return _read_array(directory, value[1], copy_arrays, is_cancelled)
    if isinstance(value, tuple):
        return tuple(unpack_arrays(item, directory, copy_arrays, is_cancelled)
                     for item in value)
    if isinstance(value, list):
        return [unpack_arrays(item, directory, copy_arrays, is_cancelled)
                for item in value]
    if isinstance(value, dict):
        return {key: unpack_arrays(item, directory, copy_arrays, is_cancelled)
                for key, item in value.items()}
    return value
