# Imago

**Imago** es un editor de imágenes de escritorio de estilo *Paint.NET*, escrito en
**Python + PySide6 (Qt 6)**. Combina la potencia de un editor por capas con la
sencillez de las herramientas clásicas, e incluye un conjunto de funciones de
**Inteligencia Artificial que se ejecutan en local**, sin enviar tus imágenes a
la nube.

Está pensado principalmente para **Linux** (desarrollo actual en CachyOS/KDE) y
también funciona en **Windows**, donde nació el proyecto. La interfaz está
traducida a **español, inglés y francés**.

## Características principales

- Edición por **capas** con máscaras no destructivas, grupos, opacidad y modos
  de fusión.
- **Deshacer/rehacer** completo y herramientas de dibujo (pincel, lápiz, goma,
  bote, formas, texto, degradado, clonado, aerógrafo, difuminar, corrector…).
- **Selección** por rectángulo, elipse, lazo y varita mágica, con refinado.
- **Ajustes y efectos** con vista previa en vivo (niveles, curvas de exposición,
  tono/saturación, balance de color, desenfoques, enfoque, bordes…).
- **Funciones de IA locales** (modelos ONNX en CPU/GPU): eliminar fondo, borrado
  inteligente de objetos, super-resolución, colorización, reducción de ruido,
  restaurar caras, segmentación, estimación de profundidad y OCR, además de
  funciones de visión clásica (enderezar horizonte, ojos rojos, perspectiva,
  panorama).
- **Formatos**: formato nativo `.imago` (ZIP con capas), PNG/JPG/WebP/GIF, PSD
  (lectura), ORA, PDF, SVG, y `.avif`/`.heic`/`.jxl` mediante plugins de Pillow.
- **Sistema de plugins** para añadir Ajustes/Efectos de terceros.
- Tema oscuro y claro propios, ventana sin marco, paneles empotrados y
  autoguardado con recuperación.

## Requisitos e instalación

Imago necesita **Python 3** y las dependencias de [`requirements.txt`](requirements.txt).

```bash
# 1. Crear un entorno virtual (recomendado)
python -m venv .venv
# Linux/Mac:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Ejecutar
python main.py
```

`onnxruntime`, `opencv`, `pillow`, `pillow-heif`, `pillow-jxl-plugin` y
`psd-tools` se importan de forma **perezosa**: Imago arranca aunque falten, y
solo son necesarios para las funciones concretas que dependen de ellos.

## Modelos de IA

Las funciones neuronales necesitan un archivo de modelo que **se descarga una
sola vez, bajo demanda** (la primera vez que usas la función), a la carpeta de
datos del usuario. **Los modelos no se distribuyen con Imago.** Puedes revisar,
descargar y borrar cada modelo desde **IA → Gestionar modelos de IA…**, donde se
indica su tamaño y su licencia. Todos los modelos usados tienen licencias
redistribuibles (Apache-2.0, BSD-3-Clause o MIT).

## Licencia

Imago es **software libre** y se distribuye bajo los términos de la
**GNU General Public License, versión 3 (GPLv3)**. Consulta el archivo
[`LICENSE`](LICENSE) para el texto completo.

    Imago — editor de imágenes de escritorio
    Copyright (C) 2026 AVN Bramg

    Este programa es software libre: puedes redistribuirlo y/o modificarlo
    bajo los términos de la GNU General Public License publicada por la Free
    Software Foundation, ya sea la versión 3 de la Licencia o (a tu elección)
    cualquier versión posterior.

    Este programa se distribuye con la esperanza de que sea útil, pero SIN
    NINGUNA GARANTÍA; ni siquiera la garantía implícita de COMERCIABILIDAD o
    IDONEIDAD PARA UN PROPÓSITO PARTICULAR. Consulta la GNU General Public
    License para más detalles.

Los componentes de terceros (bibliotecas, iconos y modelos de IA) y sus
respectivas licencias se detallan en [`TERCEROS.md`](TERCEROS.md).
