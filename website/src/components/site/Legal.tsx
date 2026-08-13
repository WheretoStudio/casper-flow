import type { ReactNode } from "react";

/**
 * Shared furniture for the privacy and terms pages.
 *
 * Both were a single column of headings with no way to navigate them, which is
 * how legal pages end up unread. This gives them a table of contents that sticks
 * beside the text on a wide screen and collapses above it on a narrow one, and
 * anchored headings so a specific clause can be linked to directly.
 *
 * The section list is defined once per page and drives both the contents and the
 * headings, so a section cannot exist in one and not the other.
 */

export type LegalSection = { id: string; title: string; body: ReactNode };

export function LegalPage({
  eyebrow,
  title,
  summary,
  sections,
  updated,
  footnote,
}: {
  eyebrow: string;
  title: string;
  summary: ReactNode;
  sections: LegalSection[];
  updated: string;
  footnote?: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-[1200px] px-6 pb-24 pt-14 md:px-10 md:pb-32 md:pt-20">
      <header className="max-w-[70ch]">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          {eyebrow}
        </p>
        <h1 className="mt-5 text-[clamp(2rem,4.6vw,3.1rem)] font-semibold leading-[1.06] tracking-[-0.035em]">
          {title}
        </h1>
        <div className="mt-6 text-[16.5px] leading-[1.7] text-muted-foreground">{summary}</div>
        <p className="mt-7 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Last updated {updated}
        </p>
      </header>

      <div className="mt-16 grid gap-12 lg:grid-cols-[minmax(0,240px)_minmax(0,1fr)] lg:gap-20">
        <nav aria-label="On this page" className="lg:sticky lg:top-24 lg:self-start">
          <h2 className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
            On this page
          </h2>
          <ol className="mt-4 space-y-1">
            {sections.map((s, i) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className="group flex gap-3 rounded py-1.5 text-[13.5px] leading-snug text-muted-foreground transition-colors hover:text-foreground"
                >
                  <span className="font-mono text-[11px] tabular-nums text-muted-foreground group-hover:text-accent">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0">{s.title}</span>
                </a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="min-w-0">
          {sections.map((s, i) => (
            <section
              key={s.id}
              id={s.id}
              // scroll-mt keeps the heading clear of the sticky header when
              // arriving from the contents or a shared anchor link.
              className="scroll-mt-24 border-t border-border py-10 first:border-t-0 first:pt-0"
            >
              <div className="flex items-baseline gap-4">
                <span className="font-mono text-[11px] tabular-nums text-accent">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <h2 className="text-[19px] font-semibold tracking-[-0.02em]">{s.title}</h2>
              </div>
              <div className="mt-4 space-y-4 pl-0 text-[15.5px] leading-[1.75] text-muted-foreground sm:pl-[2.1rem] [&_a]:text-foreground [&_a]:underline [&_a]:underline-offset-4 [&_code]:font-mono [&_code]:text-[13.5px] [&_code]:text-foreground [&_li]:pl-1 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:space-y-2 [&_ul]:pl-5">
                {s.body}
              </div>
            </section>
          ))}

          {footnote ? (
            <p className="mt-10 border-t border-border pt-8 text-[14px] leading-[1.7] text-muted-foreground">
              {footnote}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
