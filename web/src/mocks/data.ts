// web/mocks/*.json is written by `glint fixtures synthetic` (make synthetic). Never hand-edit it.
import companies from "../../mocks/companies.json";
import history from "../../mocks/history.json";
import meta from "../../mocks/meta.json";
import metrics from "../../mocks/metrics.json";
import profiles from "../../mocks/profiles.json";
import type { MockData } from "./generate";

export const MOCK_DATA: MockData = {
  meta: meta as unknown as MockData["meta"],
  metrics: metrics.metrics as unknown as MockData["metrics"],
  rows: companies.rows as unknown as MockData["rows"],
  profiles: profiles.companies as unknown as MockData["profiles"],
  history: history as unknown as MockData["history"],
  config: profiles.screen_config,
};
