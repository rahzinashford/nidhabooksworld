/**
 * Nidha Books World — main entry point.
 * Modular, dependency-free JS. Each concern lives in its own module under
 * static/js/modules/ and is wired up here.
 */
import { initHeaderScroll } from "./modules/header.js";
import { initLiveSearch } from "./modules/liveSearch.js";
import { initRevealOnScroll } from "./modules/reveal.js";
import { setFooterYear } from "./modules/footerYear.js";
import { initHeroFade } from "./modules/heroFade.js";
import { initSearchSuggest } from "./modules/searchSuggest.js";

document.addEventListener("DOMContentLoaded", () => {
  setFooterYear();
  initHeaderScroll();
  initRevealOnScroll();
  initLiveSearch();
  initHeroFade();
  initSearchSuggest();
});
