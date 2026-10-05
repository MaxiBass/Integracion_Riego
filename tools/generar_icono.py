"""Genera el icono de «Riego por Balance Hídrico»: una gota con un brote.

Uso (desde la raíz del repo):

    /tmp/hav/bin/python tools/generar_icono.py

Escribe custom_components/riego/brand/icon.png (256×256) e icon@2x.png
(512×512), que es donde Home Assistant busca el icono de una integración
propia. Necesita Pillow; el venv de pruebas de HA (ver CLAUDE.md) ya lo trae.

Se dibuja a 2048 px y se reduce con LANCZOS para que los bordes salgan suaves
sin depender de ninguna librería de SVG. Las coordenadas del diseño están en
un espacio de 100 unidades de alto, de modo que se puede retocar la forma
sin pensar en píxeles.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

LIENZO = 2048
RELLENO = 0.92  # fracción del alto del lienzo que ocupa la gota

# Azul de agua, de más claro arriba a más profundo abajo.
AZUL_ARRIBA = (96, 205, 252)
AZUL_ABAJO = (13, 92, 186)
BLANCO = (255, 255, 255)

# ── Geometría de la gota, en unidades de diseño ──────────────────────────
CENTRO = (50.0, 64.0)  # centro del bulbo
RADIO = 37.0
PUNTA = (50.0, 2.0)


def _bezier(p0, p1, p2, p3, pasos=240):
    puntos = []
    for i in range(pasos + 1):
        t = i / pasos
        m = 1 - t
        puntos.append(
            (
                m**3 * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] + t**3 * p3[0],
                m**3 * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return puntos


def contorno_gota():
    """Punta afilada, flancos suaves y bulbo circular, con tangente continua."""
    cx, cy = CENTRO
    derecho = _bezier(PUNTA, (58, 20), (cx + RADIO, 40), (cx + RADIO, cy))
    # Semicircunferencia inferior, de derecha a izquierda pasando por abajo.
    arco = [
        (cx + RADIO * math.cos(math.radians(a)), cy + RADIO * math.sin(math.radians(a)))
        for a in [i * 180 / 240 for i in range(241)]
    ]
    izquierdo = [(2 * cx - x, y) for x, y in reversed(derecho)]
    return derecho + arco[1:] + izquierdo[1:]


def _hoja(base, punta, ancho):
    """Hoja con la panza cerca de la base y la punta afilada.

    Una lente simétrica (dos arcos) da una punta de ~90° y queda como una
    banderita; con curvas cúbicas se puede cargar la anchura hacia la base.
    """
    dx, dy = punta[0] - base[0], punta[1] - base[1]
    largo = math.hypot(dx, dy)
    ux, uy = dx / largo, dy / largo
    nx, ny = -uy, ux

    def lado(signo):
        c1 = (base[0] + ux * 0.18 * largo + nx * signo * ancho * 1.15,
              base[1] + uy * 0.18 * largo + ny * signo * ancho * 1.15)
        c2 = (base[0] + ux * 0.62 * largo + nx * signo * ancho * 0.45,
              base[1] + uy * 0.62 * largo + ny * signo * ancho * 0.45)
        return _bezier(base, c1, c2, punta, pasos=120)

    return lado(1) + list(reversed(lado(-1)))


def _tallo(p0, p1, p2, pasos=60):
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
        )
        for t in [i / pasos for i in range(pasos + 1)]
    ]


def dibujar() -> Image.Image:
    puntos = contorno_gota()
    ys = [y for _, y in puntos]
    xs = [x for x, _ in puntos]
    escala = RELLENO * LIENZO / (max(ys) - min(ys))
    ox = (LIENZO - (max(xs) - min(xs)) * escala) / 2 - min(xs) * escala
    oy = (LIENZO - (max(ys) - min(ys)) * escala) / 2 - min(ys) * escala

    def px(p):
        return (p[0] * escala + ox, p[1] * escala + oy)

    # Máscara de la gota
    mascara = Image.new("L", (LIENZO, LIENZO), 0)
    ImageDraw.Draw(mascara).polygon([px(p) for p in puntos], fill=255)

    # Degradado vertical recortado por la máscara
    y0, y1 = min(ys) * escala + oy, max(ys) * escala + oy
    degradado = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    d = ImageDraw.Draw(degradado)
    for fila in range(LIENZO):
        t = min(max((fila - y0) / (y1 - y0), 0.0), 1.0)
        color = tuple(round(a + (b - a) * t) for a, b in zip(AZUL_ARRIBA, AZUL_ABAJO))
        d.line([(0, fila), (LIENZO, fila)], fill=color + (255,))
    # La máscara va como canal alfa. Con paste(imagen, máscara) el color se
    # mezclaría además con el fondo transparente (negro), lo que oscurecería
    # el borde si la máscara tuviera bordes suaves.
    gota = degradado.copy()
    gota.putalpha(mascara)

    # Brillo: un arco claro siguiendo el borde inferior izquierdo del bulbo
    brillo = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    bd = ImageDraw.Draw(brillo)
    cx, cy = px(CENTRO)
    r = (RADIO - 7.5) * escala
    ancho = round(4.4 * escala)
    bd.arc([cx - r, cy - r, cx + r, cy + r], start=122, end=172, fill=BLANCO + (84,), width=ancho)
    for ang in (122, 172):  # extremos redondeados
        ex = cx + (r - ancho / 2) * math.cos(math.radians(ang))
        ey = cy + (r - ancho / 2) * math.sin(math.radians(ang))
        bd.ellipse([ex - ancho / 2, ey - ancho / 2, ex + ancho / 2, ey + ancho / 2], fill=BLANCO + (84,))
    # El brillo solo se pinta dentro de la gota: se multiplica su alfa por la máscara.
    brillo.putalpha(ImageChops.multiply(brillo.getchannel("A"), mascara))
    gota = Image.alpha_composite(gota, brillo)

    # Brote blanco: tallo y dos hojas
    brote = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    bd = ImageDraw.Draw(brote)
    grosor = round(3.6 * escala)
    # El trazo grueso de line() deja muescas en el borde; sellar círculos a lo
    # largo del camino da un ancho constante y un borde liso.
    for x, y in (px(p) for p in _tallo((50, 88), (48.6, 76), (50, 66), pasos=240)):
        bd.ellipse([x - grosor / 2, y - grosor / 2, x + grosor / 2, y + grosor / 2], fill=BLANCO + (255,))
    bd.polygon([px(p) for p in _hoja((49.6, 75), (33, 54.5), 9.0)], fill=BLANCO + (255,))
    bd.polygon([px(p) for p in _hoja((50.4, 68), (67.5, 43.5), 9.6)], fill=BLANCO + (255,))
    return Image.alpha_composite(gota, brote)


def main() -> None:
    raiz = Path(__file__).resolve().parent.parent
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else raiz / "custom_components" / "riego" / "brand"
    destino.mkdir(parents=True, exist_ok=True)

    grande = dibujar()
    for nombre, lado in (("icon.png", 256), ("icon@2x.png", 512)):
        grande.resize((lado, lado), Image.LANCZOS).save(destino / nombre, optimize=True)
        print(f"{destino / nombre}  {lado}×{lado}")


if __name__ == "__main__":
    main()
