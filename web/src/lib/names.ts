// Company names as SEC files them ("ADOBE INC.", "UPWORK, INC", "Nutex Health Inc.") made
// readable for tables: title case for all-caps names, legal suffixes dropped. The drawer and
// company page keep the full legal name.

const SUFFIX = /(?:[,\s]+(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|llc|lp|l\.p|n\.v|s\.a|ag|se|holdings?|group))\.?\s*$/i;
const SMALL = new Set(["of", "and", "the", "for", "de", "la", "du", "en", "on", "in", "at", "by", "to", "a"]);
const VOWEL = /[AEIOUY]/;

function titleWord(w: string, first: boolean): string {
  const lower = w.toLowerCase();
  if (!first && SMALL.has(lower)) return lower;
  // Short all-caps words without vowels, or 2–3 letter ones, are usually acronyms (AMC, USA, IBM).
  const letters = w.replace(/[^A-Za-z]/g, "");
  if (letters.length > 0 && letters.length <= 3 && !SMALL.has(lower)) return w;
  if (letters.length > 0 && !VOWEL.test(letters)) return w;
  // Keep separators: "MCDONALD'S" → "Mcdonald's", "COCA-COLA" → "Coca-Cola".
  return lower.replace(/(^|[-/&.])([a-z])/g, (_, sep: string, c: string) => sep + c.toUpperCase());
}

/** "ADOBE INC." → "Adobe", "UPWORK, INC" → "Upwork", "Nutex Health Inc." → "Nutex Health". */
export function displayName(name: string): string {
  // EDGAR state tags first ("BANK OF AMERICA CORP /DE/", "ALIGHT, INC. / DELAWARE").
  let n = name.trim().replace(/\s*\/\s*[A-Za-z]{2,}\s*\/?\s*$/, "");
  // Drop trailing legal suffixes (repeatedly: "Holdings, Inc." → "").
  for (let k = 0; k < 3; k++) {
    const next = n.replace(SUFFIX, "").replace(/[,\s]+$/, "");
    if (next === n || next.length < 2) break;
    n = next;
  }
  const allCaps = n === n.toUpperCase() && /[A-Z]/.test(n);
  if (!allCaps) return n;
  return n
    .split(/\s+/)
    .map((w, i) => titleWord(w, i === 0))
    .join(" ");
}
