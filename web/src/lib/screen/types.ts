import type { components } from "@/lib/api/types";

type S = components["schemas"];

export type Screen = S["Screen"];
export type Group = S["Group"];
export type Condition = S["Condition"];
export type Comparator = S["Comparator"];
export type MetricDefinition = S["MetricDefinition"];
export type ScreenResponse = S["ScreenResponse"];
export type ResultRow = S["ResultRow"];
export type NearMiss = S["NearMiss"];
export type Sector = S["Sector"];

export function isGroup(node: Condition | Group): node is Group {
  return "op" in node;
}
