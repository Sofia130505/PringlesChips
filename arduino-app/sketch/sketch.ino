// Matriz LED 8x13 de la Arduino UNO Q.
//
// Copia el patrón oficial de app-bricks-examples
// (core-and-foundational/02-led-matrix/02-led-matrix-frame):
//   - el frame son 104 bytes (8 filas x 13 columnas), un byte por LED,
//     con brillo de 0 a 7 porque `setGrayscaleBits(3)`;
//   - Python llama a `draw` con `Bridge.call("draw", frame_bytes)`;
//   - el `loop()` repinta el frame cada 10 ms, así que `draw` solo copia.

#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <vector>

Arduino_LED_Matrix matrix;

const uint8_t FRAME_ROWS = 8;                         // filas
const uint8_t FRAME_COLS = 13;                        // columnas
const uint8_t FRAME_SIZE = FRAME_ROWS * FRAME_COLS;   // 104 píxeles

uint8_t frame[FRAME_SIZE] = {0};                      // frame actual, apagado al arrancar

void draw(std::vector<uint8_t> newFrame);             // lo llama Python por el Bridge

void setup() {
    matrix.begin();
    matrix.setGrayscaleBits(3);                       // brillos de 0 a 7
    matrix.clear();
    Bridge.begin();
    Bridge.provide("draw", draw);
}

void loop() {
    matrix.draw(frame);
    delay(10);
}

// Python manda una figura nueva; aquí solo se copia en el frame global.
void draw(std::vector<uint8_t> newFrame) {
    size_t len = min(newFrame.size(), (size_t)FRAME_SIZE);
    memcpy(frame, newFrame.data(), len);
}
