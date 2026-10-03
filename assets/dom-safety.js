// Escape only data substitutions; authored markup stays in the source.
export function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]);
}
export function safeColor(value) {
  return /^#[0-9a-f]{6}$/i.test(value ?? "") ? value : "#9E9E9E";
}
export function number(value, fallback = 0) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
export const totalCount = rows => rows.reduce((n, row) => n + number(row.count, 1), 0);
