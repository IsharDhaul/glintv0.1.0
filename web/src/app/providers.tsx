"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/config";

// Browser-only: msw/browser has no server build, so it must never enter the SSR bundle.
const MockWorker = dynamic(() => import("@/mocks/MockWorker"), { ssr: false });

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // API down / no build won't fix themselves on a retry; other errors get one.
        retry: (count, err) => !(err instanceof ApiError && err.kind !== "http") && count < 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeQueryClient);
  return (
    <QueryClientProvider client={client}>
      {isMockMode() && <MockWorker />}
      {children}
    </QueryClientProvider>
  );
}
