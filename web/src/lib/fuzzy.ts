// Fuzzy matching for the command palette: higher is better, null is no match.
// Exact > prefix > word-start > substring > in-order subsequence (with a penalty for gaps).

export function fuzzyScore(query: string, text: string): number | null {
  const q = query.trim().toLowerCase();
  const t = text.toLowerCase();
  if (!q) return 0;
  if (t === q) return 1000;
  if (t.startsWith(q)) return 800 - t.length;
  const words = t.split(/[^a-z0-9]+/).filter(Boolean);
  if (words.some((w) => w.startsWith(q))) return 600 - t.length;
  const at = t.indexOf(q);
  if (at >= 0) return 400 - at;
  // Subsequence: every query character, in order.
  let i = 0;
  let gaps = 0;
  let last = -1;
  for (let j = 0; j < t.length && i < q.length; j++) {
    if (t[j] === q[i]) {
      if (last >= 0) gaps += j - last - 1;
      last = j;
      i++;
    }
  }
  return i === q.length ? Math.max(1, 200 - gaps * 5) : null;
}

/** Items that match, best first; ties keep their input order. */
export function fuzzyFilter<T>(query: string, items: T[], text: (item: T) => string): T[] {
  return items
    .map((item, k) => ({ item, k, s: fuzzyScore(query, text(item)) }))
    .filter((x): x is { item: T; k: number; s: number } => x.s !== null)
    .sort((a, b) => b.s - a.s || a.k - b.k)
    .map((x) => x.item);
}
