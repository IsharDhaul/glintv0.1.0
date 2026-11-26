import { isMockMode } from "@/lib/api/config";
import { loadPresetFiles } from "@/mocks/presetFiles";

// Mock mode only: hands config/presets/*.json to the MSW handlers in the browser.
export async function GET() {
  if (!isMockMode()) return new Response("Not found", { status: 404 });
  return Response.json(await loadPresetFiles());
}
