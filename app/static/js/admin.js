/**
 * Small interactions used only by the admin area.
 */

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-stock-step]").forEach((button) => {
    button.addEventListener("click", () => {
      const stepper = button.closest(".admin-stock-stepper");
      const input = stepper?.querySelector('input[name="stock"]');
      if (!input) return;

      const current = Number.parseInt(input.value, 10);
      const step = Number.parseInt(button.dataset.stockStep, 10);
      const next = (Number.isFinite(current) ? current : 0) + step;
      input.value = String(Math.max(0, next));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });
});