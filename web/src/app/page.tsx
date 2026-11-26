import { Suspense } from "react";
import { Screener } from "@/components/screener/Screener";

export default function Home() {
  // Suspense: the screener reads ?s= with useSearchParams.
  return (
    <Suspense>
      <Screener />
    </Suspense>
  );
}
