/**
 * Instant search suggestions. Attaches to every `[data-search-suggest]`
 * wrapper (home hero search, browse filter bar) and queries `/api/suggest`,
 * which matches title, author, ISBN, category, and publisher.
 */
import { formatInr } from "./format.js";
import { resolveCoverUrl } from "./cover.js";

export function initSearchSuggest() {
  document.querySelectorAll("[data-search-suggest]").forEach(setupWrapper);
}

function setupWrapper(wrapper) {
  const input = wrapper.querySelector("[data-suggest-input]");
  const list = wrapper.querySelector("[data-suggest-list]");
  if (!input || !list) return;

  let debounceTimer = null;
  let activeIndex = -1;

  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    const term = input.value.trim();
    if (term.length < 2) {
      closeList();
      return;
    }
    debounceTimer = setTimeout(() => fetchSuggestions(term), 220);
  });

  input.addEventListener("keydown", (event) => {
    if (list.hidden) return;
    const options = Array.from(list.querySelectorAll(".search-suggest__item"));
    if (options.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, options.length - 1);
      highlight(options);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      highlight(options);
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      window.location.href = options[activeIndex].getAttribute("href");
    } else if (event.key === "Escape") {
      closeList();
    }
  });

  document.addEventListener("click", (event) => {
    if (!wrapper.contains(event.target)) closeList();
  });

  input.addEventListener("blur", () => {
    // Delay so a click on a suggestion still registers before we hide it.
    setTimeout(closeList, 150);
  });

  async function fetchSuggestions(term) {
    try {
      const response = await fetch(`/api/suggest?q=${encodeURIComponent(term)}`);
      if (!response.ok) return;
      const books = await response.json();
      renderList(books, term);
    } catch (err) {
      console.warn("Suggestion fetch failed", err);
    }
  }

  function renderList(books, term) {
    activeIndex = -1;
    if (books.length === 0) {
      list.innerHTML = `<p class="search-suggest__empty">No matches for \u201c${escapeHtml(term)}\u201d.</p>`;
      list.hidden = false;
      return;
    }

    list.innerHTML = books
      .map(
        (book) => `
        <a class="search-suggest__item" href="/books/${book.id}">
          <img src="${escapeHtml(resolveCoverUrl(book.cover_image))}" alt="" class="search-suggest__cover" loading="lazy" onerror="this.src='/static/images/covers/cover-01.jpg'" />
          <span class="search-suggest__text">
            <span class="search-suggest__title">${highlightMatch(book.title, term)}</span>
            <span class="search-suggest__meta">${escapeHtml(book.author)} &middot; ${escapeHtml(book.genre)}</span>
          </span>
          <span class="search-suggest__price">${formatInr(book.price)}</span>
        </a>`
      )
      .join("");
    list.hidden = false;
  }

  function highlight(options) {
    options.forEach((el, idx) => el.classList.toggle("is-active", idx === activeIndex));
    if (activeIndex >= 0) options[activeIndex].scrollIntoView({ block: "nearest" });
  }

  function closeList() {
    list.hidden = true;
    list.innerHTML = "";
    activeIndex = -1;
  }

  function highlightMatch(text, term) {
    const safe = escapeHtml(text);
    const idx = safe.toLowerCase().indexOf(term.toLowerCase());
    if (idx === -1) return safe;
    return (
      safe.slice(0, idx) +
      "<mark>" +
      safe.slice(idx, idx + term.length) +
      "</mark>" +
      safe.slice(idx + term.length)
    );
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
}
