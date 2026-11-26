import createClient from "openapi-fetch";
import { mockReady } from "@/mocks/ready";
import { apiBaseUrl, isMockMode } from "./config";
import type { components, paths } from "./types";

export type ErrorResponse = components["schemas"]["ErrorResponse"];

/**
 * One error type for the UI's states (SPEC §3.3): `network` = API down, `no_build` = run
 * `glint refresh` first, `http` = any other error response from the API.
 */
export class ApiError extends Error {
  constructor(
    readonly kind: "network" | "no_build" | "http",
    readonly status: number | null,
    readonly body: ErrorResponse | null,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// In mock mode MSW intercepts these same URLs in the browser, so components never know.
// Every request first waits for the worker, so none can slip out to a real API.
export const api = createClient<paths>({
  baseUrl: apiBaseUrl(),
  fetch: isMockMode()
    ? async (req: Request) => {
        await mockReady;
        return globalThis.fetch(req);
      }
    : undefined,
});

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Await an openapi-fetch call and return its data, or throw an ApiError. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  let res: Result<T>;
  try {
    res = await call;
  } catch {
    throw new ApiError("network", null, null, `Can't reach the API at ${apiBaseUrl()}.`);
  }
  if (res.response.ok && res.data !== undefined) return res.data;
  const body = isErrorResponse(res.error) ? res.error : null;
  const kind = body?.error === "NO_BUILD" ? "no_build" : "http";
  throw new ApiError(kind, res.response.status, body, body?.message ?? `${res.response.status} ${res.response.statusText}`);
}

function isErrorResponse(x: unknown): x is ErrorResponse {
  return typeof x === "object" && x !== null && "error" in x && "message" in x;
}
