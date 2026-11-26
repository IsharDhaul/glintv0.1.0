import type { Metadata } from "next";
import { Suspense } from "react";
import { CompanyPage } from "./CompanyPage";

export async function generateMetadata({ params }: { params: Promise<{ ticker: string }> }): Promise<Metadata> {
  const { ticker } = await params;
  return { title: `${decodeURIComponent(ticker).toUpperCase()} · Glint` };
}

export default async function Page({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  return (
    <Suspense>
      <CompanyPage ticker={decodeURIComponent(ticker)} />
    </Suspense>
  );
}
