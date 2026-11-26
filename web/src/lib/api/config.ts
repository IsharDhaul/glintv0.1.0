export const DEFAULT_API_URL = "http://localhost:8000";

type Env = Record<string, string | undefined>;

// Next inlines NEXT_PUBLIC_* into the browser bundle only where the literal
// `process.env.NEXT_PUBLIC_…` appears, so the defaults below must spell it out.
const BUILD_ENV: Env = {
  NEXT_PUBLIC_GLINT_API_URL: process.env.NEXT_PUBLIC_GLINT_API_URL,
  NEXT_PUBLIC_GLINT_MOCK: process.env.NEXT_PUBLIC_GLINT_MOCK,
};

export function apiBaseUrl(env: Env = BUILD_ENV): string {
  return (env.NEXT_PUBLIC_GLINT_API_URL || DEFAULT_API_URL).replace(/\/+$/, "");
}

export function isMockMode(env: Env = BUILD_ENV): boolean {
  return env.NEXT_PUBLIC_GLINT_MOCK === "1";
}
