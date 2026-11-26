// Resolves once the MSW worker controls this page. In mock mode the API client waits on it
// before every request, so nothing ever reaches a real API. Safe to import on the server.

let resolveReady: () => void = () => {};

export const mockReady = new Promise<void>((resolve) => {
  resolveReady = resolve;
});

export function markMockReady(): void {
  resolveReady();
}
