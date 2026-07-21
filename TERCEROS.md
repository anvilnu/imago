# Avisos de terceros (Third-Party Notices)

Imago se distribuye bajo la **GPLv3** (ver [`LICENSE`](LICENSE)). Este documento
recopila los componentes de terceros que Imago utiliza y sus licencias, todas
compatibles con la GPLv3.

---

## 1. Bibliotecas de Python

Estas bibliotecas **no forman parte del código fuente de Imago**: se instalan
por separado con `pip install -r requirements.txt`. Se listan aquí a título
informativo y para el empaquetado de binarios.

| Biblioteca | Licencia | Uso en Imago |
|---|---|---|
| **PySide6 / Qt 6** (`PySide6`, `PySide6_Addons`, `PySide6_Essentials`, `shiboken6`) | **LGPLv3** | Toda la interfaz gráfica |
| NumPy | BSD-3-Clause | Operaciones de píxeles vectorizadas |
| SciPy | BSD-3-Clause | Utilidades numéricas |
| ONNX Runtime (`onnxruntime`, `onnxruntime-directml`) | MIT | Motor de inferencia de los modelos de IA |
| OpenCV (`opencv-python-headless`) | Apache-2.0 | Funciones de visión clásica |
| Pillow | HPND (tipo MIT) | Conservar metadatos EXIF de JPEG |
| pillow-heif | Apache-2.0 (+ códecs, ver nota) | Abrir/guardar `.heic`/`.heif` |
| pillow-jxl-plugin | BSD-3-Clause (libjxl) | Abrir/guardar `.jxl` |
| psd-tools | MIT | Importar archivos `.psd`/`.psb` |

### Nota sobre Qt / PySide6 (LGPLv3)

Qt y PySide6 se usan bajo la **LGPLv3**, que es compatible con una aplicación
GPLv3. Si distribuyes **binarios** de Imago (instalador o versión portable), la
LGPL exige que el usuario pueda **sustituir o re-enlazar** las bibliotecas Qt.
El empaquetado de Imago con PyInstaller en modo *one-folder* (carpeta
`_internal` con las bibliotecas Qt como archivos separados) cumple este
requisito de forma natural.

### Nota sobre pillow-heif (códecs HEVC)

`pillow-heif` incluye códecs para el formato HEIC/HEIF (libheif y bibliotecas
HEVC asociadas). El código es libre, pero el estándar **HEVC está sujeto a
patentes** cuya situación varía según el país. Es una cuestión de patentes, no
de licencia de copyright, y afecta por igual a cualquier software que abra HEIC.
La apertura de `.heic` en Imago es opcional (import perezoso).

---

## 2. Modelos de Inteligencia Artificial

Los modelos ONNX **no se distribuyen con Imago**: se descargan bajo demanda a la
carpeta de datos del usuario la primera vez que se usa cada función, y pueden
borrarse en cualquier momento. Cada uno conserva su propia licencia (todas
redistribuibles). El gestor de modelos (**IA → Gestionar modelos de IA…**)
muestra la licencia de cada uno.

| Modelo | Función | Licencia |
|---|---|---|
| ISNet (uso general), U2Net | Eliminar fondo | Apache-2.0 |
| LaMa | Borrado inteligente de objetos (inpainting) | Apache-2.0 |
| Real-ESRGAN (x4) | Super-resolución | BSD-3-Clause |
| DDColor | Colorización | Apache-2.0 |
| SCUNet | Reducción de ruido | Apache-2.0 |
| YuNet + GFPGAN v1.4 | Detección y restauración de caras | Apache-2.0 |
| DeepLabV3+ MobileNetV2 | Segmentación semántica | Apache-2.0 |
| MiDaS v21 small | Estimación de profundidad | MIT |
| PP-OCR (detección + reconocimiento latino) | OCR | Apache-2.0 |

---

## 3. Iconos

La mayoría de los iconos de Imago son **creación propia del proyecto** (algunos
generados con asistencia de herramientas de IA) y se distribuyen bajo la GPLv3
junto con el resto del proyecto.

Una parte de los iconos proviene de dos conjuntos de terceros con licencia
permisiva:

- **Tabler Icons** — https://tabler.io/icons — Licencia MIT
- **Lucide** — https://lucide.dev/icons — Licencia ISC
  (basado en Feather Icons)

Los textos completos de ambas licencias se reproducen a continuación, tal como
exigen la MIT y la ISC.

### Tabler Icons — Licencia MIT

```
MIT License

Copyright (c) 2020-2024 Paweł Kuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Lucide — Licencia ISC

```
ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part
of Feather (MIT). All other copyright (c) for Lucide are held by Lucide
Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
```
