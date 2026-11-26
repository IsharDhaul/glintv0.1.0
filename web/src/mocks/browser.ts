import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);

let started: Promise<unknown> | null = null;

/** Idempotent: Strict Mode runs effects twice, and MSW refuses a second start(). */
export function startMockWorker(): Promise<unknown> {
  // Only /api/* is mocked; Next's own assets and HMR pass straight through.
  started ??= worker.start({ onUnhandledFrame: "bypass", quiet: true });
  return started;
}
