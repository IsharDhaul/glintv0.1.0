// Commands the palette (in the header, on every page) sends to the screener when it's mounted.
// Off the screener, the palette navigates instead (CommandPalette.tsx).

export type GlintCommand =
  | { kind: "open-company"; ticker: string }
  | { kind: "apply-preset"; id: string }
  | { kind: "add-filter"; metric: string }
  | { kind: "share" }
  | { kind: "export" }
  | { kind: "pin-company"; ticker: string }
  | { kind: "compare" }
  | { kind: "show-shortcuts" };

export const COMMAND_EVENT = "glint:command";

export function sendCommand(command: GlintCommand): void {
  window.dispatchEvent(new CustomEvent<GlintCommand>(COMMAND_EVENT, { detail: command }));
}

export function onCommand(handler: (command: GlintCommand) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<GlintCommand>).detail);
  window.addEventListener(COMMAND_EVENT, listener);
  return () => window.removeEventListener(COMMAND_EVENT, listener);
}
