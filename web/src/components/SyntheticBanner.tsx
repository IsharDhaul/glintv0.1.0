/** Mock mode banner (SPEC §3.3). Fixed to the top of every page; there is no way to dismiss it. */
export function SyntheticBanner() {
  return (
    <aside
      aria-label="Synthetic data notice"
      data-testid="synthetic-banner"
      data-synthetic-banner
      className="banner-hatch sticky top-0 z-50 flex h-banner items-center justify-center px-4 text-center text-label font-semibold text-on-banner"
    >
      Synthetic data: these are not real companies
    </aside>
  );
}
