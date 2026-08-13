import type { ReactNode } from "react";

/**
 * FAQ accordion.
 *
 * Built on <details>/<summary> rather than React state. That gets keyboard
 * support, the correct ARIA semantics, in-page find (browsers expand a closed
 * <details> when the search term is inside it) and correct behaviour with
 * JavaScript disabled — none of which a div with an onClick gives you for free.
 *
 * The `name` attribute makes it exclusive, so opening one closes the last. On the
 * engines that do not support it yet you simply get several open at once, which is
 * a fine outcome rather than a broken one.
 */

export type QA = { readonly q: string; readonly a: string };

export function FaqList({ items, name = "faq" }: { items: readonly QA[]; name?: string }) {
  return (
    <div className="divide-y divide-border border-y border-border">
      {items.map((item) => (
        <FaqItem key={item.q} question={item.q} name={name}>
          {item.a}
        </FaqItem>
      ))}
    </div>
  );
}

function FaqItem({
  question,
  name,
  children,
}: {
  question: string;
  name: string;
  children: ReactNode;
}) {
  return (
    <details className="faq-item group" name={name}>
      <summary className="flex cursor-pointer list-none items-start justify-between gap-6 py-5 text-[16.5px] font-medium tracking-[-0.01em] text-foreground/90 transition-colors hover:text-foreground">
        <span className="min-w-0">{question}</span>
        {/*
          A plus that rotates into an x. Two 1px bars instead of an icon
          dependency: one rotates, the other stays, so it costs nothing to ship.
        */}
        <span
          aria-hidden="true"
          className="faq-chevron relative mt-1.5 h-3.5 w-3.5 shrink-0 text-muted-foreground group-hover:text-accent"
        >
          <span className="absolute left-0 top-1/2 h-[1.5px] w-full -translate-y-1/2 rounded bg-current" />
          <span className="absolute left-1/2 top-0 h-full w-[1.5px] -translate-x-1/2 rounded bg-current transition-opacity group-open:opacity-0" />
        </span>
      </summary>
      <div className="pb-6 pr-10">
        <p className="max-w-[68ch] text-[15.5px] leading-[1.75] text-muted-foreground">
          {children}
        </p>
      </div>
    </details>
  );
}
