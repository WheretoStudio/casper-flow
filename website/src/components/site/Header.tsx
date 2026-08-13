import { Link } from "@tanstack/react-router";
import { SITE } from "./constants";
import { Logo } from "./Mark";

export function Header() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/70 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4 px-6 py-3 md:px-10">
        <Link
          to="/"
          aria-label="Casper Flow, home"
          className="min-w-0 shrink-0 text-foreground transition-opacity hover:opacity-70"
        >
          <Logo />
        </Link>

        <nav aria-label="Primary" className="flex shrink-0 items-center gap-0.5 sm:gap-1">
          <Link
            to="/guide"
            className="rounded-md px-3 py-2 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground"
          >
            Guide
          </Link>
          <Link
            to="/alternatives/wispr-flow"
            className="hidden rounded-md px-3 py-2 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground sm:block"
          >
            Compare
          </Link>
          <a
            href={SITE.repoUrl}
            className="rounded-md px-3 py-2 text-[13.5px] text-muted-foreground transition-colors hover:text-foreground"
          >
            Source
          </a>
          {/*
            Points at /download, our own path, which redirects to the release
            asset. Keeps the visible URL on our domain and means the destination
            can change without touching the markup.
          */}
          <a
            href="/download"
            className="ml-1 inline-flex items-center gap-2 rounded-md bg-accent px-3.5 py-2 text-[13.5px] font-medium text-accent-foreground shadow-[0_1px_2px_rgba(0,0,0,0.08)] transition-transform hover:-translate-y-px hover:opacity-95"
          >
            Download
            <span aria-hidden="true" className="font-mono text-[10px] opacity-70">
              {SITE.installerSize}
            </span>
          </a>
        </nav>
      </div>
    </header>
  );
}
