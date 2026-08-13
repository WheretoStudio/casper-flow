import { useEffect, useRef, type ElementType, type ReactNode } from "react";

/**
 * Marks the document so reveal styles apply only when JS is running,
 * then reveals each [data-reveal] element once via IntersectionObserver.
 */
export function RevealProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const root = document.documentElement;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;
    root.classList.add("js-reveal");

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            (entry.target as HTMLElement).dataset["shown"] = "true";
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.05 },
    );

    const scan = () => {
      document.querySelectorAll<HTMLElement>("[data-reveal]").forEach((el) => {
        if (el.dataset["shown"] !== "true") observer.observe(el);
      });
    };
    scan();
    const mo = new MutationObserver(scan);
    mo.observe(document.body, { childList: true, subtree: true });

    return () => {
      mo.disconnect();
      observer.disconnect();
      root.classList.remove("js-reveal");
    };
  }, []);

  return <>{children}</>;
}

export function Reveal({
  as: Tag = "div",
  delay = 0,
  className,
  children,
}: {
  as?: ElementType;
  delay?: number;
  className?: string;
  children: ReactNode;
}) {
  const ref = useRef(null);
  return (
    <Tag
      ref={ref}
      data-reveal=""
      style={{ "--reveal-delay": `${delay}ms` } as React.CSSProperties}
      className={className}
    >
      {children}
    </Tag>
  );
}
