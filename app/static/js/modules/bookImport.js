/**
 * bookImport.js — JS-driven book import flow for the admin panel.
 *
 * Stages:
 *   1. Search       — admin types a query; results appear as cards
 *   2. Preview      — admin clicks "Import Book"; metadata fills in
 *   3. Save         — admin fills price/stock/condition; book is saved
 *   3a. Duplicate   — modal lets admin update existing stock instead
 */

import { resolveCoverUrl } from "./cover.js";

const cfg = window._importConfig || {};

// ── DOM refs ──────────────────────────────────────────────────────────────
const qInput        = document.getElementById("import-q");
const searchBtn     = document.getElementById("import-search-btn");
const statusEl      = document.getElementById("import-status");
const hintEl        = document.getElementById("import-hint");
const resultsSection = document.getElementById("import-results-section");
const resultsList    = document.getElementById("import-results-list");
const sourceNote     = document.getElementById("import-source-note");
const previewSection = document.getElementById("import-preview-section");
const prevCover      = document.getElementById("prev-cover");
const prevTitle      = document.getElementById("prev-title");
const prevAuthor     = document.getElementById("prev-author");
const prevSpecs      = document.getElementById("prev-specs");
const prevDesc       = document.getElementById("prev-description");
const priceInput     = document.getElementById("inv-price");
const stockInput     = document.getElementById("inv-stock");
const conditionSel   = document.getElementById("inv-condition");
const featuredChk    = document.getElementById("inv-featured");
const confirmBtn     = document.getElementById("import-confirm-btn");
const backBtn        = document.getElementById("import-back-btn");
const dupModal       = document.getElementById("duplicate-modal");
const dupModalBody   = document.getElementById("dup-modal-body");
const dupStockInput  = document.getElementById("dup-stock");
const dupPriceInput  = document.getElementById("dup-price");
const dupUpdateBtn   = document.getElementById("dup-update-btn");
const dupCancelBtn   = document.getElementById("dup-cancel-btn");
const sourceTabs     = document.getElementById("import-source-tabs");

// ── State ─────────────────────────────────────────────────────────────────
let currentResults = [];
let selectedBook   = null;  // the candidate being previewed
let lastDuplicate  = null;  // {book_id, title, current_stock} from server
let metadataRequestId = 0;
let activeSource = "all";

// ── Search ────────────────────────────────────────────────────────────────
async function doSearch(source = activeSource) {
  const q = qInput.value.trim();
  if (!q) {
    showStatus("error", "Please enter an ISBN, title, or author.");
    return;
  }

  setSearching(true);
  hideAll();
  showStatus("loading", "Searching…");

  try {
    const resp = await fetch(
      `${cfg.searchUrl}?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}`
    );
    const data = await resp.json();

    if (!resp.ok) {
      showStatus("error", data.error || "Search failed.");
      return;
    }

    if (!data.results || data.results.length === 0) {
      const errs = (data.errors || []).map(e => e.message).join("; ");
      showStatus("error", `No results found for "${q}".${errs ? " (" + errs + ")" : ""}`);
      return;
    }

    currentResults = data.results;
    renderResults(data.results, source, data.errors || []);
    hideStatus();

  } catch (err) {
    showStatus("error", "Network error — please check your connection and try again.");
    console.error(err);
  } finally {
    setSearching(false);
  }
}

function renderResults(results, source, errors = []) {
  resultsList.innerHTML = "";

  const errorNote = errors.length
    ? ` <span class="admin-import-source-note__errors">${escHtml(errors.map(([, message]) => message).join("; "))}</span>`
    : "";
  sourceNote.innerHTML =
    `<i class="icon-database"></i> Matches from <strong>${humanSource(source)}</strong>. ` +
    `Pick the right edition below.${errorNote}`;

  results.forEach((book, idx) => {
    const card = document.createElement("div");
    card.className = "admin-import-candidate";
    card.dataset.idx = idx;

    const coverSrc = resolveCoverUrl(book.cover_image, cfg.defaultCover);
    const isbn = book.isbn ? `<span class="admin-import-candidate__isbn">ISBN ${book.isbn}</span>` : "";
    const pub = book.publisher
      ? `<span class="admin-import-candidate__isbn">${escHtml(book.publisher)}${book.published_date ? " · " + book.published_date : ""}</span>`
      : "";

    card.innerHTML = `
      <img src="${escHtml(coverSrc)}" alt="" onerror="this.src='${escHtml(cfg.defaultCover)}'" />
      <div class="admin-import-candidate__body">
        <span class="admin-import-candidate__title">${escHtml(book.title || "Untitled")}</span>
        <span class="admin-import-candidate__author">${escHtml(book.author || "Unknown author")}</span>
        ${isbn}
        ${pub}
      </div>
      <button class="btn btn--primary import-use-btn" type="button" data-idx="${idx}">
        <i class="icon-download"></i> Import
      </button>
    `;
    resultsList.appendChild(card);
  });

  hintEl.hidden     = true;
  resultsSection.hidden = false;
}

// ── Preview ────────────────────────────────────────────────────────────────
async function showPreview(book) {
  selectedBook = book;
  renderPreview(book);

  const requestId = ++metadataRequestId;
  if (!looksLikeIsbn(book.isbn)) {
    finishPreview();
    return;
  }

  showStatus("loading", "Fetching complete metadata…");
  try {
    const provider = book.source || activeSource;
    const resp = await fetch(
      `${cfg.metadataUrl}?isbn=${encodeURIComponent(book.isbn)}&source=${encodeURIComponent(provider)}`
    );
    const data = await resp.json();
    if (requestId !== metadataRequestId) return;
    if (resp.ok && data.metadata) {
      selectedBook = mergeMetadata(book, data.metadata);
      renderPreview(selectedBook);
    }
  } catch (err) {
    // The search result remains usable when the enrichment provider is unavailable.
    console.warn("Complete metadata lookup failed", err);
  } finally {
    if (requestId === metadataRequestId) finishPreview();
  }
}

function renderPreview(book) {
  prevCover.src = resolveCoverUrl(book.cover_image, cfg.defaultCover);
  prevCover.onerror = () => { prevCover.src = cfg.defaultCover; };
  prevTitle.textContent  = book.title || "Untitled";
  prevAuthor.textContent = book.author || "Unknown author";

  // Specs
  const specsData = [
    ["ISBN", book.isbn],
    ["Publisher", book.publisher],
    ["Published", book.published_date],
    ["Pages", book.pages],
    ["Language", book.language],
    ["Categories", (book.categories || []).join(", ")],
  ];
  prevSpecs.innerHTML = specsData
    .filter(([, v]) => v)
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${escHtml(String(v))}</dd></div>`)
    .join("");

  prevDesc.textContent = book.description || "";
  prevDesc.hidden = !book.description;

  // Reset inventory fields
  priceInput.value = "";
  stockInput.value = "1";
  conditionSel.selectedIndex = 0;
  featuredChk.checked = false;

  resultsSection.hidden = true;
  previewSection.hidden = false;
  priceInput.focus();
}

function finishPreview() {
  hideStatus();
}

function mergeMetadata(base, enriched) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(enriched || {})) {
    const isEmpty = value === null || value === undefined || value === "" ||
      (Array.isArray(value) && value.length === 0);
    if (!isEmpty) merged[key] = value;
  }
  return merged;
}

function looksLikeIsbn(value) {
  const cleaned = String(value || "").replace(/[\s-]/g, "");
  return /^\d{9}[\dXx]$|^\d{13}$/.test(cleaned);
}

// ── Confirm import ─────────────────────────────────────────────────────────
async function doImport() {
  const price = parseFloat(priceInput.value);
  const stock = parseInt(stockInput.value, 10);

  if (isNaN(price) || price < 0) {
    showStatus("error", "Please enter a valid price.");
    priceInput.focus();
    return;
  }
  if (isNaN(stock) || stock < 0) {
    showStatus("error", "Please enter a valid stock quantity.");
    stockInput.focus();
    return;
  }

  setConfirming(true);
  hideStatus();

  const payload = {
    ...selectedBook,
    price,
    stock,
    condition: conditionSel.value,
    is_featured: featuredChk.checked,
  };

  try {
    const resp = await fetch(cfg.importUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();

    if (data.duplicate) {
      lastDuplicate = data;
      openDuplicateModal(data, price);
      return;
    }

    if (data.success) {
      showSuccess(data.title);
    } else {
      showStatus("error", data.error || "Import failed. Please try again.");
    }

  } catch (err) {
    showStatus("error", "Network error — please try again.");
    console.error(err);
  } finally {
    setConfirming(false);
  }
}

// ── Duplicate modal ────────────────────────────────────────────────────────
function openDuplicateModal(dup, currentPrice) {
  dupModalBody.innerHTML =
    `<strong>${escHtml(dup.title)}</strong> by ${escHtml(dup.author || "")} is already in your inventory ` +
    `with <strong>${dup.current_stock}</strong> cop${dup.current_stock === 1 ? "y" : "ies"} in stock. ` +
    `How many additional copies would you like to add?`;
  dupStockInput.value = 1;
  dupPriceInput.value = currentPrice || "";
  dupModal.hidden = false;
}

function closeDuplicateModal() {
  dupModal.hidden = true;
  lastDuplicate   = null;
}

async function doUpdateStock() {
  if (!lastDuplicate) return;

  const additional = parseInt(dupStockInput.value, 10);
  const price      = parseFloat(dupPriceInput.value);

  if (isNaN(additional) || additional < 1) {
    dupStockInput.focus();
    return;
  }

  dupUpdateBtn.disabled = true;
  dupUpdateBtn.textContent = "Updating…";

  try {
    const resp = await fetch(cfg.importUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        force_update_stock: true,
        book_id: lastDuplicate.book_id,
        additional_stock: additional,
        price: isNaN(price) ? undefined : price,
        condition: conditionSel.value,
      }),
    });
    const data = await resp.json();

    closeDuplicateModal();

    if (data.success) {
      showSuccess(data.title, data.new_stock, true);
    } else {
      showStatus("error", data.error || "Update failed.");
    }

  } catch (err) {
    showStatus("error", "Network error — please try again.");
    console.error(err);
  } finally {
    dupUpdateBtn.disabled = false;
    dupUpdateBtn.innerHTML = `<i class="icon-plus"></i> Add to stock`;
  }
}

// ── Success state ──────────────────────────────────────────────────────────
function showSuccess(title, newStock, wasUpdate) {
  previewSection.hidden  = true;
  resultsSection.hidden  = true;
  selectedBook           = null;

  const msg = wasUpdate
    ? `Stock updated for <strong>${escHtml(title)}</strong>. Now ${newStock} cop${newStock === 1 ? "y" : "ies"} in stock.`
    : `<strong>${escHtml(title)}</strong> was imported successfully.`;

  statusEl.innerHTML = `
    <div class="import-success-banner">
      <i class="icon-check-circle"></i>
      <span>${msg}</span>
      <div class="import-success-actions">
        <a href="${cfg.booksUrl}" class="btn btn--primary btn--sm">View books</a>
        <button class="btn admin-btn-cancel btn--sm" id="import-another-btn" type="button">
          Import another
        </button>
      </div>
    </div>`;
  statusEl.hidden = false;

  document.getElementById("import-another-btn")?.addEventListener("click", resetToSearch);
}

function resetToSearch() {
  selectedBook    = null;
  currentResults  = [];
  hideAll();
  hideStatus();
  hintEl.hidden   = false;
  qInput.value    = "";
  qInput.focus();
}

// ── Utilities ──────────────────────────────────────────────────────────────
function hideAll() {
  resultsSection.hidden = true;
  previewSection.hidden = true;
  hintEl.hidden         = false;
}

function hideStatus()  { statusEl.hidden = true; statusEl.innerHTML = ""; }

function showStatus(type, msg) {
  statusEl.hidden = false;
  if (type === "loading") {
    statusEl.innerHTML = `<div class="import-spinner-row"><span class="import-spinner"></span>${escHtml(msg)}</div>`;
  } else if (type === "error") {
    statusEl.innerHTML = `<div class="admin-flash admin-flash--error">${escHtml(msg)}</div>`;
  } else {
    statusEl.innerHTML = `<div class="admin-flash admin-flash--success">${escHtml(msg)}</div>`;
  }
}

function setSearching(on) {
  searchBtn.disabled = on;
  searchBtn.innerHTML = on
    ? `<span class="import-spinner import-spinner--sm"></span> Searching…`
    : `<i class="icon-search"></i> Search`;
}

function setConfirming(on) {
  confirmBtn.disabled = on;
  confirmBtn.innerHTML = on
    ? `<span class="import-spinner import-spinner--sm"></span> Importing…`
    : `<i class="icon-check"></i> Import book`;
}

function humanSource(src) {
  const map = {
    all: "all available sources",
    google_books: "Google Books",
    open_library: "OpenLibrary",
    library_of_congress: "Library of Congress",
    hathitrust: "HathiTrust (ISBN only)",
    dc_bookstore: "DC Bookstore",
  };
  return map[src] || src;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Event listeners ────────────────────────────────────────────────────────
// Do not pass the click event as the source argument. Passing the event
// object produces source="[object PointerEvent]" and a 400 response.
searchBtn.addEventListener("click", () => doSearch());
qInput.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });

sourceTabs?.addEventListener("click", event => {
  const button = event.target.closest("[data-source]");
  if (!button) return;
  activeSource = button.dataset.source || "all";
  sourceTabs.querySelectorAll("[data-source]").forEach(tab => {
    tab.classList.toggle("is-active", tab === button);
  });
  if (qInput.value.trim()) {
    doSearch(activeSource);
  } else {
    showStatus("error", "Enter an ISBN, title, or author first.");
  }
});

// Delegate click on result cards → Import button
resultsList.addEventListener("click", e => {
  const btn = e.target.closest(".import-use-btn");
  if (!btn) return;
  const idx = parseInt(btn.dataset.idx, 10);
  if (!isNaN(idx) && currentResults[idx]) {
    showPreview(currentResults[idx]);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
});

confirmBtn.addEventListener("click", doImport);

backBtn.addEventListener("click", () => {
  previewSection.hidden = true;
  resultsSection.hidden = (currentResults.length === 0);
  hintEl.hidden         = currentResults.length > 0;
  hideStatus();
});

dupUpdateBtn.addEventListener("click", doUpdateStock);
dupCancelBtn.addEventListener("click", closeDuplicateModal);

// Close modal on overlay click
dupModal.addEventListener("click", e => {
  if (e.target === dupModal) closeDuplicateModal();
});

// Close modal on Escape
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !dupModal.hidden) closeDuplicateModal();
});
