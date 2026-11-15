/* Estrella al elegir una isla · corazón al superar un nivel.
 *
 * Este archivo NO modifica app.js: se engancha a dos de sus funciones
 * globales (`selectIsland` y `saveCompletedLevel`) y avisa a la placa.
 * Solo vive en la copia que sirve la app de App Lab (puerto 7000), no en
 * apps/frontend: la genera `scripts/sync_assets.py`.
 */
(function () {
  "use strict";

  var API = "/api/led";

  function avisar(figura) {
    // Si la placa no está (por ejemplo, abriendo la web con otro servidor),
    // la petición falla y no pasa nada: la página sigue funcionando igual.
    fetch(API + "/" + figura).catch(function () {});
  }

  function enganchar(nombre, despues) {
    var original = window[nombre];
    if (typeof original !== "function") {
      console.warn("led.js: no encuentro " + nombre + "() en app.js; la matriz no reaccionará");
      return;
    }
    window[nombre] = function () {
      var resultado = original.apply(this, arguments);
      try {
        despues.apply(this, arguments);
      } catch (error) {
        console.warn("led.js: fallo al dibujar en la matriz", error);
      }
      return resultado;
    };
  }

  // Estrella al entrar en una isla desbloqueada. Si está bloqueada, app.js ya
  // muestra su propio aviso y no se enciende nada.
  enganchar("selectIsland", function (index) {
    var desbloqueada;
    try {
      desbloqueada = index < unlockedCount;   // `unlockedCount` vive en app.js
    } catch (error) {
      desbloqueada = true;                    // si app.js cambia, no filtramos
    }
    if (desbloqueada) avisar("estrella");
  });

  // Corazón cuando app.js marca un nivel como superado.
  enganchar("saveCompletedLevel", function () {
    avisar("corazon");
  });
})();
