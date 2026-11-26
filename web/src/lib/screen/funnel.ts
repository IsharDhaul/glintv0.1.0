import { describeNode } from "./describe";
import { isGroup, type Condition, type Group, type MetricDefinition, type Screen } from "./types";

/**
 * The screen node a funnel step or near miss points at (`["filters", "children", i, …]`).
 * Null when the path doesn't resolve against this screen.
 */
export function nodeAtPath(screen: Screen, path: (string | number)[] | null | undefined): Condition | Group | null {
  if (!path || path[0] !== "filters") return null;
  let node: Condition | Group | undefined = screen.filters;
  for (let k = 1; k < path.length; k += 2) {
    if (path[k] !== "children" || !node || !isGroup(node)) return null;
    const i = path[k + 1];
    if (typeof i !== "number") return null;
    node = node.children?.[i];
  }
  return node ?? null;
}

/**
 * Label for a step, built from the screen with format.ts so every number shares one format
 * (the API's own label formats numbers itself). Falls back to the API label.
 */
export function stepLabel(
  step: { filter_path: (string | number)[] | null; label: string },
  screen: Screen,
  metrics: Map<string, MetricDefinition>,
): string {
  if (step.filter_path === null) return "Universe";
  const node = nodeAtPath(screen, step.filter_path);
  return node ? describeNode(node, metrics) : step.label;
}
