"""Las figuras que se dibujan en la matriz LED (8 filas x 13 columnas).

Cada figura es arte ASCII: ``#`` es un LED encendido y ``.`` uno apagado.
El brillo va de 0 a 7, el máximo que permite ``matrix.setGrayscaleBits(3)`` en
``sketch/sketch.ino``.

Este módulo es solo librería estándar **a propósito**, para poder probarlo en el
portátil sin la placa:

    python3 arduino-app/python/figuras.py
"""
ROWS = 8
COLS = 13
BRIGHTNESS = 7

ESTRELLA = (
    "......#......",
    ".....###.....",
    ".....###.....",
    "#############",
    ".###########.",
    "..#########..",
    "..##.###.##..",
    ".##.......##.",
)

CORAZON = (
    "..##.....##..",
    ".####...####.",
    "#############",
    "#############",
    ".###########.",
    "..#########..",
    "...#######...",
    "....#####....",
)

APAGADO = tuple("." * COLS for _ in range(ROWS))

FIGURAS = {"estrella": ESTRELLA, "corazon": CORAZON, "apagar": APAGADO}


def figura(nombre):
    """Matriz de 8x13 con brillos 0..7, lista para `numpy.array(..., uint8)`."""
    try:
        arte = FIGURAS[nombre]
    except KeyError:
        raise ValueError("figura desconocida: {!r} (usa {})".format(
            nombre, ", ".join(sorted(FIGURAS))))
    return [[BRIGHTNESS if char == "#" else 0 for char in row] for row in arte]


def preview(nombre):
    """La figura en texto, para verla en la consola."""
    return "\n".join("".join("#" if value else "." for value in row) for row in figura(nombre))


def _validar():
    for nombre, arte in FIGURAS.items():
        if len(arte) != ROWS or any(len(row) != COLS for row in arte):
            raise ValueError("la figura {} no mide {}x{}".format(nombre, ROWS, COLS))


_validar()


if __name__ == "__main__":
    for _nombre in ("estrella", "corazon"):
        print("== {} ==".format(_nombre))
        print(preview(_nombre))
        print()
