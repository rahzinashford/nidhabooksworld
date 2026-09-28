/** Shared formatting helpers for search/browse UI. */
export function formatInr(value) {
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  return Number.isInteger(num)
    ? `\u20b9${num.toLocaleString("en-IN")}`
    : `\u20b9${num.toFixed(2)}`;
}
