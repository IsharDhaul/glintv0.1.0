"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useDebounced } from "@/lib/useDebounced";
import type { Screen } from "./types";
import { decodeScreen } from "./codec";
import { sameScreen, screenFromParam, screenParam, withScreenParam } from "./url";

/**
 * The screen, kept in `?s=` (SPEC §3.3 "URL state"):
 * - it starts from the URL, so shared links and preset cards open their screen;
 * - each settled change (after `delay` ms) pushes one history entry, so Back undoes it;
 * - Back/Forward (or any outside URL change) replaces the screen with the URL's.
 * `lastWritten` tells our own pushes apart from outside changes, so the two never loop.
 */
export function useScreenUrlState(delay = 400): [Screen, Dispatch<SetStateAction<Screen>>, { brokenLink: boolean }] {
  const params = useSearchParams();
  const urlS = params.get("s");
  const [screen, setScreen] = useState<Screen>(() => screenFromParam(urlS));
  const lastWritten = useRef<string | null>(urlS);

  // Outside change: Back/Forward, a pasted link, or a Link to /?s=… while mounted.
  useEffect(() => {
    if (urlS === lastWritten.current) return;
    lastWritten.current = urlS;
    setScreen(screenFromParam(urlS));
  }, [urlS]);

  // Our change: once edits settle, push one entry, unless the URL already says this screen.
  // The first write normalises the incoming URL in place (defaults filled, re-encoded), so it
  // replaces rather than pushes: otherwise Back would just return to the same screen.
  const settled = useDebounced(screen, delay);
  const first = useRef(true);
  useEffect(() => {
    const current = new URLSearchParams(window.location.search).get("s");
    const replace = first.current;
    // An unreadable ?s= stays in the address bar (review fix: never erase a link silently); the
    // screener says it opened empty. The next real edit pushes a valid URL as usual.
    if (replace && current !== null && decodeScreen(current) === null) {
      first.current = false;
      lastWritten.current = current;
      return;
    }
    first.current = false;
    // The URL moved (Back/Forward) but React hasn't absorbed it yet: writing now would push a
    // stale screen over the user's navigation. The absorb effect will set the screen instead.
    if (current !== lastWritten.current) return;
    const s = screenParam(settled);
    // Compare content, not strings: the same screen can encode differently (an old link,
    // defaults filled in). Pushing an "edit" that isn't one would erase the Forward history.
    // Only the first write rewrites such a URL, in place, to its normal form.
    const unchanged = sameScreen(settled, screenFromParam(current));
    if (unchanged && !(replace && s !== current)) {
      lastWritten.current = current;
      return;
    }
    lastWritten.current = s;
    const url = `${window.location.pathname}${withScreenParam(window.location.search, s)}`;
    if (replace) window.history.replaceState(window.history.state, "", url);
    else window.history.pushState(null, "", url);
  }, [settled]);

  // The link is broken while the URL still carries the unreadable value.
  const brokenLink = urlS !== null && decodeScreen(urlS) === null;
  return [screen, setScreen, { brokenLink }];
}
