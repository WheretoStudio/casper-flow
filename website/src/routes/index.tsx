import { createFileRoute } from "@tanstack/react-router";
import { SiteLayout } from "@/components/site/SiteLayout";
import { Reveal } from "@/components/site/Reveal";
import { ACCURACY, SITE, url } from "@/components/site/constants";
import { FaqList, type QA } from "@/components/site/Faq";
import { formatCount, getDownloadCount } from "@/components/site/downloads";
import {
  BlobOverlay,
  ClipboardScene,
  CompactBarOverlay,
  DictationScene,
  HinglishScene,
  LiveCaptionOverlay,
} from "@/components/site/visuals";

const DESCRIPTION =
  "Casper Flow is a free, open-source Windows dictation app. Hold a key, speak, and your words appear at your cursor. It runs on the CPU of an ordinary laptop — no GPU, no account, no subscription — and your voice never leaves the machine.";

/**
 * Rendered on the page as accordions and emitted as FAQPage structured data from
 * the same array, because Google requires the two to match and the usual way that
 * breaks is answering a question in markup that is no longer on the page.
 */
const FAQ: readonly QA[] = [
  {
    q: "Do I need a graphics card?",
    a: "No. Casper Flow is built for the processor in an ordinary laptop, and every speed figure published here was measured on a CPU with no GPU involved. The models are int8-quantised to make that practical. There is a setting to use an NVIDIA GPU if you have one, but it is not required and not benchmarked.",
  },
  {
    q: "Will it run on an old or cheap laptop?",
    a: "That is what it was built for. It needs 64-bit Windows 10 or 11, about 420 MB of disk space and roughly 200 MB of memory once the speech model is loaded. There is no minimum GPU, no dedicated hardware and no cloud fallback doing the real work.",
  },
  {
    q: "Is Casper Flow really free?",
    a: "Yes. It is open source under the MIT licence, with no account, no subscription, no trial and no usage limits. There is no paid tier to upgrade to.",
  },
  {
    q: "Does my voice get uploaded anywhere?",
    a: "No. Speech recognition runs on your own CPU. The models are installed with the app, the temporary recording is deleted as soon as the text is produced, and the cloud client libraries are excluded from the build — so the program you install is not capable of reaching a transcription API, whatever its settings say.",
  },
  {
    q: "Does it work offline?",
    a: "Completely, including during installation. Both speech models are inside the download, so you can install and dictate on a plane with Wi-Fi off.",
  },
  {
    q: "How accurate is it?",
    a: "Measured on a 30-phrase spoken corpus, on a two-core laptop: the English-only model is 91% accurate at about 1.1 seconds per sentence, and the Hinglish model is 81% accurate on mixed Hindi-English at about 1.3 seconds. Those are two different models, and the installer asks which one you want — each is poor at the other's job. We were aiming for 90% on Hinglish and have not got there yet.",
  },
  {
    q: "Can it handle Hinglish and code-switching?",
    a: "That is what it ships tuned for. The default model handles sentences that move between Hindi and English mid-flow, and writes Hindi words in Roman script the way most people type them.",
  },
  {
    q: "Will Windows Defender block it?",
    a: "It might. Dictation needs a global keyboard hook to notice your push-to-talk key in other applications, and that is the same mechanism a keylogger uses, so antivirus software sometimes flags it. The installer is not code-signed yet. Checksums are published so you can verify the download, and the source is short enough to read.",
  },
  {
    q: "Do I need administrator rights to install it?",
    a: "No. It installs for your account only, into your local app data folder, so there is no UAC prompt at any point. That also means it works on a managed or locked-down work laptop.",
  },
  {
    q: "Which Windows versions are supported?",
    a: "Windows 10 and Windows 11, 64-bit. There is no macOS or Linux build.",
  },
];

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Casper Flow — free local dictation for Windows, on any CPU" },
      { name: "description", content: DESCRIPTION },
      {
        property: "og:title",
        content: "Casper Flow — free local dictation for Windows, on any CPU",
      },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:type", content: "website" },
      { property: "og:url", content: url("/") },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: url("/") }],
    scripts: [
      {
        type: "application/ld+json",
        children: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "SoftwareApplication",
          name: "Casper Flow",
          applicationCategory: "UtilitiesApplication",
          operatingSystem: "Windows 10, Windows 11",
          processorRequirements: "x86-64 CPU; no GPU required",
          memoryRequirements: "200 MB",
          storageRequirements: "420 MB",
          description: DESCRIPTION,
          url: url("/"),
          downloadUrl: SITE.downloadUrl,
          softwareVersion: SITE.version,
          fileSize: SITE.installerSize,
          license: "https://opensource.org/licenses/MIT",
          isAccessibleForFree: true,
          offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
        }),
      },
      {
        type: "application/ld+json",
        children: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: FAQ.map((f) => ({
            "@type": "Question",
            name: f.q,
            acceptedAnswer: { "@type": "Answer", text: f.a },
          })),
        }),
      },
    ],
  }),
  // A download counter is decoration; the homepage is not. Unguarded, a failing
  // count RPC rejected the loader, and on a client-side navigation TanStack
  // Router replaces the whole route with its error component - so a GitHub API
  // hiccup took the landing page down. Null is a value the component already
  // handles by hiding the counter.
  loader: async () => ({ downloads: await getDownloadCount().catch(() => null) }),
  component: Index,
});

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </p>
  );
}

/** Section heading that sticks while its content scrolls past on wide screens. */
function SectionHead({
  eyebrow,
  title,
  id,
  children,
}: {
  eyebrow: string;
  title: string;
  id: string;
  children?: React.ReactNode;
}) {
  return (
    <Reveal className="min-w-0 lg:sticky lg:top-24 lg:self-start">
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2
        id={id}
        className="mt-5 text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.08] tracking-[-0.032em]"
      >
        {title}
      </h2>
      {children ? (
        <div className="mt-5 max-w-[42ch] text-[15.5px] leading-[1.7] text-muted-foreground">
          {children}
        </div>
      ) : null}
    </Reveal>
  );
}

function DownloadButton({ className = "" }: { className?: string }) {
  return (
    <a
      href="/download"
      className={`group inline-flex min-h-12 items-center gap-3 rounded-md bg-accent px-6 text-[15px] font-medium text-accent-foreground shadow-[0_1px_2px_rgba(0,0,0,0.10),0_12px_28px_-14px_rgba(177,78,42,0.7)] transition-all hover:-translate-y-px hover:shadow-[0_2px_4px_rgba(0,0,0,0.10),0_18px_36px_-14px_rgba(177,78,42,0.8)] ${className}`}
    >
      Download for Windows
      <span
        aria-hidden="true"
        className="font-mono text-[11px] opacity-70 transition-transform group-hover:translate-x-0.5"
      >
        {SITE.installerSize} →
      </span>
    </a>
  );
}

function Index() {
  const { downloads } = Route.useLoaderData();
  return (
    <SiteLayout>
      <Hero downloads={downloads} />
      <AnyLaptop />
      <Mechanic />
      <Privacy />
      <Overlay />
      <Details />
      <MixedLanguage />
      <Questions />
      <Requirements />
    </SiteLayout>
  );
}

function Hero({ downloads }: { downloads: number | null }) {
  return (
    <section className="relative overflow-hidden border-b border-border">
      {/* A single soft accent wash behind the headline. Subtle enough to read as
          paper texture rather than as a gradient hero. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-1/4 -top-1/3 h-[70vh] w-[80vw] rounded-full opacity-[0.55] blur-3xl"
        style={{
          background: "radial-gradient(closest-side, var(--accent-soft), transparent 70%)",
        }}
      />
      <div className="relative mx-auto max-w-[1200px] px-6 pb-20 pt-16 md:px-10 md:pb-28 md:pt-24">
        <Reveal>
          <p className="inline-flex items-center gap-2.5 rounded-full border border-border-strong bg-card/80 px-3.5 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
            Windows 10 & 11 · No GPU required
          </p>
        </Reveal>

        <div className="mt-8 grid gap-12 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-end lg:gap-16">
          <div className="min-w-0">
            <Reveal delay={70}>
              <h1 className="max-w-[19ch] text-[clamp(2.6rem,6.4vw,4.7rem)] font-semibold leading-[1.0] tracking-[-0.04em]">
                Speak, and the words land where your cursor is.
              </h1>
            </Reveal>
            <Reveal delay={150}>
              <p className="mt-7 max-w-[54ch] text-[17px] leading-[1.65] text-muted-foreground md:text-[18.5px]">
                Hold a key, talk, let go. Casper Flow transcribes on{" "}
                <span className="text-foreground">the processor you already have</span> and types
                the result into whatever Windows app you were using. No account, no subscription,
                and no audio leaving the machine.
              </p>
            </Reveal>
          </div>

          <Reveal delay={230} className="min-w-0">
            <DownloadButton />
            <p className="mt-4 font-mono text-[11px] leading-relaxed text-muted-foreground">
              v{SITE.version} · {SITE.installerSize} · {SITE.license} licence
            </p>

            {/* Only rendered once real releases exist. See downloads.ts — the
                counter returns null rather than 0 so this stays absent instead of
                advertising that nobody has downloaded it. */}
            {downloads !== null ? (
              <p className="mt-5 flex items-baseline gap-2 border-t border-border pt-5">
                <span className="text-[26px] font-semibold tabular-nums tracking-[-0.02em]">
                  {formatCount(downloads)}
                </span>
                <span className="text-[13.5px] text-muted-foreground">downloads so far</span>
              </p>
            ) : null}
          </Reveal>
        </div>

        <Reveal delay={310} className="mt-16 md:mt-24">
          <DictationScene />
        </Reveal>
      </div>
    </section>
  );
}

/**
 * The CPU section. This is the product's actual thesis, and the page used to bury
 * it in the requirements list as a caveat — "runs on the CPU and does not require
 * a GPU" — phrased like an apology for a missing feature. It is the opposite: the
 * decision that makes the thing usable on the hardware most people own.
 */
const SPECS: Array<[string, string, string]> = [
  ["Processor", "Any 64-bit x86 CPU", "No GPU, no NPU, no dedicated silicon"],
  ["Memory", "~200 MB", "Measured with the speech model loaded"],
  ["Disk", SITE.installedSize, "Both speech models included"],
  ["Speed", `~${ACCURACY.hinglishLatencySeconds}s`, "Per sentence, on a mid-range laptop CPU"],
];

function AnyLaptop() {
  return (
    <section className="border-b border-border bg-surface/60" aria-labelledby="cpu-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
          <SectionHead
            eyebrow="Hardware"
            id="cpu-title"
            title="It runs on the laptop you already own."
          >
            <p>
              Most people do not have a graphics card worth using, and most dictation tools quietly
              assume otherwise — or send the audio to a datacentre GPU and bill you monthly for it.
            </p>
            <p className="mt-4">
              Casper Flow was built the other way round. The models are int8-quantised so they run
              on an ordinary processor at conversational speed, which means a budget laptop, a
              five-year-old office machine or a work desktop with integrated graphics are all
              perfectly adequate.
            </p>
          </SectionHead>

          <div className="min-w-0">
            <Reveal delay={80}>
              <dl className="grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2">
                {SPECS.map(([label, value, note], i) => (
                  <div
                    key={label}
                    className="group bg-card p-6 transition-colors hover:bg-background md:p-7"
                    style={{ transitionDelay: `${i * 20}ms` }}
                  >
                    <dt className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
                      {label}
                    </dt>
                    <dd className="mt-3 text-[24px] font-semibold tracking-[-0.025em] md:text-[27px]">
                      {value}
                    </dd>
                    <dd className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
                      {note}
                    </dd>
                  </div>
                ))}
              </dl>
            </Reveal>

            <Reveal delay={160}>
              <p className="mt-8 border-l-2 border-accent pl-5 text-[16.5px] leading-[1.65]">
                Every speed and accuracy figure on this page was measured on a CPU. There is a
                setting to move the model onto an NVIDIA GPU, and we have deliberately not published
                a number for it — because we have not benchmarked it, and the CPU path is the one
                that has to be good.
              </p>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}

const STEPS = [
  {
    n: "01",
    title: "Hold",
    body: "Hold the configured hotkey for two seconds and dictation starts. The default is Caps Lock, and a quick tap still toggles Caps Lock exactly as it always did — the key keeps its normal job, so nothing you already do with it breaks.",
  },
  {
    n: "02",
    title: "Speak",
    body: "Speak naturally. Casper Flow records locally and a small overlay swells with your voice, so you can see it is listening without anything covering your work.",
  },
  {
    n: "03",
    title: "Release",
    body: "Release the key. Casper Flow finishes transcription and inserts the final text at the cursor, in whichever application has focus.",
  },
];

function Mechanic() {
  return (
    <section className="border-b border-border" aria-labelledby="mechanic-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)] lg:gap-16">
          <SectionHead eyebrow="The mechanic" id="mechanic-title" title="Three movements, one key.">
            <p>
              There is no window to open and no mode to enter. The interaction is the same in Word,
              Slack, VS Code, a browser text field or any other application that accepts text.
            </p>
          </SectionHead>

          <ol className="min-w-0">
            {STEPS.map((s, i) => (
              <Reveal as="li" key={s.n} delay={i * 110}>
                <div className="group grid grid-cols-[auto_minmax(0,1fr)] gap-6 border-t border-border py-8 transition-colors sm:gap-10 md:py-10">
                  <span className="font-mono text-[12px] tabular-nums text-accent transition-transform group-hover:-translate-y-0.5">
                    {s.n}
                  </span>
                  <div className="min-w-0">
                    <h3 className="text-[20px] font-semibold tracking-[-0.02em] md:text-[22px]">
                      {s.title}
                    </h3>
                    <p className="mt-2.5 max-w-[58ch] text-[15.5px] leading-[1.7] text-muted-foreground">
                      {s.body}
                    </p>
                    {i === 0 ? (
                      <div className="mt-5 inline-flex items-center gap-3 rounded-md border border-border-strong bg-card px-3.5 py-2.5">
                        <kbd className="rounded border border-border-strong bg-surface px-2.5 py-1 font-mono text-[11.5px] uppercase tracking-[0.1em]">
                          Caps Lock
                        </kbd>
                        <span className="text-[13px] text-muted-foreground">
                          held two seconds to dictate — a tap still toggles
                        </span>
                      </div>
                    ) : null}
                    {i === 1 ? (
                      <div className="mt-5 max-w-[300px]">
                        <BlobOverlay />
                      </div>
                    ) : null}
                    {i === 2 ? (
                      <div className="mt-5 max-w-[520px] rounded-md border border-border bg-card px-4 py-3.5">
                        <p className="text-[15px] leading-[1.7]">
                          the deposition is scheduled for Thursday morning
                          <span
                            aria-hidden="true"
                            className="ml-[1px] inline-block h-[1.05em] w-[1.5px] translate-y-[0.18em] bg-accent"
                          />
                        </p>
                      </div>
                    ) : null}
                  </div>
                </div>
              </Reveal>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}

function Privacy() {
  return (
    <section className="border-b border-border" aria-labelledby="privacy-title">
      <div className="mx-auto max-w-[1200px] px-6 py-28 md:px-10 md:py-40">
        <Reveal>
          <Eyebrow>Architecture</Eyebrow>
        </Reveal>
        <Reveal delay={80}>
          <h2
            id="privacy-title"
            className="mt-6 max-w-[18ch] text-[clamp(2.1rem,5.2vw,3.9rem)] font-semibold leading-[1.04] tracking-[-0.038em]"
          >
            There is no server to stream your voice to.
          </h2>
        </Reveal>

        <div className="mt-20 grid gap-px overflow-hidden rounded-xl border border-border bg-border md:mt-28 md:grid-cols-2">
          <Reveal delay={120} className="bg-background">
            <div className="h-full px-6 py-10 md:px-10 md:py-14">
              <Eyebrow>Other dictation architecture</Eyebrow>
              {/* Full muted-foreground, not /70. Measured against this
                  background, /70 is 3.36:1 and /40 is 1.87:1, both under the
                  4.5:1 AA minimum — and this smallest text is 15px, so the
                  large-text allowance does not apply. Plain muted-foreground is
                  6.78:1. The arrows are decorative punctuation, so they are also
                  hidden from screen readers rather than read as "right arrow". */}
              <p className="mt-8 text-[clamp(1.15rem,2.2vw,1.6rem)] leading-[1.35] tracking-[-0.02em] text-muted-foreground">
                your voice
                <span aria-hidden="true" className="mx-3 text-muted-foreground/70">
                  →
                </span>
                the network
                <span aria-hidden="true" className="mx-3 text-muted-foreground/70">
                  →
                </span>
                someone else&rsquo;s datacenter
              </p>
              <p className="mt-8 max-w-[40ch] text-[15px] leading-[1.7] text-muted-foreground">
                Audio leaves the machine. What happens next is a matter of policy, and policy can
                change.
              </p>
            </div>
          </Reveal>
          <Reveal delay={200} className="bg-background">
            <div className="h-full border-l-2 border-accent px-6 py-10 md:px-10 md:py-14">
              <Eyebrow>Casper Flow</Eyebrow>
              <p className="mt-8 text-[clamp(1.15rem,2.2vw,1.6rem)] leading-[1.35] tracking-[-0.02em]">
                your voice
                <span className="mx-3 text-accent">→</span>
                your CPU
              </p>
              <p className="mt-8 max-w-[40ch] text-[15px] leading-[1.7] text-muted-foreground">
                The model runs on your own processor. The temporary recording is deleted as soon as
                transcription finishes. Any code path that would send audio or text away from the
                machine is refused, whatever the configuration says.
              </p>
            </div>
          </Reveal>
        </div>

        <div className="mt-20 grid gap-10 md:mt-28 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-20">
          <Reveal delay={80} className="min-w-0">
            <p className="text-[clamp(1.25rem,2.3vw,1.75rem)] leading-[1.4] tracking-[-0.02em]">
              There is nothing to configure and nothing to opt out of, because the infrastructure
              that would need configuring does not exist.
            </p>
          </Reveal>
          <Reveal delay={160} className="min-w-0">
            <ul className="text-[15.5px] leading-[1.7] text-muted-foreground">
              {[
                "No account.",
                "No API key.",
                "No dashboard.",
                "No usage limits.",
                "No sync.",
                "No telemetry.",
                "No network dependency during dictation.",
              ].map((item) => (
                <li
                  key={item}
                  className="flex items-center gap-3 border-b border-border py-3.5 last:border-b-0"
                >
                  <span className="h-1 w-1 shrink-0 rounded-full bg-accent/60" aria-hidden="true" />
                  {item}
                </li>
              ))}
            </ul>
            <p className="mt-8 text-[17px] leading-[1.6] text-foreground">
              It works on a plane with Wi-Fi off. That is not a feature. It is what happens when
              there is no server in the design.
            </p>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Overlay() {
  return (
    <section className="border-b border-border" aria-labelledby="overlay-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
          <SectionHead
            eyebrow="While you dictate"
            id="overlay-title"
            title="You can see it listening."
          >
            <p>
              A small overlay sits above your work while the key is held. Three styles, and the
              default shows no text at all.
            </p>
          </SectionHead>

          <div className="min-w-0 space-y-4">
            {[
              {
                name: "Blob",
                badge: "default",
                body: "A soft shape that swells with your voice. It is driven by the microphone level rather than by transcription, so it stays smooth and tells you nothing you would have to read mid-sentence.",
                visual: <BlobOverlay />,
              },
              {
                name: "Live captions",
                body: "Words appear as you speak them. Off by default, and turning it on downloads a further small model to run the preview — so this is the one style that is not ready the moment you install, and the one that needs the internet once.",
                visual: <LiveCaptionOverlay />,
              },
              {
                name: "Compact bar",
                body: "Microphone level, elapsed time and recording state. The level meter reflects your actual microphone input, not a decorative loop.",
                visual: <CompactBarOverlay />,
              },
            ].map((style, i) => (
              <Reveal key={style.name} delay={i * 90}>
                <div className="grid gap-6 rounded-xl border border-border bg-card p-5 transition-colors hover:border-border-strong sm:grid-cols-[minmax(0,1fr)_240px] sm:items-center md:p-6">
                  <div className="min-w-0">
                    <h3 className="flex items-center gap-2.5 text-[16px] font-semibold">
                      {style.name}
                      {style.badge ? (
                        <span className="rounded border border-accent/30 bg-accent-soft px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-[0.12em] text-accent">
                          {style.badge}
                        </span>
                      ) : null}
                    </h3>
                    <p className="mt-2 max-w-[52ch] text-[14.5px] leading-[1.7] text-muted-foreground">
                      {style.body}
                    </p>
                  </div>
                  <div className="min-w-0">{style.visual}</div>
                </div>
              </Reveal>
            ))}

            <Reveal delay={280}>
              <div className="mt-6 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2">
                <div className="bg-card p-6">
                  <Eyebrow>Preview pass — optional</Eyebrow>
                  <p className="mt-3 text-[15px] leading-[1.7] text-muted-foreground">
                    Only the live-caption style runs one. A second, faster model produces the
                    running text so the overlay keeps up with your voice.
                  </p>
                </div>
                <div className="bg-card p-6">
                  <Eyebrow>Final pass — always</Eyebrow>
                  <p className="mt-3 text-[15px] leading-[1.7] text-muted-foreground">
                    The text that reaches your document comes from a separate full transcription of
                    the complete recording. The preview cannot corrupt the final output.
                  </p>
                </div>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}

function Details() {
  return (
    <section className="border-b border-border bg-surface/60" aria-labelledby="details-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <Reveal>
          <Eyebrow>Engineering</Eyebrow>
          <h2
            id="details-title"
            className="mt-5 max-w-[20ch] text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.08] tracking-[-0.032em]"
          >
            The details matter.
          </h2>
        </Reveal>

        {/* Bento: one wide feature with its illustration, then four supporting
            cards. Uniform rows read as a spec sheet; this gives the section a
            focal point. */}
        <div className="mt-14 grid gap-4 lg:grid-cols-3">
          <Reveal delay={80} className="lg:col-span-2">
            <div className="flex h-full flex-col justify-between gap-8 rounded-xl border border-border bg-card p-6 md:p-9">
              <div>
                <h3 className="max-w-[26ch] text-[22px] font-semibold tracking-[-0.025em] md:text-[26px]">
                  Your clipboard survives dictation.
                </h3>
                <p className="mt-4 max-w-[52ch] text-[15.5px] leading-[1.7] text-muted-foreground">
                  Casper Flow pastes at the cursor, so it briefly needs the clipboard. Before it
                  does, it snapshots whatever you had there — images, HTML, rich text or plain text
                  — and puts it back afterwards. Copying a chart, dictating a sentence and pasting
                  the chart works the way you expect.
                </p>
              </div>
              <div className="max-w-[420px]">
                <ClipboardScene />
              </div>
            </div>
          </Reveal>

          <div className="grid gap-4">
            {[
              [
                "Modifier release",
                "If your hotkey uses modifiers, they are released before pasting, so Ctrl+V does not arrive as Ctrl+Shift+V.",
              ],
              [
                "Clipboard fallback",
                "If another application has the clipboard locked, it types the text directly instead of failing.",
              ],
              [
                "Single instance",
                "It refuses to run twice. One process, one paste — no duplicate insertions.",
              ],
              [
                "Deterministic cleanup",
                "Filler words go via fixed rules, not a model, so nothing can invent words you did not say. Grammar and layout are available, opt-in, with a local model.",
              ],
            ].map(([title, body], i) => (
              <Reveal key={title} delay={140 + i * 70}>
                <div className="h-full rounded-xl border border-border bg-card p-5 transition-colors hover:border-border-strong">
                  <h3 className="text-[15px] font-semibold">{title}</h3>
                  <p className="mt-2 text-[14px] leading-[1.65] text-muted-foreground">{body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function MixedLanguage() {
  return (
    <section className="border-b border-border" aria-labelledby="language-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
          <SectionHead
            eyebrow="Mixed-language dictation"
            id="language-title"
            title="One sentence, two languages."
          >
            <p>
              Many dictation tools ask you to pick a language, then mangle the other one when you
              switch mid-sentence. Casper Flow ships with a Hinglish-tuned model by default and
              handles code-switching as part of normal transcription.
            </p>
            <p className="mt-4">
              Output is Roman script — the way most people type Hindi. Devanagari is available if
              you enable the optional local cleanup model.
            </p>
          </SectionHead>

          <div className="min-w-0">
            <Reveal delay={100}>
              <HinglishScene />
            </Reveal>

            <Reveal delay={180}>
              <div className="mt-8 rounded-xl border border-border-strong bg-card p-6">
                <Eyebrow>Measured, not claimed</Eyebrow>
                <dl className="mt-5 space-y-px">
                  {[
                    {
                      lang: "English",
                      pct: ACCURACY.englishPercent,
                      lat: ACCURACY.englishLatencySeconds,
                      model: ACCURACY.englishModel,
                    },
                    {
                      lang: "Hinglish",
                      pct: ACCURACY.hinglishPercent,
                      lat: ACCURACY.hinglishLatencySeconds,
                      model: ACCURACY.hinglishModel,
                    },
                  ].map(({ lang, pct, lat, model }) => (
                    <div key={lang} className="py-2.5">
                      <div className="flex items-baseline justify-between gap-4">
                        <dt className="text-[14.5px] font-medium">{lang}</dt>
                        <dd className="font-mono text-[13px] tabular-nums text-muted-foreground">
                          {pct}% · ~{lat}s
                        </dd>
                      </div>
                      {/* Which model produced the number. Without this the two
                          figures read as one system scoring differently on two
                          inputs, which is not what was measured. */}
                      <p className="mt-1 font-mono text-[11.5px] text-muted-foreground">{model}</p>
                      {/* The bar makes the 10-point gap between the two visible
                          rather than something you have to work out. */}
                      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-border">
                        <div
                          className="h-full rounded-full bg-accent"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </dl>
                <p className="mt-5 text-[14px] leading-[1.7] text-muted-foreground">
                  Accuracy over a 30-phrase spoken corpus, on a two-core laptop CPU. Each figure is
                  for the model the installer gives you when you pick that language, measured on
                  that kind of speech — they are two models, not one score. We were aiming for{" "}
                  {ACCURACY.hinglishTarget}% on Hinglish and have not reached it. Improving that is
                  the active work, and sending your audio to a cloud API to buy the difference is
                  the one option ruled out.
                </p>
              </div>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}

function Questions() {
  return (
    <section className="border-b border-border" aria-labelledby="faq-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <div className="grid gap-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,8fr)] lg:gap-16">
          <SectionHead eyebrow="Questions" id="faq-title" title="The things people actually ask." />
          <Reveal delay={80} className="min-w-0">
            <FaqList items={FAQ} name="home-faq" />
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function Requirements() {
  return (
    <section aria-labelledby="download-title">
      <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
        <div className="grid gap-12 lg:grid-cols-[minmax(0,6fr)_minmax(0,6fr)] lg:gap-16">
          <Reveal className="min-w-0">
            <Eyebrow>Requirements and download</Eyebrow>
            <h2
              id="download-title"
              className="mt-5 text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.08] tracking-[-0.032em]"
            >
              Download Casper Flow for Windows.
            </h2>
            <p className="mt-5 max-w-[46ch] text-[15.5px] leading-[1.7] text-muted-foreground">
              Windows 10 or 11, 64-bit, and any x86 processor. No GPU. Installs for your account
              only, with no administrator rights and no UAC prompt, and both speech models are
              inside the download — so setup needs no internet connection.
            </p>
            <div className="mt-8">
              <DownloadButton />
            </div>
            <p className="mt-4 max-w-[52ch] text-[14px] leading-[1.7] text-muted-foreground">
              On a machine where you cannot run an installer, there is a{" "}
              <a href="/download/portable" className="text-foreground underline underline-offset-4">
                portable zip
              </a>{" "}
              of the same files ({SITE.portableSize}). It has no Start Menu entry and no uninstaller
              — you delete the folder to remove it.
            </p>
            <dl className="mt-10 border-t border-border font-mono text-[12.5px]">
              {[
                ["Current version", SITE.version],
                ["Installer size", SITE.installerSize],
                ["On disk after install", SITE.installedSize],
                ["Installs to", SITE.installPath],
                ["SHA-256", SITE.sha256],
              ].map(([k, v]) => (
                <div
                  key={k}
                  className="grid grid-cols-[minmax(0,1fr)] gap-1 border-b border-border py-3.5 sm:grid-cols-[170px_minmax(0,1fr)] sm:gap-4"
                >
                  <dt className="uppercase tracking-[0.12em] text-muted-foreground">{k}</dt>
                  <dd className="min-w-0 break-words">{v}</dd>
                </div>
              ))}
            </dl>
          </Reveal>

          <Reveal delay={120} className="min-w-0">
            <div className="rounded-xl border border-border-strong bg-card p-6 md:p-8">
              <h3 className="text-[18px] font-semibold tracking-[-0.02em]">
                This build is not code-signed yet.
              </h3>
              <p className="mt-3 text-[15px] leading-[1.7] text-muted-foreground">
                Because the installer carries no code-signing certificate, Windows may show a
                SmartScreen notice the first time you run it. This is what to do.
              </p>
              <ol className="mt-6 border-t border-border">
                {[
                  "Open the downloaded installer.",
                  "If Windows shows the SmartScreen notice, select More info.",
                  "Select Run anyway.",
                ].map((step, i) => (
                  <li
                    key={step}
                    className="grid grid-cols-[auto_minmax(0,1fr)] gap-4 border-b border-border py-4"
                  >
                    <span className="font-mono text-[12px] tabular-nums text-accent">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="min-w-0 text-[15px] leading-[1.6]">{step}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-6 text-[14.5px] leading-[1.7] text-muted-foreground">
                Verify the download against the SHA-256 above — or the{" "}
                <a
                  href="/download/checksums"
                  className="text-foreground underline underline-offset-4"
                >
                  published checksums
                </a>{" "}
                — check what{" "}
                {/*
                  A VirusTotal report addressed by file hash, not by upload. The
                  URL is the checksum we already publish, so it needs nothing
                  maintained: whatever engines have scanned this exact build is
                  what the visitor sees, including the false positives we warn
                  about in the next sentence. Linking it is the point - telling
                  someone antivirus may flag a download and then not showing them
                  the scan is asking them to take it on trust.
                */}
                <a
                  href={`https://www.virustotal.com/gui/file/${SITE.sha256}`}
                  rel="nofollow noopener"
                  className="text-foreground underline underline-offset-4"
                >
                  antivirus engines say about it
                </a>
                , and read the source before installing. Windows Defender sometimes quarantines this
                kind of program outright, because dictation requires watching the keyboard and that
                is what a keylogger does too. We would rather tell you that here than have you find
                out.
              </p>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  );
}
