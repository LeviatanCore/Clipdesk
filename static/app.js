const lookupForm = document.querySelector("#lookup");
const urlInput = document.querySelector("#url");
const playlistInput = document.querySelector("#playlist");
const lookupButton = document.querySelector("#lookup-button");
const formError = document.querySelector("#form-error");
const preview = document.querySelector("#preview");
const thumb = document.querySelector("#thumb");
const kind = document.querySelector("#kind");
const titleEl = document.querySelector("#title");
const metaEl = document.querySelector("#meta");
const qualityGrid = document.querySelector("#quality-grid");
const formatId = document.querySelector("#format-id");
const downloadButton = document.querySelector("#download-button");
const downloadError = document.querySelector("#download-error");
const activity = document.querySelector("#activity");
const jobsEl = document.querySelector("#jobs");
const folderEl = document.querySelector("#folder");
const folderInput = document.querySelector("#output");
const browseButton = document.querySelector("#browse-button");
const destinationsEl = document.querySelector("#destinations");
const destinationHint = document.querySelector("#destination-hint");
const folderError = document.querySelector("#folder-error");
const fileList = document.querySelector("#file-list");

const state = {
  info: null,
  quality: "1080",
  output: "",
  outputHint: "",
  suggestions: [],
};

function fileHref(name, output) {
  const params = new URLSearchParams();
  if (output) params.set("output", output);
  const query = params.toString();
  return `/files/${encodeURIComponent(name)}${query ? `?${query}` : ""}`;
}

const statusText = {
  starting: "Preparando",
  downloading: "Descargando",
  merging: "Uniendo pistas",
  done: "Listo",
  error: "No se pudo",
  cancelled: "Cancelada",
};

function showError(node, message) {
  node.hidden = !message;
  node.textContent = message || "";
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (_error) {
    return {};
  }
}

function currentLabel() {
  const match = state.suggestions.find((item) => item.path === state.output);
  return match ? match.label : "Carpeta elegida";
}

function updateDestinationCopy() {
  const label = currentLabel();
  const hint = state.outputHint || state.output;
  destinationHint.textContent = hint ? `${label} · ${hint}` : "Elige un destino o abre el explorador.";
  folderEl.textContent = hint || state.output || "";
}

function setDestination(path, hint, label) {
  folderInput.value = path || "";
  state.output = path || "";
  state.outputHint = hint || path || "";
  if (label && path && !state.suggestions.some((item) => item.path === path)) {
    state.suggestions = [
      { label, path, hint: hint || path },
      ...state.suggestions.filter((item) => item.path !== path),
    ];
    renderDestinations();
  }
  markDestination(path);
  updateDestinationCopy();
  if (path) window.localStorage.setItem("ydl-output", path);
  else window.localStorage.removeItem("ydl-output");
}

function renderDestinations() {
  destinationsEl.replaceChildren();
  for (const item of state.suggestions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "destination";
    button.setAttribute("role", "option");
    button.dataset.path = item.path;
    button.setAttribute("aria-selected", item.path === state.output ? "true" : "false");
    const title = document.createElement("span");
    title.className = "destination-label";
    title.textContent = item.label;
    const hint = document.createElement("span");
    hint.className = "destination-hint";
    hint.textContent = item.hint || item.path;
    button.append(title, hint);
    button.addEventListener("click", () => {
      setDestination(item.path, item.hint || item.path, item.label);
      refreshFiles();
    });
    destinationsEl.appendChild(button);
  }
}

function markDestination(path) {
  for (const button of destinationsEl.querySelectorAll(".destination")) {
    button.setAttribute("aria-selected", button.dataset.path === path ? "true" : "false");
  }
}

function renderQualities(qualities) {
  qualityGrid.replaceChildren();
  for (const quality of qualities) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = quality.label;
    button.dataset.quality = quality.id;
    button.setAttribute("aria-pressed", quality.id === state.quality ? "true" : "false");
    button.addEventListener("click", () => {
      state.quality = quality.id;
      formatId.value = "";
      for (const chip of qualityGrid.querySelectorAll(".chip")) {
        chip.setAttribute("aria-pressed", chip === button ? "true" : "false");
      }
    });
    qualityGrid.appendChild(button);
  }
}

function renderPreview(info) {
  state.info = info;
  preview.hidden = false;
  titleEl.textContent = info.title || "Sin título";
  if (info.is_playlist) {
    kind.textContent = "Lista";
    metaEl.textContent = info.count ? `${info.count} videos` : "Varios videos";
  } else {
    kind.textContent = "Video";
    metaEl.textContent = [info.channel, info.duration].filter(Boolean).join(" · ");
  }
  if (info.thumbnail) {
    thumb.hidden = false;
    thumb.src = info.thumbnail;
    thumb.alt = "";
  } else {
    thumb.hidden = true;
    thumb.removeAttribute("src");
  }
  showError(downloadError, "");
  preview.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderFiles(files) {
  fileList.replaceChildren();
  if (!files.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "Todavía no hay archivos en este destino.";
    fileList.appendChild(empty);
    return;
  }
  for (const file of files) {
    const item = document.createElement("li");
    item.className = "file-row";
    const link = document.createElement("a");
    link.href = fileHref(file.name, state.output);
    link.textContent = file.name;
    const size = document.createElement("span");
    size.className = "meta";
    size.textContent = file.size_label;
    item.append(link, size);
    fileList.appendChild(item);
  }
}

function renderJobs(jobs) {
  const visible = jobs.filter((job) =>
    ["starting", "downloading", "merging", "error"].includes(job.status)
  );
  activity.hidden = visible.length === 0;
  jobsEl.replaceChildren();
  for (const job of visible) {
    const card = document.createElement("article");
    card.className = "job";
    const top = document.createElement("div");
    top.className = "job-top";
    const heading = document.createElement("h3");
    heading.textContent = job.title || "Video";
    const status = document.createElement("span");
    status.className = `status-${job.status}`;
    status.textContent = statusText[job.status] || job.status;
    top.append(heading, status);

    const bar = document.createElement("div");
    bar.className = "bar";
    bar.setAttribute("role", "progressbar");
    const value = Number.isFinite(job.percent) ? job.percent : 0;
    bar.setAttribute("aria-valuenow", String(Math.round(value)));
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    const fill = document.createElement("span");
    fill.style.width = `${Math.max(0, Math.min(100, value))}%`;
    bar.appendChild(fill);

    const meta = document.createElement("p");
    meta.className = "meta job-meta";
    const position = job.index && job.count ? `${job.index} de ${job.count}` : "";
    const bits = [job.quality, position, job.speed, job.eta ? `queda ${job.eta}` : ""].filter(Boolean);
    meta.textContent = job.error || bits.join(" · ");

    card.append(top, bar, meta);
    if (job.status === "starting" || job.status === "downloading" || job.status === "merging") {
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.className = "ghost";
      cancel.textContent = "Cancelar";
      cancel.addEventListener("click", () => cancelJob(job.id, cancel));
      card.appendChild(cancel);
    }
    if (job.files && job.files.length) {
      const list = document.createElement("div");
      for (const file of job.files) {
        const link = document.createElement("a");
        link.href = fileHref(file.name, job.output || state.output);
        link.textContent = `Abrir ${file.name}`;
        list.appendChild(link);
      }
      card.appendChild(list);
    }
    jobsEl.appendChild(card);
  }
}

async function refreshFiles() {
  const params = new URLSearchParams();
  const selected = folderInput.value.trim();
  if (selected) params.set("output", selected);
  const response = await fetch(`/api/files?${params.toString()}`);
  const data = await readJson(response);
  if (!response.ok) {
    showError(folderError, data.error || "No se pudo usar esa carpeta.");
    return;
  }
  showError(folderError, "");
  setDestination(data.output_dir || selected, data.output_hint || data.output_dir || selected);
  renderFiles(data.files || []);
}

let pollTimer = 0;

async function poll() {
  window.clearTimeout(pollTimer);
  try {
    const response = await fetch("/api/jobs");
    const data = await readJson(response);
    if (!response.ok) return;
    const jobs = data.jobs || [];
    renderJobs(jobs);
    const active = jobs.some((job) => ["starting", "downloading", "merging"].includes(job.status));
    if (active) {
      pollTimer = window.setTimeout(poll, 700);
      return;
    }
    await refreshFiles();
  } catch (_error) {
    pollTimer = window.setTimeout(poll, 1500);
  }
}

async function cancelJob(id, button) {
  button.disabled = true;
  await fetch(`/api/jobs/${id}/cancel`, { method: "POST" });
  poll();
}

lookupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError(formError, "");
  lookupButton.disabled = true;
  lookupButton.textContent = "Leyendo…";
  try {
    const response = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: urlInput.value.trim(),
        playlist: playlistInput.checked,
      }),
    });
    const data = await readJson(response);
    if (!response.ok) {
      preview.hidden = true;
      state.info = null;
      showError(formError, data.error || "No se pudo leer el enlace.");
      return;
    }
    renderPreview(data);
  } finally {
    lookupButton.disabled = false;
    lookupButton.textContent = "Continuar";
  }
});

downloadButton.addEventListener("click", async () => {
  if (!state.info) return;
  showError(downloadError, "");
  const custom = formatId.value.trim();
  const quality = custom || state.quality;
  downloadButton.disabled = true;
  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: state.info.url,
        quality,
        playlist: playlistInput.checked,
        title: state.info.title,
        output: folderInput.value.trim(),
      }),
    });
    const data = await readJson(response);
    if (!response.ok) {
      showError(downloadError, data.error || "No se pudo empezar la descarga.");
      return;
    }
    activity.hidden = false;
    poll();
  } finally {
    downloadButton.disabled = false;
  }
});

formatId.addEventListener("input", () => {
  const custom = formatId.value.trim();
  for (const chip of qualityGrid.querySelectorAll(".chip")) {
    chip.setAttribute(
      "aria-pressed",
      custom ? "false" : chip.dataset.quality === state.quality ? "true" : "false"
    );
  }
});

browseButton.addEventListener("click", async () => {
  showError(folderError, "");
  browseButton.disabled = true;
  browseButton.querySelector(".browse-title").textContent = "Abriendo explorador…";
  try {
    const response = await fetch("/api/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output: folderInput.value.trim() }),
    });
    const data = await readJson(response);
    if (!response.ok) {
      showError(folderError, data.error || "No se pudo abrir el explorador.");
      return;
    }
    if (data.cancelled || !data.output_dir) return;
    setDestination(data.output_dir, data.output_hint || data.output_dir, data.label || "Carpeta elegida");
    await refreshFiles();
  } finally {
    browseButton.disabled = false;
    browseButton.querySelector(".browse-title").textContent = "Explorar carpeta";
  }
});

async function boot() {
  const response = await fetch("/api/meta");
  const data = await readJson(response);
  if (response.ok) {
    const badge = document.querySelector("#mode-badge");
    if (badge) badge.textContent = data.docker ? "Docker" : "Local";
    if (!data.browse_enabled) {
      browseButton.hidden = true;
      const destCopy = document.querySelector("#destination-hint");
      if (destCopy && data.docker) {
        destCopy.textContent = "Los archivos se guardan en la carpeta montada del contenedor.";
      }
    }
    renderQualities(data.qualities || []);
    state.suggestions = data.suggestions || [];
    renderDestinations();
    const saved = data.docker ? "" : window.localStorage.getItem("ydl-output");
    const initial = saved || data.output_dir || "";
    const match = state.suggestions.find((item) => item.path === initial);
    setDestination(initial, match?.hint || data.output_hint || initial, match?.label);
  }
  await refreshFiles();
  poll();
}

boot();
