import { createFileRoute } from "@tanstack/react-router";
import { useEffect } from "react";
import { SITE } from "@/components/site/constants";
import { Mark } from "@/components/site/Mark";

/**
 * /download — starts the installer download and shows nothing else worth reading.
 *
 * The download button used to link straight to GitHub, which meant clicking it
 * took you to github.com. This keeps the visible URL on our own domain and hands
 * back the file.
 *
 * In production this route is almost never rendered: `vercel.json` has a 307 for
 * /download that fires at the edge, so the file starts arriving without any HTML
 * being parsed. This page exists for local development, for any host that is not
 * Vercel, and as the thing a user sees if the redirect is slow — with a plain
 * link, because a page that says "your download is starting" and offers no way to
 * retry is a dead end.
 *
 * Why GitHub still hosts the file: it is 234 MB. That cannot go in the git
 * repository, and Vercel is not a file host for artefacts that size. GitHub
 * Releases is free, fast, resumable and already where the tags live.
 */

export const Route = createFileRoute("/download")({
  head: () => ({
    meta: [
      { title: "Downloading Casper Flow…" },
      // Kept out of search results: it is a redirect, not a page.
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: DownloadPage,
});

function DownloadPage() {
  useEffect(() => {
    // replace() rather than assign(), so Back returns to the page they came
    // from instead of bouncing them into the download again.
    window.location.replace(SITE.downloadUrl);
  }, []);

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background px-6 text-center">
      <Mark className="h-12 w-12" />
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Your download is starting</h1>
        <p className="mt-2 text-[15px] text-muted-foreground">
          CasperFlowSetup.exe · {SITE.installerSize} · version {SITE.version}
        </p>
      </div>
      <a
        href={SITE.downloadUrl}
        className="rounded-md border border-border-strong bg-card px-4 py-2 text-[14px] font-medium transition-colors hover:bg-surface"
      >
        If nothing happens, click here
      </a>
      <p className="max-w-[46ch] break-all font-mono text-[11px] leading-relaxed text-muted-foreground">
        SHA-256 {SITE.sha256}
      </p>
      {/*
        Four pages tell the reader that checksums are published and that a
        portable build exists. Nothing linked either of them, and both constants
        sat unused in constants.ts - so the promise was made and then not kept.
      */}
      <p className="text-[13px] text-muted-foreground">
        <a
          href={SITE.checksumsUrl}
          className="underline decoration-border-strong underline-offset-4 hover:text-foreground"
        >
          All checksums
        </a>
        <span aria-hidden="true" className="mx-2.5 text-muted-foreground/70">
          ·
        </span>
        <a
          href={SITE.portableUrl}
          className="underline decoration-border-strong underline-offset-4 hover:text-foreground"
        >
          Portable zip, no installer
        </a>
      </p>
    </div>
  );
}
