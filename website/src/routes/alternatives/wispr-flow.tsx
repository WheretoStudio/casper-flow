import { createFileRoute, Link } from "@tanstack/react-router";
import { SiteLayout } from "@/components/site/SiteLayout";
import { Reveal } from "@/components/site/Reveal";
import { FaqList, type QA } from "@/components/site/Faq";
import { ACCURACY, SITE, url } from "@/components/site/constants";

/**
 * A comparison page, written to be useful to somebody deciding rather than to
 * win an argument.
 *
 * Two rules were applied throughout:
 *
 * 1. Every claim about Wispr Flow is sourced from Wispr Flow's own published
 *    pages, linked inline. A comparison page that gets a competitor's pricing
 *    wrong discredits everything else on the site, and this site's whole pitch
 *    is that its claims are checkable.
 * 2. There is a section on what they do better, and it is not a token one. They
 *    are cross-platform, they support far more languages, and they are almost
 *    certainly more accurate. Pretending otherwise would be the kind of thing a
 *    reader spots immediately.
 */

/**
 * The questions, in one place.
 *
 * Rendered on the page *and* emitted as FAQPage structured data, from this single
 * array — the same arrangement the homepage uses. They were previously only in the
 * JSON-LD and appeared nowhere in the page, which is against Google's own
 * structured-data policy: FAQPage markup has to describe content the visitor can
 * actually see. Markup that describes invisible content gets the page's rich
 * results dropped at best.
 */
const FAQ: readonly QA[] = [
  {
    q: "Is there a free open-source alternative to Wispr Flow?",
    a: "Casper Flow is free and MIT-licensed, with no subscription and no word limits. It runs speech recognition on your own Windows PC instead of in the cloud. It is Windows-only, and it supports two languages rather than a hundred.",
  },
  {
    q: "Does Wispr Flow work offline?",
    a: "No. Wispr Flow processes dictation in the cloud, so it needs an internet connection. Casper Flow runs entirely on your own CPU and works with the network disconnected.",
  },
  {
    q: "Is Wispr Flow free?",
    a: "Wispr Flow has a free Basic tier limited to 2,000 words per week on Mac and Windows, and a Pro plan at 15 US dollars per month, or 12 per month billed annually, according to its own pricing page.",
  },
];

const PATH = "/alternatives/wispr-flow";
const TITLE = "Free open-source alternative to Wispr Flow — Casper Flow";
const DESCRIPTION =
  "Casper Flow is a free, open-source, offline dictation app for Windows. No subscription, no word limits, and your audio never leaves your computer. An honest comparison with Wispr Flow, including what Wispr Flow does better.";

export const Route = createFileRoute("/alternatives/wispr-flow")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:type", content: "article" },
      { property: "og:url", content: url(PATH) },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: url(PATH) }],
    scripts: [
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
  component: WisprFlowComparison,
});

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
      {children}
    </p>
  );
}

function Source({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      rel="nofollow noopener"
      className="underline decoration-border-strong underline-offset-4 transition-colors hover:decoration-foreground"
    >
      {children}
    </a>
  );
}

const ROWS: Array<[string, string, string]> = [
  [
    "Price",
    "Free, forever. MIT licensed.",
    "Free tier capped; Pro $15/mo, or $12/mo billed annually",
  ],
  ["Word limits", "None", "2,000 words per week on the free Basic tier"],
  ["Where speech is processed", "On your own CPU", "In the cloud"],
  ["Works offline", "Yes, including installation", "No — needs a connection"],
  ["Account required", "No", "Yes"],
  ["Platforms", "Windows 10 and 11", "Windows, macOS, iPhone"],
  ["Languages", "English and Hinglish", "100+"],
  ["Source code", "Public, MIT", "Proprietary"],
  ["Telemetry", "None", "Configurable; see their data controls"],
];

function WisprFlowComparison() {
  return (
    <SiteLayout>
      <article>
        <section className="border-b border-border">
          <div className="mx-auto max-w-[1200px] px-6 pb-20 pt-16 md:px-10 md:pb-28 md:pt-24">
            <Reveal>
              <Eyebrow>Comparison</Eyebrow>
            </Reveal>
            <Reveal delay={80}>
              <h1 className="mt-6 max-w-[24ch] text-[clamp(2.2rem,5.4vw,3.9rem)] font-semibold leading-[1.04] tracking-[-0.035em]">
                A free, open-source alternative to Wispr Flow.
              </h1>
            </Reveal>
            <Reveal delay={160}>
              <p className="mt-7 max-w-[62ch] text-[17px] leading-[1.65] text-muted-foreground md:text-[18.5px]">
                Both let you hold a key, talk, and have the text appear where your cursor is. The
                difference is where your voice goes. Wispr Flow sends it to a server; Casper Flow
                does the recognition on your own processor, and costs nothing because there is no
                server to pay for.
              </p>
            </Reveal>

            <Reveal delay={240}>
              <div className="mt-10 rounded-lg border border-border-strong bg-card p-6 md:p-8">
                <Eyebrow>The short version</Eyebrow>
                <div className="mt-5 grid gap-6 md:grid-cols-2 md:gap-10">
                  <div>
                    <h2 className="text-[16px] font-semibold">Pick Casper Flow if</h2>
                    <p className="mt-2 max-w-[46ch] text-[15px] leading-[1.7] text-muted-foreground">
                      You are on Windows, you dictate in English or Hinglish, and you would rather
                      your audio never left the machine — or you simply do not want a subscription
                      or a word cap.
                    </p>
                  </div>
                  <div>
                    <h2 className="text-[16px] font-semibold">Pick Wispr Flow if</h2>
                    <p className="mt-2 max-w-[46ch] text-[15px] leading-[1.7] text-muted-foreground">
                      You need a Mac or iPhone, you dictate in one of the many languages we do not
                      support, or you want the most accurate result available and are willing to
                      send audio to a server and pay monthly for it.
                    </p>
                  </div>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        <section className="border-b border-border" aria-labelledby="table-title">
          <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
            <Reveal>
              <h2
                id="table-title"
                className="text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.1] tracking-[-0.03em]"
              >
                Side by side.
              </h2>
              <p className="mt-4 max-w-[62ch] text-[15.5px] leading-[1.7] text-muted-foreground">
                Wispr Flow's figures come from its own{" "}
                <Source href="https://wisprflow.ai/pricing">pricing page</Source> and{" "}
                <Source href="https://wisprflow.ai/data-controls">data controls page</Source>.
                Pricing changes; check theirs before deciding.
              </p>
            </Reveal>

            <Reveal delay={80} className="mt-10 overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-left">
                <caption className="sr-only">
                  Feature comparison between Casper Flow and Wispr Flow
                </caption>
                <thead>
                  <tr className="border-b border-border-strong">
                    <th
                      scope="col"
                      className="py-3 pr-4 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                    >
                      &nbsp;
                    </th>
                    <th scope="col" className="py-3 pr-4 text-[15px] font-semibold">
                      Casper Flow
                    </th>
                    <th
                      scope="col"
                      className="py-3 text-[15px] font-semibold text-muted-foreground"
                    >
                      Wispr Flow
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ROWS.map(([label, ours, theirs]) => (
                    <tr key={label} className="border-b border-border align-top">
                      <th
                        scope="row"
                        className="w-[26%] py-4 pr-4 text-[14px] font-medium text-muted-foreground"
                      >
                        {label}
                      </th>
                      <td className="w-[37%] py-4 pr-4 text-[15px] leading-[1.6]">{ours}</td>
                      <td className="w-[37%] py-4 text-[15px] leading-[1.6] text-muted-foreground">
                        {theirs}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Reveal>
          </div>
        </section>

        <section className="border-b border-border bg-surface/60" aria-labelledby="honest-title">
          <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
            <div className="grid gap-12 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16">
              <Reveal className="min-w-0">
                <Eyebrow>Not a sales pitch</Eyebrow>
                <h2
                  id="honest-title"
                  className="mt-5 text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.1] tracking-[-0.03em]"
                >
                  What Wispr Flow does better.
                </h2>
                <p className="mt-5 max-w-[46ch] text-[15.5px] leading-[1.7] text-muted-foreground">
                  It is a well-made product with a funded team behind it. If this page pretended
                  otherwise you would be right to distrust the rest of it.
                </p>
              </Reveal>
              <Reveal delay={100} className="min-w-0">
                <dl>
                  {[
                    [
                      "Languages",
                      "They support over a hundred. We support two: English, and Hindi-English mixed. If you dictate in Spanish, Japanese or German, we are not an option at all.",
                    ],
                    [
                      "Accuracy",
                      `A large cloud model on a datacentre GPU will beat a quantised model on your laptop CPU. Our English figure is ${ACCURACY.englishPercent}% and our Hinglish figure is ${ACCURACY.hinglishPercent}%, both measured on a small corpus. We do not claim to beat them.`,
                    ],
                    [
                      "Mac and iPhone",
                      "We are Windows-only and have no plans to change that. They run on macOS and iOS as well.",
                    ],
                    [
                      "Rewriting and formatting",
                      "Theirs works out of the box. Ours is off by default and needs you to install a local model (Ollama) first — we will fix grammar and lay text out as a message or an email, but only when you ask for it, because a model in that position once pasted its own prompt into a document.",
                    ],
                    [
                      "Teams and compliance",
                      "They offer team billing, an enterprise tier and third-party security attestations. We are an MIT-licensed project with a public repository and no company behind it.",
                    ],
                  ].map(([title, body]) => (
                    <div key={title} className="border-t border-border py-6">
                      <dt className="text-[15.5px] font-semibold">{title}</dt>
                      <dd className="mt-2 max-w-[62ch] text-[15px] leading-[1.7] text-muted-foreground">
                        {body}
                      </dd>
                    </div>
                  ))}
                </dl>
              </Reveal>
            </div>
          </div>
        </section>

        <section className="border-b border-border" aria-labelledby="privacy-title">
          <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
            <Reveal>
              <Eyebrow>The actual difference</Eyebrow>
              <h2
                id="privacy-title"
                className="mt-5 max-w-[22ch] text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.1] tracking-[-0.03em]"
              >
                Cloud dictation is a policy. Local dictation is an architecture.
              </h2>
            </Reveal>
            <div className="mt-10 grid gap-10 lg:grid-cols-2 lg:gap-16">
              <Reveal delay={80} className="min-w-0">
                <p className="max-w-[58ch] text-[16px] leading-[1.7] text-muted-foreground">
                  Wispr Flow is not careless with your data. It publishes a subprocessor list, and
                  it has a <Source href="https://wisprflow.ai/data-controls">Privacy Mode</Source>{" "}
                  that stops your dictation being used to train models. Its terms also note that
                  cloud sync is a separate thing from that mode.
                </p>
                <p className="mt-4 max-w-[58ch] text-[16px] leading-[1.7] text-muted-foreground">
                  All of that is a promise about what a company will do with audio it already has.
                  Promises are made in good faith and can still be changed by a new owner, a new
                  jurisdiction or a breach.
                </p>
              </Reveal>
              <Reveal delay={160} className="min-w-0">
                <p className="max-w-[58ch] text-[16px] leading-[1.7]">
                  Casper Flow makes no promise about handling your audio, because it never has it.
                  There is no account, no server and no endpoint. The cloud client libraries are
                  excluded from the build, so the program on your disk is not capable of reaching a
                  transcription API — not configured not to, incapable of it.
                </p>
                <p className="mt-4 max-w-[58ch] text-[16px] leading-[1.7] text-muted-foreground">
                  You do not have to believe that. It is{" "}
                  <Source href={SITE.repoUrl}>a few hundred lines of Python</Source> and you can
                  read the parts that touch your microphone and your keyboard in an afternoon.
                </p>
              </Reveal>
            </div>
          </div>
        </section>

        {/* The same array that produces this page's FAQPage structured data. */}
        <section className="border-b border-border" aria-labelledby="wispr-faq-title">
          <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
            <Reveal>
              <Eyebrow>Questions</Eyebrow>
              <h2
                id="wispr-faq-title"
                className="mt-4 max-w-[26ch] text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.1] tracking-[-0.03em]"
              >
                What people ask before switching.
              </h2>
            </Reveal>
            <Reveal delay={100}>
              <div className="mt-10 max-w-[860px]">
                <FaqList items={FAQ} name="wispr-faq" />
              </div>
            </Reveal>
          </div>
        </section>

        <section aria-labelledby="cta-title">
          <div className="mx-auto max-w-[1200px] px-6 py-20 md:px-10 md:py-28">
            <Reveal>
              <h2
                id="cta-title"
                className="max-w-[24ch] text-[clamp(1.75rem,3.4vw,2.5rem)] font-semibold leading-[1.1] tracking-[-0.03em]"
              >
                Try it. There is nothing to cancel.
              </h2>
              <p className="mt-5 max-w-[56ch] text-[15.5px] leading-[1.7] text-muted-foreground">
                {SITE.installerSize}, installs for your account only with no administrator rights,
                and both speech models are inside the download — so it works before you have a
                connection.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <a
                  href="/download"
                  className="group inline-flex min-h-12 items-center gap-3 rounded-md bg-accent px-6 text-[15px] font-medium text-accent-foreground shadow-[0_1px_2px_rgba(0,0,0,0.10),0_12px_28px_-14px_rgba(177,78,42,0.7)] transition-all hover:-translate-y-px"
                >
                  Download for Windows
                  <span aria-hidden="true" className="font-mono text-[11px] opacity-70">
                    {SITE.installerSize} →
                  </span>
                </a>
                <Link
                  to="/"
                  className="inline-flex min-h-11 items-center rounded-md border border-border-strong bg-card px-5 text-[14.5px] font-medium transition-colors hover:bg-surface"
                >
                  How it works
                </Link>
              </div>
              <p className="mt-6 max-w-[56ch] text-[13.5px] leading-[1.7] text-muted-foreground">
                Wispr Flow is a trademark of Wispr AI, Inc. This page is not affiliated with or
                endorsed by them, and its claims about their product are drawn from their own
                published documentation on the dates linked above.
              </p>
            </Reveal>
          </div>
        </section>
      </article>
    </SiteLayout>
  );
}
