/**
 * Progressive-enhancement live search for the Browse page.
 * The form still works without JS (full page reload); when JS is available
 * we debounce input and re-render results via the JSON API for a snappier
 * mobile experience.
 */
import { formatInr } from "./format.js";
import { resolveCoverUrl } from "./cover.js";

export function initLiveSearch() {
  const input = document.getElementById("book-search");
  const resultsEl = document.getElementById("book-results");
  if (!input || !resultsEl) return;

  let debounceTimer = null;

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => runSearch(input.value.trim()), 300);
  });

  async function runSearch(term) {
    // Only intercept plain search; if genre/condition filters are active,
    // let the full page form submission handle it for correctness.
    const genreSelect = document.querySelector('select[name="genre"]');
    const conditionSelect = document.querySelector('select[name="condition"]');
    if (
      (genreSelect && genreSelect.value) ||
      (conditionSelect && conditionSelect.value)
    ) {
      return;
    }

    try {
      const response = await fetch(
        `${window.location.pathname.replace(/\/browse.*/, "")}/api/books?q=${encodeURIComponent(term)}`
      );
      if (!response.ok) return;
      const books = await response.json();
      renderResults(books);
    } catch (err) {
      // Network hiccup — leave existing results in place.
      console.warn("Live search failed", err);
    }
  }

  function renderResults(books) {
    if (books.length === 0) {
      resultsEl.innerHTML = `
        <div class="empty-state">
          <i class="icon-book-x"></i>
          <p>No books match yet — try a different search term.</p>
        </div>`;
      return;
    }

    const cards = books
      .map(
        (book) => `
        <article class="book-card">
          <a href="/books/${book.id}" class="book-card__link">
            <div class="book-card__cover">
              <img src="${escapeHtml(resolveCoverUrl(book.cover_image))}" alt="Cover of ${escapeHtml(book.title)}" loading="lazy" width="240" height="240" onerror="this.src='/static/images/covers/cover-01.jpg'" />
              <span class="book-card__condition">${escapeHtml(book.condition)}</span>
            </div>
            <div class="book-card__body">
              <h3 class="book-card__title">${escapeHtml(book.title)}</h3>
              <p class="book-card__author">${escapeHtml(book.author)}</p>
              <p class="book-card__price">${formatInr(book.price)}</p>
            </div>
          </a>
        </article>`
      )
      .join("");

    resultsEl.innerHTML = `<div class="book-grid">${cards}</div>`;
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
}
