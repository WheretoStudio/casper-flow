import { useId } from "react";

/**
 * The Casper Flow mark, as SVG.
 *
 * This is the same geometry as `draw_mark` in make_icon.py — a squircle with a
 * dictation caret and a level bar either side — re-expressed in vector form. The
 * proportions are ported deliberately rather than approximated: the tray icon,
 * the installer, the favicon and this share one design, and a nav logo that is
 * "nearly" the icon looks like a mistake rather than a family.
 *
 * SVG rather than the .ico or a PNG: it stays sharp at any size and on any
 * display, and it is a few hundred bytes inline instead of a request.
 *
 * The gradient id comes from useId because the mark renders more than once per
 * page (header and footer). Two <linearGradient> elements sharing an id is
 * invalid, and the second one silently inherits the first.
 */
export function Mark({ className = "h-7 w-7" }: { className?: string }) {
  const id = useId();
  const grad = `mark-grad-${id}`;

  return (
    <svg viewBox="0 0 100 100" className={className} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={grad} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#b14e2a" />
          <stop offset="100%" stopColor="#8a391e" />
        </linearGradient>
      </defs>

      {/* pad 9%, radius 28 — matches SIMPLE_BELOW-independent large rendering */}
      <rect x="9" y="9" width="82" height="82" rx="28" ry="28" fill={`url(#${grad})`} />

      {/* Level bar, left: shorter. Alpha 0.75, as in the icon. */}
      <rect x="23.75" y="38" width="9.5" height="24" rx="4.75" fill="#fffaf6" opacity="0.75" />
      {/* The caret: the tallest, fully opaque, dead centre. */}
      <rect x="42.75" y="28" width="14.5" height="44" rx="7.25" fill="#fffaf6" />
      {/* Level bar, right: taller than the left, so the mark is not symmetrical. */}
      <rect x="66.75" y="35" width="9.5" height="30" rx="4.75" fill="#fffaf6" opacity="0.75" />
    </svg>
  );
}

/**
 * Lockup for the header: mark plus name.
 *
 * The name is a real text node rather than part of the SVG, so it inherits the
 * page's font and stays selectable and searchable.
 */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <Mark className="h-[26px] w-[26px] shrink-0" />
      <span className="text-[15.5px] font-semibold tracking-[-0.015em]">Casper Flow</span>
    </span>
  );
}
