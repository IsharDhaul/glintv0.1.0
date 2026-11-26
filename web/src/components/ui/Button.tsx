import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-forest text-on-forest hover:bg-forest/90 active:bg-ink font-medium",
  secondary: "border border-line-strong bg-paper text-ink-soft hover:border-ink-soft active:bg-dune",
  ghost: "text-ink-soft hover:bg-dune/50 active:bg-dune",
};

export function Button({
  variant = "secondary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type={type}
      className={`inline-flex h-ctl items-center gap-1.5 rounded-control px-3 text-label transition-colors duration-150 ease-out disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${className}`}
      {...props}
    />
  );
}

/** Square icon-only button. `label` is required so it is never unnamed for screen readers. */
export function IconButton({
  label,
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex size-ctl items-center justify-center rounded-control text-muted transition-colors duration-150 ease-out hover:bg-dune hover:text-ink-soft ${className}`}
      {...props}
    />
  );
}
