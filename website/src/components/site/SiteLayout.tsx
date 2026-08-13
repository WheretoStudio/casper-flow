import type { ReactNode } from "react";
import { Header } from "./Header";
import { Footer } from "./Footer";
import { RevealProvider } from "./Reveal";

export function SiteLayout({ children }: { children: ReactNode }) {
  return (
    <RevealProvider>
      <div className="min-h-dvh bg-background">
        {/*
          Skip link. Every page puts the same navigation ahead of its content, so
          without this a keyboard or screen-reader user tabs through the whole
          header on every single page before reaching anything they came for.
          Positioned off-screen until focused, rather than hidden - `display: none`
          or `hidden` would take it out of the tab order and defeat the point.
        */}
        <a
          href="#main"
          className="sr-only rounded-md bg-foreground px-4 py-2 text-[14px] font-medium text-background focus-visible:not-sr-only focus-visible:absolute focus-visible:left-4 focus-visible:top-4 focus-visible:z-50"
        >
          Skip to content
        </a>
        <Header />
        {/* tabIndex={-1} so the skip link can move focus here, not just scroll. */}
        <main id="main" tabIndex={-1}>
          {children}
        </main>
        <Footer />
      </div>
    </RevealProvider>
  );
}
