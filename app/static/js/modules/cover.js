/**
 * Resolve a stored cover value for an <img src>.
 *
 * Local catalog covers are stored relative to Flask's static directory.
 * Imported covers may remain hosted by Google Books or Open Library when a
 * provider refuses a server-side download, so those URLs must not be prefixed
 * with /static/.
 */
export function resolveCoverUrl(value, fallback = "/static/images/covers/cover-01.jpg") {
  const cover = String(value || "").trim();
  if (!cover) return fallback;
  if (/^https?:\/\//i.test(cover)) return cover;
  if (/^\/\//.test(cover)) return `https:${cover}`;
  if (cover.startsWith("/")) return cover;
  return `/static/${cover}`;
}