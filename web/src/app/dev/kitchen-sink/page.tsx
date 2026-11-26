import type { Metadata } from "next";
import { SyntheticBanner } from "@/components/SyntheticBanner";
import { isMockMode } from "@/lib/api/config";
import { KitchenSink } from "./KitchenSink";

export const metadata: Metadata = { title: "Kitchen sink · Glint" };

// Design-pass page (WT-05 step 1). Every value here is a hand-written sample, not data.
export default function Page() {
  return (
    <>
      {!isMockMode() && <SyntheticBanner />}
      <KitchenSink />
    </>
  );
}
