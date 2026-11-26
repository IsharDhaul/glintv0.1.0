import { delay, http, HttpResponse, type HttpHandler } from "msw";
import type { components } from "@/lib/api/types";
import { decodeScreen } from "@/lib/screen/codec";
import type { Screen } from "@/lib/screen/types";
import { MOCK_DATA } from "./data";
import { mockCompany, mockCsv, mockDistribution, mockHistoryPoints, mockScreen, mockSearch, mockSectors } from "./generate";
import { mockPresets } from "./presets";
import { readScenario } from "./scenario";
import { mockSnapshot } from "./store";

type S = components["schemas"];

const data = MOCK_DATA;
const buildId = data.meta.build_id;

function error(status: number, code: S["ErrorCode"], message: string) {
  return HttpResponse.json<S["ErrorResponse"]>({ build_id: buildId, error: code, message }, { status });
}

/** Applies the ?mock= scenario before every handler. Returns a response to short-circuit with. */
async function gate() {
  const scenario = readScenario();
  if (scenario === "slow") await delay(1500);
  else await delay(120); // a little latency so loading states are real
  if (scenario === "down") return HttpResponse.error();
  if (scenario === "nobuild") return error(503, "NO_BUILD", "No build yet. Run `glint refresh` first.");
  return null;
}

// "*/api/..." matches whatever base URL the client uses (NEXT_PUBLIC_GLINT_API_URL).
export const handlers: HttpHandler[] = [
  http.get("*/api/health", async () => (await gate()) ?? HttpResponse.json<S["HealthResponse"]>({ build_id: buildId, status: "ok" })),

  http.get("*/api/meta", async () => (await gate()) ?? HttpResponse.json<S["MetaResponse"]>(data.meta)),

  http.get("*/api/metrics", async () => (await gate()) ?? HttpResponse.json<S["MetricsResponse"]>({ build_id: buildId, metrics: data.metrics })),

  http.get("*/api/sectors", async () => (await gate()) ?? HttpResponse.json(mockSectors(data))),

  http.get("*/api/presets", async () => {
    const blocked = await gate();
    if (blocked) return blocked;
    const presets = await mockPresets();
    return HttpResponse.json<S["PresetListResponse"]>({
      build_id: buildId,
      presets: presets.map(({ id, name, summary, kind }) => ({ id, name, summary, kind })),
    });
  }),

  http.get("*/api/presets/:id", async ({ params }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    const preset = (await mockPresets()).find((p) => p.id === params.id);
    return preset
      ? HttpResponse.json<S["PresetResponse"]>({ build_id: buildId, preset })
      : error(404, "UNKNOWN_PRESET", `No preset "${String(params.id)}".`);
  }),

  http.post("*/api/screen", async ({ request }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    const screen = (await request.json()) as Screen;
    return HttpResponse.json(mockScreen(data, screen, { empty: readScenario() === "empty" }));
  }),

  http.post("*/api/screen/export", async ({ request }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    const screen = (await request.json()) as Screen;
    const res = mockScreen(data, screen, { empty: readScenario() === "empty" });
    const slug = screen.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "screen";
    const date = (data.meta.as_of.prices ?? "synthetic").slice(0, 10);
    return new HttpResponse(mockCsv(res, screen), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="glint-${slug}-${date}.csv"`,
      },
    });
  }),

  http.get("*/api/distribution", async ({ request }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    const url = new URL(request.url);
    const metric = url.searchParams.get("metric") ?? "";
    if (!data.metrics.some((m) => m.id === metric)) return error(404, "UNKNOWN_METRIC", `No metric "${metric}".`);
    const within = (url.searchParams.get("within") ?? "universe") as S["Within"];
    const sector = (url.searchParams.get("sector") || null) as S["Sector"] | null;
    return HttpResponse.json(mockDistribution(data, metric, within, sector));
  }),

  http.get("*/api/search", async ({ request }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    return HttpResponse.json(mockSearch(data, new URL(request.url).searchParams.get("q") ?? ""));
  }),

  http.get("*/api/snapshot/meta", async () => (await gate()) ?? HttpResponse.json(mockSnapshot(data).meta)),

  http.get("*/api/snapshot/values", async () => {
    const blocked = await gate();
    if (blocked) return blocked;
    return new HttpResponse(mockSnapshot(data).body, {
      headers: { "Content-Type": "application/octet-stream", "X-Glint-Build": buildId ?? "" },
    });
  }),

  http.get("*/api/companies/:ticker/history", async ({ params, request }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    const ticker = String(params.ticker);
    const metric = new URL(request.url).searchParams.get("metric") ?? "";
    const row = data.rows.find((x) => x.ticker.toUpperCase() === ticker.toUpperCase());
    if (!row) return error(404, "UNKNOWN_TICKER", `No company "${ticker}".`);
    return HttpResponse.json<S["HistoryResponse"]>({ build_id: buildId, ticker: row.ticker, metric, points: mockHistoryPoints(data, row.cik, metric) });
  }),

  http.get("*/api/companies/:ticker", async ({ params, request }) => {
    const blocked = await gate();
    if (blocked) return blocked;
    const encoded = new URL(request.url).searchParams.get("screen");
    const screen = encoded ? decodeScreen(encoded) : null;
    if (encoded && !screen) return error(422, "INVALID_SCREEN", "screen is not lz-string compressed Screen JSON");
    const company = mockCompany(data, String(params.ticker), screen);
    return company ? HttpResponse.json(company) : error(404, "UNKNOWN_TICKER", `No company "${String(params.ticker)}".`);
  }),
];
