const ISLANDS = [
  { id: "pirata", name: "Pirata", points: "105,127 112,105 129,83 151,65 176,53 201,47 225,49 245,60 263,58 284,66 307,78 331,94 353,111 374,129 393,149 407,169 404,187 391,201 371,211 347,216 323,214 300,207 277,209 253,205 231,208 209,202 187,202 166,195 146,185 128,171 113,153" },
  { id: "hielo", name: "Hielo", points: "438,111 448,87 465,64 485,43 508,27 535,14 562,7 585,6 609,14 632,28 653,47 673,70 691,92 707,115 719,137 715,156 700,173 681,186 657,196 630,202 602,205 575,202 547,196 520,190 495,181 473,168 455,151 443,132" },
  { id: "lava", name: "Lava", points: "859,47 871,24 892,8 916,0 946,0 971,7 993,23 1012,43 1028,67 1037,94 1038,120 1028,146 1011,170 990,190 967,209 942,225 914,238 885,244 856,242 828,235 802,225 778,210 756,192 738,171 722,149 715,127 722,106 738,87 758,73 780,61 805,53 830,46" },
  { id: "jungla", name: "Jungla", points: "779,305 789,280 807,258 828,241 851,228 877,218 903,215 928,218 951,226 976,233 1001,245 1025,260 1048,278 1070,297 1091,318 1109,339 1120,360 1118,380 1105,399 1086,414 1063,426 1037,433 1009,435 980,431 952,425 925,419 899,411 875,402 851,390 830,376 812,358 796,338 785,321" },
  { id: "robot", name: "Robot", points: "741,477 750,452 766,431 786,412 809,397 835,386 861,381 888,381 914,386 940,394 966,405 990,419 1014,436 1036,455 1055,477 1068,501 1076,524 1072,547 1059,568 1040,587 1017,602 989,614 960,622 930,626 900,624 871,618 843,608 817,596 793,580 773,561 757,539 746,515 740,493" },
  { id: "espacio", name: "Espacio", points: "401,493 409,468 426,445 447,426 470,410 495,397 521,389 548,386 575,390 601,399 627,412 651,428 674,447 695,468 713,491 727,515 735,538 732,560 718,582 700,601 677,617 650,632 622,642 592,647 562,646 533,641 505,632 478,620 454,604 434,585 417,563 404,540 397,516" },
  { id: "chuche", name: "Chuche", points: "56,485 66,461 82,440 101,421 123,404 147,391 173,381 199,376 224,377 248,384 272,394 296,407 319,423 341,442 362,463 382,484 397,506 406,528 405,549 393,570 375,588 352,604 325,616 295,625 264,629 233,627 204,621 175,613 147,603 121,589 98,572 79,551 64,529 55,506" },
  { id: "desierto", name: "Desierto", points: "0,277 17,258 38,246 62,238 88,235 114,237 140,242 165,249 191,257 216,268 241,281 265,296 287,311 307,328 326,344 341,360 342,375 329,387 309,396 283,402 255,403 226,400 197,397 169,392 141,388 114,383 87,376 61,367 37,356 17,341 4,323" }
];

const STORAGE_KEY = "islandMapUnlockedCount";
let unlockedCount = readProgress();
let pendingIsland = null;

const mapContainer = document.getElementById("map-container");
const maskLayer = document.getElementById("mask-layer");
const hitAreas = document.getElementById("island-hitareas");
const backdrop = document.getElementById("modal-backdrop");
const modalTitle = document.getElementById("modal-title");
const modalMessage = document.getElementById("modal-message");
const modalKicker = document.getElementById("modal-kicker");
const modalActions = document.getElementById("modal-actions");

function readProgress() {
  const saved = Number(localStorage.getItem(STORAGE_KEY));
  return Number.isInteger(saved) && saved >= 1 && saved <= ISLANDS.length ? saved : 1;
}

function saveProgress() {
  localStorage.setItem(STORAGE_KEY, String(unlockedCount));
}

function renderMap() {
  maskLayer.replaceChildren();
  hitAreas.replaceChildren();

  ISLANDS.forEach((island, index) => {
    // Every island after the unlocked frontier receives its own grayscale PNG.
    if (index >= unlockedCount) {
    const grayIsland = document.createElement("img");

    // Utilizamos el mapa original, no la máscara blanca.
    grayIsland.src = "assets/mapa_8_islas.png";

    // Aplicamos la máscara para delimitar la isla.
    grayIsland.style.webkitMaskImage =
        `url("assets/masks/mascara_${island.id}.png")`;

    grayIsland.style.maskImage =
        `url("assets/masks/mascara_${island.id}.png")`;

    grayIsland.className = "grayscale-island";
    grayIsland.alt = "";
    grayIsland.draggable = false;

    maskLayer.appendChild(grayIsland);
    }

    const area = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    area.setAttribute("points", island.points);
    area.setAttribute("tabindex", "0");
    area.setAttribute("role", "button");
    area.setAttribute("aria-label", `Isla ${island.name}${index < unlockedCount ? ", desbloqueada" : ", bloqueada"}`);
    area.addEventListener("click", () => selectIsland(index));
    area.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectIsland(index);
      }
    });
    area.addEventListener("mouseenter", () => {
      showIslandHighlight(island.id);
    });

    area.addEventListener("mouseleave", hideIslandHighlight);

    area.addEventListener("focus", () => {
      showIslandHighlight(island.id);
    });

    area.addEventListener("blur", hideIslandHighlight);
      hitAreas.appendChild(area);
    });
}
let selectionHighlight = null;

function showIslandHighlight(islandId) {

    if (!selectionHighlight) {
        selectionHighlight = document.createElement("div");

        selectionHighlight.className = "selection-highlight";

        mapContainer.appendChild(selectionHighlight);
    }

    selectionHighlight.style.webkitMaskImage =
        `url("assets/masks/mascara_${islandId}.png")`;

    selectionHighlight.style.maskImage =
        `url("assets/masks/mascara_${islandId}.png")`;
}

function hideIslandHighlight() {

    if (selectionHighlight) {
        selectionHighlight.remove();
        selectionHighlight = null;
    }
}


function selectIsland(index) {
  const island = ISLANDS[index];

  if (index < unlockedCount) {
    showModal(
      `Isla ${island.name}`,
      "Esta isla está desbloqueada. La pantalla de niveles de la isla se añadirá cuando definamos esa segunda pantalla.",
      [{ label: "Volver al mapa", style: "primary", action: closeModal }]
    );
    return;
  }

  // The next island in clockwise progression is the only locked island that can be attempted.
  if (index === unlockedCount) {
    pendingIsland = index;
    showModal(
      "¡Una nueva isla te espera!",
      "Este es el siguiente nivel. ¿Estás seguro de que lo quieres probar?",
      [
        { label: "Sí", style: "primary", action: startUnlockChallenge },
        { label: "No", style: "secondary", action: closeModal }
      ]
    );
  } else {
    showLockedMessage();
  }
}

function startUnlockChallenge() {
  const island = ISLANDS[pendingIsland];
  showModal(
    `Prueba para desbloquear ${island.name}`,
    "Esta es una pantalla provisional para probar el flujo. Cuando definamos el nivel de desbloqueo, sustituiremos estos botones por el ejercicio real.",
    [
      { label: "Simular que lo supera", style: "success", action: passChallenge },
      { label: "Simular que falla", style: "warning", action: failChallenge }
    ]
  );
}

function passChallenge() {
  const island = ISLANDS[pendingIsland];
  unlockedCount = Math.max(unlockedCount, pendingIsland + 1);
  saveProgress();
  renderMap();
  pendingIsland = null;
  showModal(
    "¡Isla desbloqueada!",
    `¡Enhorabuena! La isla ${island.name} ya está disponible.`,
    [{ label: "Volver al mapa", style: "primary", action: closeModal }]
  );
}

function failChallenge() {
  pendingIsland = null;
  showLockedMessage();
}

function showLockedMessage() {
  showModal(
    "Sigue practicando",
    "No puedes acceder aún a esta isla. ¡Sigue practicando!",
    [{ label: "Volver al mapa", style: "primary", action: closeModal }]
  );
}

function showModal(title, message, actions) {
  modalTitle.textContent = title;
  modalMessage.textContent = message;
  modalKicker.textContent = "AVENTURA MATEMÁTICA";
  modalActions.replaceChildren();

  actions.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `action-button action-${item.style}`;
    button.textContent = item.label;
    button.addEventListener("click", item.action);
    modalActions.appendChild(button);
  });

  backdrop.classList.remove("hidden");
  const firstButton = modalActions.querySelector("button");
  if (firstButton) firstButton.focus();
}

function closeModal() {
  backdrop.classList.add("hidden");
  pendingIsland = null;
}

document.getElementById("modal-close").addEventListener("click", closeModal);
backdrop.addEventListener("click", (event) => {
  if (event.target === backdrop) closeModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !backdrop.classList.contains("hidden")) closeModal();
});

document.getElementById("reset-progress").addEventListener("click", () => {
  unlockedCount = 1;
  saveProgress();
  renderMap();
  closeModal();
});

renderMap();
