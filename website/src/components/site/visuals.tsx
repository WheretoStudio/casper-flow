import type { ReactNode } from "react";

function WindowChrome({
  title,
  children,
  className = "",
}: {
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`overflow-hidden rounded-lg border border-border-strong bg-card ${className}`}
      style={{ boxShadow: "var(--shadow-panel)" }}
    >
      <div className="flex items-center justify-between border-b border-border bg-surface px-4 py-2.5">
        <span className="truncate font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          {title}
        </span>
        <span
          aria-hidden="true"
          className="flex shrink-0 items-center gap-3 text-muted-foreground/70"
        >
          <span className="block h-px w-3 bg-current" />
          <span className="block h-2.5 w-2.5 border border-current" />
          <span className="block h-2.5 w-2.5 rotate-45 border-l border-t border-current" />
        </span>
      </div>
      {children}
    </div>
  );
}

export function Caret() {
  return (
    <span
      aria-hidden="true"
      className="ml-[1px] inline-block h-[1.05em] w-[1.5px] translate-y-[0.18em] bg-accent"
    />
  );
}

/** Hero: dictated text landing at the cursor inside a Windows document window. */
export function DictationScene() {
  return (
    <figure className="relative">
      <WindowChrome title="Document.docx — Word">
        <div className="px-6 py-7 sm:px-10 sm:py-10">
          <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
            Draft — client memorandum
          </p>
          <div className="mt-5 max-w-[52ch] space-y-3 text-[15px] leading-[1.75] text-foreground">
            <p>
              Following our call on Tuesday, I have reviewed the revised schedule and the two
              outstanding indemnity clauses.
            </p>
            <p>
              <span className="text-muted-foreground">The position remains unchanged: </span>
              <span className="bg-accent-soft/70 px-0.5">
                we will not accept an uncapped liability provision in section nine
              </span>
              <Caret />
            </p>
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-border bg-surface px-6 py-2 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground sm:px-10">
          <span>Page 3 of 7</span>
          <span>English (United Kingdom)</span>
        </div>
      </WindowChrome>

      {/*
        The default overlay, shown the way it actually appears: transparent, with
        no panel behind it, floating near the bottom of the screen over whatever
        you are working in. This used to show the live-caption pill, which is not
        the default and needs an extra model downloaded before it works.
      */}
      <div className="mt-4 flex justify-center sm:absolute sm:-bottom-14 sm:left-1/2 sm:mt-0 sm:-translate-x-1/2">
        <BlobOverlay bare />
      </div>
      <figcaption className="sr-only">
        A Windows word processor with a legal memorandum. Dictated words appear at the text cursor
        while Casper Flow&rsquo;s overlay floats below, pulsing with the speaker&rsquo;s voice.
      </figcaption>
    </figure>
  );
}

/**
 * Frame for an overlay screenshot.
 *
 * The overlay images in public/overlay/ are produced by make_overlay_previews.py,
 * which imports the application's own `pill_render` module and calls the same
 * function the app calls 24 times a second. They are the overlay, not a drawing
 * of it — the previous hand-built SVG had the wrong colour, the wrong shape and
 * none of the waveform detail, which is exactly what happens when a marketing
 * asset is maintained separately from the thing it depicts.
 *
 * The overlay itself is transparent, with its own glow and shadow, and floats
 * over whatever you are working in. It is shown here on a dark panel because that
 * is the background its light grey side-waveform is legible against, and because
 * a transparent PNG on paper-white would look like a mistake.
 */
function OverlayShot({
  src,
  alt,
  width,
  height,
  display,
  animate = false,
  bare = false,
}: {
  src: string;
  alt: string;
  width: number;
  height: number;
  /** Rendered width in CSS pixels. The files are 2x for high-DPI displays. */
  display: number;
  animate?: boolean;
  /** No panel: the transparent overlay on whatever is behind it, as in use. */
  bare?: boolean;
}) {
  const img = (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      loading="lazy"
      decoding="async"
      className={`relative block h-auto w-full ${animate ? "blob-pulse" : ""}`}
      style={{ maxWidth: display }}
    />
  );

  if (bare) return img;

  return (
    <div className="relative flex items-center justify-center overflow-hidden rounded-xl bg-surface-deep px-4 py-5 ring-1 ring-inset ring-white/10">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(130% 100% at 50% 35%, rgba(255,255,255,0.055), transparent 70%)",
        }}
      />
      {img}
    </div>
  );
}

export function LiveCaptionOverlay() {
  return (
    <OverlayShot
      src="/overlay/caption.png"
      alt="The live caption overlay: a dark rounded pill containing a small waveform, the words being transcribed, and the elapsed time."
      width={567}
      height={96}
      display={284}
    />
  );
}

/**
 * The default overlay: an organic red shape that morphs and swells with your
 * voice, with the input waveform inside it and a grey waveform trailing off to
 * both sides. No text.
 *
 * Two earlier attempts at drawing this by hand were both wrong — the second one
 * so wrong that it read as an orange smudge in a black box. It is now the real
 * render. The CSS pulse is on top of a still frame, so it breathes the way the
 * live one does without shipping an animation.
 */
export function BlobOverlay({ bare = false }: { bare?: boolean } = {}) {
  return (
    <OverlayShot
      src="/overlay/blob.png"
      alt="The default overlay: a soft red organic shape with your voice level drawn as bars inside it, and a grey waveform trailing away on both sides. No text."
      width={393}
      height={216}
      display={216}
      animate
      bare={bare}
    />
  );
}

export function CompactBarOverlay() {
  return (
    <OverlayShot
      src="/overlay/capsule.png"
      alt="The compact bar overlay: a small dark capsule with a pulsing dot, the word Recording, a live level meter and an elapsed timer."
      width={528}
      height={109}
      display={264}
    />
  );
}

export function ClipboardScene() {
  return (
    <figure className="grid gap-3">
      <div className="rounded-md border border-border bg-card p-4">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
          Clipboard before dictation
        </p>
        <p className="mt-2 text-[13.5px]">chart-q3.png — image, 1.2&nbsp;MB</p>
      </div>
      <div className="rounded-md border border-dashed border-border-strong bg-surface p-4">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
          During paste
        </p>
        <p className="mt-2 text-[13.5px] text-muted-foreground">
          Transcript placed on the clipboard, pasted at the cursor.
        </p>
      </div>
      <div className="rounded-md border border-border bg-card p-4">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
          Clipboard after dictation
        </p>
        <p className="mt-2 text-[13.5px]">chart-q3.png — image, 1.2&nbsp;MB</p>
      </div>
      <figcaption className="sr-only">
        The clipboard holds an image before dictation, is used briefly for the transcript, and is
        restored to the same image afterwards.
      </figcaption>
    </figure>
  );
}

export function HinglishScene() {
  return (
    <figure>
      <WindowChrome title="Slack — #product">
        <div className="space-y-6 px-6 py-7 sm:px-9">
          <div>
            <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
              Spoken
            </p>
            <p className="mt-2 text-[16px] leading-[1.7]">
              &ldquo;Build ka status kya hai, I need it before the review call&rdquo;
            </p>
          </div>
          <div className="border-t border-border pt-6">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
              Inserted — Roman script
            </p>
            <p className="mt-2 text-[16px] leading-[1.7]">
              Build ka status kya hai, I need it before the review call
              <Caret />
            </p>
          </div>
          {/*
            Labelled as optional because it is. Script conversion happens in the
            cleanup step, and the shipped cleanup backend is `rules`, which is
            deterministic and does not transliterate. Devanagari output requires
            switching that step to a local Ollama model. Presenting it as a second
            default, which this panel used to do, was simply untrue.
          */}
          <div className="border-t border-border pt-6">
            <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
              Devanagari — optional, needs local Ollama
            </p>
            {/*
              lang="hi" on the Hindi run only. Without it a screen reader
              pronounces Devanagari with English phonetics, which is unintelligible,
              and the mixed sentence is exactly the case that needs the marker: the
              English tail after the comma stays in the document language.
            */}
            <p className="mt-2 text-[16px] leading-[1.8] text-muted-foreground">
              <span lang="hi">बिल्ड का स्टेटस क्या है</span>, I need it before the review call
            </p>
          </div>
        </div>
      </WindowChrome>
      <figcaption className="sr-only">
        A mixed English and Hindi sentence dictated into Slack, inserted in Roman script by default.
        Devanagari output is available if the optional local cleanup model is enabled.
      </figcaption>
    </figure>
  );
}
