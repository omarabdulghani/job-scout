const LIST_BULLET_PREFIX = /^(?:[-*\u2022]\s+|\d+[.)]\s+)/;

function cleanListEditorItem(value) {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(LIST_BULLET_PREFIX, "")
    .trim();
}

export function listEditorText(values) {
  if (!Array.isArray(values)) return "";
  return values
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
    .join("\n");
}

export function splitListEditor(value) {
  const output = [];
  const seen = new Set();
  const lines = String(value ?? "").replace(/\r\n?/g, "\n").split("\n");

  for (const line of lines) {
    const cleaned = cleanListEditorItem(line);
    const key = cleaned.toLowerCase();
    if (!cleaned || seen.has(key)) continue;
    seen.add(key);
    output.push(cleaned);
  }
  return output;
}
