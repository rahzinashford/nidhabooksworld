/** Fill in the current year in the footer without a template dependency. */
export function setFooterYear() {
  const el = document.getElementById("footer-year");
  if (el) {
    el.textContent = new Date().getFullYear();
  }
}
