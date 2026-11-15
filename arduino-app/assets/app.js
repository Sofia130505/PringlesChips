// Orden oficial de las islas: se reutiliza en el mapa y en la pantalla Canguro.
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
const ACCESSORY_CSV = "posiciones_accesorios.csv";
const LEVELS_STORAGE_KEY = "islandCompletedLevels";
let currentIslandIndex = 0;
let pendingLevel = null;
let returnScreenId = "map-screen";
const ACCESSORY_TYPES = [
  { id: "cabeza", label: "Cabeza" },
  { id: "torso", label: "Torso" },
  { id: "mano", label: "Mano" },
  { id: "cola", label: "Cola" },
  { id: "pies", label: "Pies" }
];
let unlockedCount = readProgress();
let pendingIsland = null;
let accessoryRows = [];
const equipped = new Map();

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
function saveProgress() { localStorage.setItem(STORAGE_KEY, String(unlockedCount)); }

function renderMap() {
  maskLayer.replaceChildren();
  hitAreas.replaceChildren();
  ISLANDS.forEach((island, index) => {
    if (index >= unlockedCount) {
      const grayIsland = document.createElement("img");
      grayIsland.src = "assets/mapa_8_islas.png";
      grayIsland.style.webkitMaskImage = `url("assets/masks/mascara_${island.id}.png")`;
      grayIsland.style.maskImage = `url("assets/masks/mascara_${island.id}.png")`;
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
    area.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectIsland(index); }
    });
    area.addEventListener("mouseenter", () => showIslandHighlight(island.id));
    area.addEventListener("mouseleave", hideIslandHighlight);
    area.addEventListener("focus", () => showIslandHighlight(island.id));
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
  selectionHighlight.style.webkitMaskImage = `url("assets/masks/mascara_${islandId}.png")`;
  selectionHighlight.style.maskImage = `url("assets/masks/mascara_${islandId}.png")`;
}
function hideIslandHighlight() {
  if (selectionHighlight) { selectionHighlight.remove(); selectionHighlight = null; }
}


function selectIsland(index) {
  if (index >= unlockedCount) { showLockedMessage(); return; }
  currentIslandIndex = index;
  renderIslandScreen();
  showScreen("island-screen");
}
function showLockedMessage() {
  const next = ISLANDS[unlockedCount]?.name || "la siguiente isla";
  showModal("Isla bloqueada", `Completa al menos cuatro niveles de la isla anterior para desbloquear ${next}.`,
    [{ label: "Volver al mapa", style: "primary", action: closeModal }]);
}
function completedLevels(islandId) {
  const saved = JSON.parse(localStorage.getItem(LEVELS_STORAGE_KEY) || "{}");
  return Array.isArray(saved[islandId]) ? saved[islandId] : [];
}
function saveCompletedLevel(islandId, level) {
  const saved = JSON.parse(localStorage.getItem(LEVELS_STORAGE_KEY) || "{}");
  const levels = Array.isArray(saved[islandId]) ? saved[islandId] : [];
  if (!levels.includes(level)) levels.push(level);
  saved[islandId] = levels;
  localStorage.setItem(LEVELS_STORAGE_KEY, JSON.stringify(saved));
  // Cada isla se desbloquea al completar cuatro niveles de la isla anterior.
  const index = ISLANDS.findIndex(item => item.id === islandId);
  if (index >= 0 && levels.length >= 4 && index + 1 < ISLANDS.length) {
    unlockedCount = Math.max(unlockedCount, index + 2);
    saveProgress();
  }
}
function renderIslandScreen() {
  const island = ISLANDS[currentIslandIndex];
  if (!island) return;
  document.getElementById("island-heading").textContent = `Isla ${island.name}`;
  const art = document.getElementById("island-art");
  art.replaceChildren();
  const image = document.createElement("img");
  image.className = "island-large-image";
  image.src = "assets/mapa_8_islas.png";
  image.alt = `Isla ${island.name}`;
  image.style.webkitMaskImage = `url("assets/masks/mascara_${island.id}.png")`;
  image.style.maskImage = `url("assets/masks/mascara_${island.id}.png")`;
  const bounds = getIslandBounds(island.points);
  image.style.transformOrigin = `${((bounds.cx / 1122) * 100)}% ${((bounds.cy / 676) * 100)}%`;
  image.style.setProperty("--island-zoom", String(Math.max(2.15, Math.min(3.1, 720 / Math.max(bounds.width, bounds.height)))));
  art.appendChild(image);
  const levels = document.getElementById("island-levels");
  levels.replaceChildren();
  const completed = completedLevels(island.id);
  for (let level = 1; level <= 5; level++) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `level-circle${completed.includes(level) ? " level-completed" : ""}`;
    button.textContent = String(level);
    button.setAttribute("aria-label", `Nivel ${level}${completed.includes(level) ? ", completado" : ", sin completar"}`);
    button.addEventListener("click", () => openLevelTest(level));
    levels.appendChild(button);
  }
}
function getIslandBounds(points) {
  const coords = points.split(" ").map(pair => pair.split(",").map(Number));
  const xs = coords.map(p => p[0]), ys = coords.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, width: maxX-minX, height: maxY-minY };
}
function openLevelTest(level) {
  pendingLevel = level;
  const island = ISLANDS[currentIslandIndex];
  showModal(`Nivel ${level}`, `Prueba provisional del nivel ${level} de la isla ${island.name}.`,
    [{ label: "Éxito", style: "success", action: () => finishLevel(true) },
     { label: "Fracaso", style: "warning", action: () => finishLevel(false) }]);
}
function finishLevel(success) {
  const level = pendingLevel;
  pendingLevel = null;
  closeModal();
  if (success) {
    saveCompletedLevel(ISLANDS[currentIslandIndex].id, level);
    renderIslandScreen();
    renderMap();
    renderAccessoryRows();
    showModal("¡Nivel completado!", `Has completado el nivel ${level}.`,
      [{ label: "Continuar", style: "primary", action: closeModal }]);
  } else {
    showModal("Nivel no completado", "Puedes volver a intentarlo cuando quieras.",
      [{ label: "Continuar", style: "primary", action: closeModal }]);
  }
}
function showModal(title, message, actions) {
  modalTitle.textContent = title; modalMessage.textContent = message; modalKicker.textContent = "AVENTURA MATEMÁTICA";
  modalActions.replaceChildren();
  actions.forEach(item => {
    const button = document.createElement("button");
    button.type = "button"; button.className = `action-button action-${item.style}`;
    button.textContent = item.label; button.addEventListener("click", item.action); modalActions.appendChild(button);
  });
  backdrop.classList.remove("hidden");
  modalActions.querySelector("button")?.focus();
}
function closeModal() { backdrop.classList.add("hidden"); pendingIsland = null; }

function showScreen(screenId) {
  document.querySelectorAll(".screen").forEach(screen => screen.classList.toggle("screen-active", screen.id === screenId));
  window.scrollTo({ top: 0, behavior: "instant" });
}
function openKangarooScreen() {
  returnScreenId = document.querySelector(".screen-active")?.id || "map-screen";
  renderAccessoryRows();
  showScreen("kangaroo-screen");
}
function openPreviousScreen() { showScreen(returnScreenId); }
function openMapScreen() { showScreen("map-screen"); }

function parseCSVLine(line) {
  // Los valores de este CSV no contienen comas entrecomilladas.
  return line.split(",").map(value => value.trim());
}
async function loadAccessoryCSV() {
  const response = await fetch(ACCESSORY_CSV);
  if (!response.ok) throw new Error(`No se pudo cargar ${ACCESSORY_CSV}`);
  const lines = (await response.text()).replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const headers = parseCSVLine(lines.shift());
  return lines.filter(Boolean).map(line => {
    const values = parseCSVLine(line);
    const item = Object.fromEntries(headers.map((header, i) => [header, values[i]]));
    return {
      island: item.accesorio,
      type: item.tipo_accesorio,
      file: item.archivo,
      x: Number(item.x), y: Number(item.y), width: Number(item.width),
      rotation: Number(item.rotation), zIndex: Number(item.z_index)
    };
  });
}
function accessoryImagePath(item) { return `assets/accesories/${item.file}`; }

function renderAccessoryRows() {
  const root = document.getElementById("accessory-rows");
  root.replaceChildren();
  ACCESSORY_TYPES.forEach(type => {
    const panel = document.createElement("section");
    panel.className = "accessory-row";
    const heading = document.createElement("h2");
    heading.className = "accessory-row-title";
    heading.textContent = type.label;
    const items = document.createElement("div");
    items.className = "accessory-items";
    ISLANDS.forEach((island, islandIndex) => {
      const accessory = accessoryRows.find(row => row.island === island.id && row.type === type.id);
      const isLocked = islandIndex >= unlockedCount;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `accessory-option${isLocked ? " accessory-locked" : ""}`;
      button.dataset.island = island.id;
      button.setAttribute("aria-label", `${type.label}: ${island.name}${isLocked ? ", bloqueado" : ", desbloqueado"}`);
      if (!accessory) {
        button.disabled = true;
        button.classList.add("accessory-missing");
        items.appendChild(button);
        return;
      }
      const img = document.createElement("img");
      img.src = accessoryImagePath(accessory);
      img.alt = `${island.name} ${type.label.toLowerCase()}`;
      // Aplicar el estado también directamente a la imagen para evitar
      // depender únicamente de la cascada CSS del botón.
      if (isLocked) img.classList.add("accessory-image-locked");
      img.onerror = () => {
        button.classList.add("asset-missing");
        img.alt = "Imagen pendiente";
      };
      button.appendChild(img);
      if (isLocked) {
        button.disabled = true;
        button.title = `Desbloquea la isla ${island.name} para conseguir este accesorio`;
      } else {
        button.addEventListener("click", () => equipAccessory(accessory, button));
      }
      items.appendChild(button);
    });
    panel.append(heading, items);
    root.appendChild(panel);
  });
}
function equipAccessory(item, button) {
  equipped.set(item.type, item);
  document.querySelectorAll(`.accessory-option[data-island]`).forEach(option => {
    if (option.closest(".accessory-row") === button.closest(".accessory-row")) option.classList.toggle("selected", option === button);
  });
  renderKangarooOutfit();
}
function renderKangarooOutfit() {
  const layer = document.getElementById("outfit-layer");
  layer.replaceChildren();
  [...equipped.values()].forEach(item => {
    const img = document.createElement("img");
    img.src = accessoryImagePath(item);
    img.alt = "";
    img.className = `worn-accessory worn-${item.type}`;
    img.style.left = `${(item.x / 1065) * 100}%`;
    img.style.top = `${(item.y / 970) * 100}%`;
    img.style.width = `${(item.width / 1065) * 100}%`;
    img.style.transform = `rotate(${item.rotation}deg)`;
    img.style.zIndex = String(item.zIndex);
    layer.appendChild(img);
  });
}
async function initKangarooScreen() {
  try {
    accessoryRows = await loadAccessoryCSV();
    renderAccessoryRows();
    renderKangarooOutfit();
  } catch (error) {
    document.getElementById("accessory-rows").textContent = `Error cargando accesorios: ${error.message}`;
    console.error(error);
  }
}

document.getElementById("modal-close").addEventListener("click", closeModal);
backdrop.addEventListener("click", event => { if (event.target === backdrop) closeModal(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !backdrop.classList.contains("hidden")) closeModal(); });
document.getElementById("reset-progress").addEventListener("click", () => {
  unlockedCount = 1;
  localStorage.removeItem(LEVELS_STORAGE_KEY);
  for (const [type, item] of equipped.entries()) {
    const islandIndex = ISLANDS.findIndex(island => island.id === item.island);
    if (islandIndex >= unlockedCount) equipped.delete(type);
  }
  saveProgress();
  renderMap();
  renderAccessoryRows();
  renderKangarooOutfit();
  closeModal();
});
document.getElementById("open-kangaroo").addEventListener("click", openKangarooScreen);
document.getElementById("back-to-map").addEventListener("click", openPreviousScreen);
document.getElementById("back-to-map-from-island").addEventListener("click", openMapScreen);
document.getElementById("open-kangaroo-from-island").addEventListener("click", openKangarooScreen);

renderMap();
initKangarooScreen();
