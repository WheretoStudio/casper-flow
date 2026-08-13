import { Link } from "@tanstack/react-router";
import { SITE } from "./constants";
import { Mark } from "./Mark";

/**
 * Footer.
 *
 * Dark, against a paper-white page, because the previous one was a row of grey
 * links that could have belonged to any project. Two things carry it: real
 * columns with headings instead of one undifferentiated list, and an oversized
 * wordmark cropped by the bottom edge, which gives the page a deliberate ending
 * rather than just stopping.
 *
 * The wordmark is `aria-hidden` and set in a huge low-contrast weight — it is
 * texture, not content, and a screen reader announcing "CASPER FLOW" again at the
 * end of every page would be noise.
 *
 * No contact section: there is no support desk behind this, and inventing one
 * would be a promise we cannot keep. Issues go to the repository.
 */

const COLUMNS: Array<{
  heading: string;
  links: Array<{ label: string; to?: string; href?: string; note?: string }>;
}> = [
  {
    heading: "Get it",
    links: [
      { label: "Download for Windows", href: "/download", note: SITE.installerSize },
      { label: "Portable zip", href: "/download/portable", note: SITE.portableSize },
      { label: "Checksums", href: "/download/checksums" },
    ],
  },
  {
    heading: "Read",
    links: [
      { label: "How it works", to: "/" },
      { label: "Install & usage guide", to: "/guide" },
      { label: "vs Wispr Flow", to: "/alternatives/wispr-flow" },
      { label: "Source code", href: SITE.repoUrl },
    ],
  },
  {
    heading: "Legal",
    links: [
      { label: "Privacy", to: "/privacy" },
      { label: "Terms", to: "/terms" },
      { label: `${SITE.license} licence`, href: "https://opensource.org/licenses/MIT" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="relative overflow-hidden bg-surface-deep text-surface-deep-foreground">
      <div className="relative z-10 mx-auto max-w-[1200px] px-6 pb-40 pt-20 md:px-10 md:pb-56 md:pt-28">
        <div className="grid gap-14 lg:grid-cols-[minmax(0,4fr)_minmax(0,7fr)] lg:gap-20">
          <div className="min-w-0">
            <span className="inline-flex items-center gap-2.5">
              <Mark className="h-8 w-8 shrink-0" />
              <span className="text-[17px] font-semibold tracking-[-0.015em] text-white">
                Casper Flow
              </span>
            </span>
            <p className="mt-5 max-w-[34ch] text-[14.5px] leading-relaxed text-surface-deep-foreground/60">
              Dictation for Windows that runs on your own processor. No account, no subscription,
              and your voice never leaves the machine.
            </p>
            <p className="mt-6 inline-flex items-center gap-2 rounded-full border border-white/12 px-3 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.14em] text-surface-deep-foreground/60">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
              Works offline
            </p>
          </div>

          <nav aria-label="Footer" className="grid gap-10 sm:grid-cols-3">
            {COLUMNS.map((col) => (
              <div key={col.heading} className="min-w-0">
                <h2 className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-surface-deep-foreground/70">
                  {col.heading}
                </h2>
                <ul className="mt-5 space-y-3.5">
                  {col.links.map((link) => (
                    <li key={link.label} className="min-w-0">
                      {link.to ? (
                        <Link
                          to={link.to}
                          className="group inline-flex items-baseline gap-2 text-[14px] text-surface-deep-foreground/75 transition-colors hover:text-white"
                        >
                          <span className="border-b border-transparent transition-colors group-hover:border-white/30">
                            {link.label}
                          </span>
                        </Link>
                      ) : (
                        <a
                          href={link.href}
                          className="group inline-flex items-baseline gap-2 text-[14px] text-surface-deep-foreground/75 transition-colors hover:text-white"
                        >
                          <span className="border-b border-transparent transition-colors group-hover:border-white/30">
                            {link.label}
                          </span>
                          {link.note ? (
                            <span className="font-mono text-[10px] text-surface-deep-foreground/70">
                              {link.note}
                            </span>
                          ) : null}
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        <div className="mt-20 flex flex-col gap-3 border-t border-white/10 pt-7 font-mono text-[10.5px] uppercase tracking-[0.14em] text-surface-deep-foreground/70 sm:flex-row sm:items-center sm:justify-between">
          <p>
            © 2026 Casper Flow · {SITE.license} · v{SITE.version}
          </p>
          <p>Built for Windows · runs on your CPU</p>
        </div>
      </div>

      {/*
        The oversized wordmark. Positioned so its lower third is cropped by the
        footer's edge, which is what stops it reading as a heading and starts it
        reading as a watermark. select-none because dragging across the page and
        catching it would be irritating.
      */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 -bottom-[0.16em] select-none text-center text-[clamp(4rem,17vw,14rem)] font-semibold leading-[0.8] tracking-[-0.04em] text-white/[0.045]"
      >
        CASPER FLOW
      </span>
    </footer>
  );
}
