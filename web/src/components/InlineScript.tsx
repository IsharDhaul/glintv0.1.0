/**
 * A <script> that runs during HTML parsing, before first paint. On the client it renders as
 * text/plain so React doesn't warn about (or re-run) it; suppressHydrationWarning covers the
 * type difference. Pattern from the Next 16 "preventing flash before hydration" guide.
 */
export function InlineScript({ html }: { html: string }) {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
