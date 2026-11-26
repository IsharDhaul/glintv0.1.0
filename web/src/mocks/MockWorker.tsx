"use client";

import { useEffect } from "react";
import { startMockWorker } from "./browser";
import { markMockReady } from "./ready";

/** Browser-only (loaded with ssr: false): starts MSW, then releases the API client's requests. */
export default function MockWorker() {
  useEffect(() => {
    void startMockWorker().then(markMockReady);
  }, []);
  return null;
}
