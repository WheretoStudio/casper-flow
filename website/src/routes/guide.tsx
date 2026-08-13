import { createFileRoute, Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { SiteLayout } from "@/components/site/SiteLayout";
import { Reveal } from "@/components/site/Reveal";
import { SITE, url } from "@/components/site/constants";
import { FaqList, type QA } from "@/components/site/Faq";
import { BlobOverlay } from "@/components/site/visuals";
import {
  InstallerDisclosureMock,
  SettingsMock,
  SmartScreenMock,
  TrayMock,
  WizardPracticeMock,
} from "@/components/site/guide-visuals";

/**
 * /guide — the whole path from "I have not downloaded it" to "I am dictating".
 *
 * Written because the homepage sells and does not teach, and the gap between
 * those two is where a non-technical user gives up. Three moments account for
 * almost all of that: the SmartScreen warning, which looks like the software is
 * dangerous; the disclosure screen, which looks alarming precisely because it is
 * honest; and the first dictation, where holding a key for two seconds is not
 * something anyone guesses.
 *
 * Structured as a numbered walkthrough with a sticky contents list, so it can be
 * read start to finish or jumped into at the step someone is stuck on. Emits
 * schema.org HowTo, which is what lets a search engine show the steps directly.
 */

const PATH = "/guide";
const TITLE = "How to download, install and use Casper Flow — full guide";
const DESCRIPTION =
  "A complete walkthrough: downloading Casper Flow, getting past the SmartScreen warning, the seven installer screens, first-run setup, your first dictation, the settings worth changing, and what to do when something goes wrong.";

const STEPS: Array<{
  id: string;
  n: string;
  title: string;
  minutes?: string;
  body: ReactNode;
  visual?: ReactNode;
}> = [
  {
    id: "download",
    n: "01",
    title: "Download the installer",
    minutes: "1 min",
    body: (
      <>
        <p>
          The download is a single file, <strong>CasperFlowSetup.exe</strong>, and it is{" "}
          {SITE.installerSize}. That is larger than most installers because the two speech models
          are inside it — which is what lets the app work without an internet connection, including
          while you are setting it up.
        </p>
        <p>
          You do not need an account, a licence key or an email address. There is nothing to sign up
          for.
        </p>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <a
            href="/download"
            className="group inline-flex min-h-12 items-center gap-3 rounded-md bg-accent px-6 text-[15px] font-medium text-accent-foreground shadow-[0_1px_2px_rgba(0,0,0,0.10),0_12px_28px_-14px_rgba(177,78,42,0.7)] transition-all hover:-translate-y-px"
          >
            Download for Windows
            <span aria-hidden="true" className="font-mono text-[11px] opacity-70">
              {SITE.installerSize} →
            </span>
          </a>
          <a
            href="/download/checksums"
            className="text-[14px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            Verify the checksum
          </a>
        </div>
        <p className="mt-6 text-[14px]">
          On a locked-down machine where installers are blocked, take the{" "}
          <a href="/download/portable">portable zip</a> ({SITE.portableSize}) instead, unzip it
          anywhere and run <span className="font-mono text-[13px]">CasperFlow.exe</span> from inside
          the folder. You lose the Start Menu entry and the uninstaller; everything else is
          identical.
        </p>
      </>
    ),
  },
  {
    id: "smartscreen",
    n: "02",
    title: "Get past the Windows warning",
    minutes: "10 sec",
    body: (
      <>
        <p>
          When you open the installer, Windows will probably show a blue box saying it protected
          your PC.{" "}
          <strong>
            This is expected, and it is worth understanding rather than just clicking through.
          </strong>
        </p>
        <p>
          Windows shows it because the installer carries no code-signing certificate. A certificate
          that would remove this warning costs a few hundred dollars a year; this project does not
          have one yet. The warning means Windows does not recognise the publisher — not that it
          found anything wrong with the file.
        </p>
        <ul>
          <li>
            Click <strong>More info</strong>. The dialog expands.
          </li>
          <li>
            Click <strong>Run anyway</strong>.
          </li>
        </ul>
        <p>
          If you would rather check the file before trusting it, compare its SHA-256 against the{" "}
          <a href="/download/checksums">published checksums</a>. In PowerShell:
        </p>
        <pre className="mt-3 overflow-x-auto rounded-md border border-border bg-surface px-4 py-3 font-mono text-[12.5px] leading-relaxed">
          Get-FileHash .\CasperFlowSetup.exe -Algorithm SHA256
        </pre>
      </>
    ),
    visual: <SmartScreenMock />,
  },
  {
    id: "install",
    n: "03",
    title: "Work through the installer",
    minutes: "2 min",
    body: (
      <>
        <p>
          Seven screens, and <strong>no administrator password at any point</strong>. Casper Flow
          installs for your account only, into{" "}
          <span className="font-mono text-[13.5px]">{SITE.installPath}</span>, which is why there is
          no UAC prompt and why it works on a managed work laptop.
        </p>
        <ol className="mt-5 space-y-2.5">
          {[
            ["1", "Welcome", "What it does, and that it works offline."],
            ["2", "Licence", "MIT. Accept it."],
            ["3", "What this app does to your system", "The one screen worth reading. See below."],
            ["4", "How you talk", "English only, or Hindi and English mixed."],
            ["5", "Location and startup", "Where it goes, and whether it starts when you sign in."],
            ["6", "Installing", "Copies files. No downloading — the models are already there."],
            ["7", "Finished", "Leave the box ticked and it launches."],
          ].map(([n, name, note]) => (
            <li key={n} className="flex gap-4 border-b border-border pb-2.5 last:border-b-0">
              <span className="font-mono text-[11.5px] tabular-nums text-accent">{n}</span>
              <span className="min-w-0">
                <span className="text-[14.5px] font-medium text-foreground">{name}</span>
                <span className="ml-2 text-[14px] text-muted-foreground">{note}</span>
              </span>
            </li>
          ))}
        </ol>
        <p className="mt-5">
          <strong>Screen 3 is deliberately blunt.</strong> It tells you that the app installs a
          global keyboard hook, that this is the same Windows mechanism a keylogger uses, and that
          antivirus software sometimes flags it. That is disclosed up front rather than buried in a
          licence agreement, because a dictation tool has to watch the keyboard to notice your key,
          and you should decide whether you are comfortable with that before anything is written to
          disk.
        </p>
        <p>
          The screen also links to the source. Two short files —{" "}
          <span className="font-mono text-[13.5px]">hotkey.py</span> and{" "}
          <span className="font-mono text-[13.5px]">paste.py</span> — are all the code that touches
          your keyboard.
        </p>
      </>
    ),
    visual: <InstallerDisclosureMock />,
  },
  {
    id: "setup",
    n: "04",
    title: "Finish first-run setup",
    minutes: "2 min",
    body: (
      <>
        <p>
          The first time it starts, a short setup runs. Four steps, and each one{" "}
          <strong>proves something works</strong> rather than just telling you about it:
        </p>
        <ul>
          <li>
            <strong>Microphone.</strong> Say anything; the bar has to move before you can continue.
            If it stays flat, pick a different microphone from the list.
          </li>
          <li>
            <strong>Your key.</strong> Caps Lock by default. Press whatever you would rather use.
          </li>
          <li>
            <strong>How you talk.</strong> English, or Hindi and English mixed. Both models are
            already installed, so switching is instant.
          </li>
          <li>
            <strong>One real dictation.</strong> You cannot finish without a sentence actually
            landing in the box — and it goes through the whole pipeline, not a simulation.
          </li>
        </ul>
        <p>
          If you skip setup, it will not nag you again. You can reopen it later from the tray icon.
        </p>
      </>
    ),
    visual: <WizardPracticeMock />,
  },
  {
    id: "dictate",
    n: "05",
    title: "Dictate your first sentence",
    minutes: "30 sec",
    body: (
      <>
        <p>
          There is no window to open and no button to press. Click into any text box — Word, Slack,
          Chrome, an email, a code editor — and:
        </p>
        <ol className="my-5 space-y-4">
          {[
            [
              "Hold Caps Lock for two seconds",
              "Keep holding it. The two-second delay is deliberate: it means a quick tap still toggles Caps Lock the way it always did, so the key keeps its normal job.",
            ],
            [
              "Talk normally",
              "A small red shape appears near the bottom of your screen and moves with your voice. That is how you know it is listening. It does not cover what you are working on.",
            ],
            [
              "Let go",
              "A moment later the text appears at your cursor. About a second for a normal sentence.",
            ],
          ].map(([t, d], i) => (
            <li key={t} className="flex gap-5">
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full border border-accent/30 bg-accent-soft font-mono text-[12px] text-accent">
                {i + 1}
              </span>
              <span className="min-w-0">
                <span className="block text-[15.5px] font-medium text-foreground">{t}</span>
                <span className="mt-1 block max-w-[58ch] text-[15px] leading-[1.7]">{d}</span>
              </span>
            </li>
          ))}
        </ol>
        <p>
          <strong>Speak punctuation out loud</strong> and it becomes punctuation. These work as
          spoken words anywhere in a sentence:
        </p>
        <div className="mt-4 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
          {[
            ["“full stop” or “period”", "."],
            ["“comma”", ","],
            ["“question mark”", "?"],
            ["“exclamation mark”", "!"],
            ["“colon” / “semicolon”", ": ;"],
            ["“open bracket” / “close bracket”", "( )"],
            ["“new line”", "line break"],
            ["“new paragraph”", "blank line"],
          ].map(([said, becomes]) => (
            <div
              key={said}
              className="flex items-baseline justify-between gap-4 bg-card px-4 py-2.5"
            >
              <span className="text-[14px]">{said}</span>
              <span className="font-mono text-[13px] text-accent">{becomes}</span>
            </div>
          ))}
        </div>
        <p className="mt-5">
          Filler words — um, uh, hmm — are removed by fixed rules, not by a model, so nothing can
          invent words you did not say. Your clipboard is put back exactly as it was afterwards.
        </p>
      </>
    ),
    visual: (
      <div className="rounded-xl border border-border bg-surface p-6">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
          What you see while talking
        </p>
        <div className="mt-4">
          <BlobOverlay />
        </div>
        <p className="mt-4 text-[13.5px] leading-relaxed text-muted-foreground">
          The default overlay. It tracks your microphone level rather than the words, so there is
          nothing to read mid-sentence. Two other styles are available, including live captions.
        </p>
      </div>
    ),
  },
  {
    id: "tray",
    n: "06",
    title: "Find it again afterwards",
    body: (
      <>
        <p>
          Casper Flow has no main window. It lives in the notification area next to the clock — you
          may need to click the <span className="font-mono">^</span> arrow to see it. Right-click
          the icon for settings, diagnostics, the log, launch-at-login and quit.
        </p>
        <p>
          If your key stops working, the usual cause is that the app is not running. Start it from
          the Start Menu and look for the icon.
        </p>
      </>
    ),
    visual: <TrayMock />,
  },
  {
    id: "settings",
    n: "07",
    title: "Change the things worth changing",
    body: (
      <>
        <p>Most people touch three settings and nothing else:</p>
        <ul>
          <li>
            <strong>The key.</strong> If Caps Lock is awkward, or you use it, pick another.
          </li>
          <li>
            <strong>Hold time.</strong> Two seconds is the default. Shorten it if you find it slow;
            lengthen it if dictation starts when you did not mean it to.
          </li>
          <li>
            <strong>Your words.</strong> Add names, places and jargon it keeps getting wrong. Proper
            nouns are the weakest thing speech recognition does, and this is the direct fix.
          </li>
        </ul>
        <p>
          <strong>Accuracy &amp; speed</strong> lets you switch between the English-only and mixed
          Hindi-English models. English-only is more accurate if you never mix languages, and cannot
          transcribe Hindi at all. <strong>Appearance</strong> switches the overlay style and where
          it sits. <strong>Diagnostics</strong> runs the same self-check the installer does and
          reports exactly what it found.
        </p>
      </>
    ),
    visual: <SettingsMock />,
  },
];

const TROUBLE: readonly QA[] = [
  {
    q: "Windows Defender deleted the file",
    a: "This does happen. Dictation needs a global keyboard hook, which is the same mechanism a keylogger uses, so Defender and other antivirus software sometimes flag the download as a hacking tool or a keylogger. It is a false positive caused by how the app watches the keyboard and how it is packaged. You can restore the file from Protection History and add an exclusion for the install folder if you are comfortable doing so. We will never suggest turning Defender off.",
  },
  {
    q: "Nothing happens when I hold the key",
    a: "Check the app is running — look for the microphone icon in the notification area near the clock, behind the ^ arrow if necessary. Then check you are holding the key for a full two seconds; a shorter press is treated as a normal keypress on purpose. If it is running and the key is right, open Settings, then Diagnostics, and read what it reports.",
  },
  {
    q: "My Caps Lock stopped working",
    a: "A quick tap should still toggle Caps Lock normally. If the light is stuck on or off, quit Casper Flow from the tray icon and press Caps Lock once to resync it. The app suppresses the key while it is held so your typing does not turn uppercase mid-dictation, and a crash while suppressed can leave the state confused.",
  },
  {
    q: "The bar does not move when I speak",
    a: "Windows may not be letting the app use the microphone. Open Windows Settings, then Privacy & security, then Microphone, and make sure desktop apps are allowed. If you have more than one input, pick the right one in the setup step or in Settings. A headset that is connected but not selected is the most common cause.",
  },
  {
    q: "The text went into the wrong window",
    a: "Text is pasted wherever the cursor is, so whichever window had focus when you released the key is where it lands. If you click into another application mid-dictation, that is where the text goes. Click where you want the text before you start holding.",
  },
  {
    q: "It gets a name or a technical term wrong every time",
    a: "Add it under Settings, then Words. Names are the weakest category in any speech model, and the vocabulary list exists for exactly this. There is also a corrections list for the case where it reliably hears one specific wrong thing.",
  },
  {
    q: "How do I uninstall it?",
    a: "Windows Settings, then Apps, then Casper Flow — or the Start Menu entry. It asks separately before deleting your settings and any models you downloaded, because those are yours. Uninstalling removes the keyboard hook and the launch-at-login entry with it.",
  },
];

export const Route = createFileRoute("/guide")({
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
      // There is deliberately no HowTo block here.
      //
      // Google retired HowTo rich results in September 2023, so it buys no search
      // appearance. And the version that used to be here could not be made valid:
      // `text` is required on every HowToStep and was absent, while each step's
      // instructions live in `body` as JSX, which cannot be serialised into JSON.
      // It also carried a `totalTime` of PT6M that nobody had timed and a
      // `supply: []` that asserted nothing. Invalid markup describing invented
      // durations is worse than no markup, so it is gone. The FAQPage below is
      // valid, is still supported, and describes content the page actually shows.
      {
        type: "application/ld+json",
        children: JSON.stringify({
          "@context": "https://schema.org",
          "@type": "FAQPage",
          mainEntity: TROUBLE.map((f) => ({
            "@type": "Question",
            name: f.q,
            acceptedAnswer: { "@type": "Answer", text: f.a },
          })),
        }),
      },
    ],
  }),
  component: GuidePage,
});

function GuidePage() {
  return (
    <SiteLayout>
      <article>
        <section className="relative overflow-hidden border-b border-border">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-1/4 -top-1/2 h-[60vh] w-[70vw] rounded-full opacity-50 blur-3xl"
            style={{
              background: "radial-gradient(closest-side, var(--accent-soft), transparent 70%)",
            }}
          />
          <div className="relative mx-auto max-w-[1200px] px-6 pb-16 pt-14 md:px-10 md:pb-24 md:pt-20">
            <Reveal>
              <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                Guide · {SITE.version}
              </p>
            </Reveal>
            <Reveal delay={70}>
              <h1 className="mt-5 max-w-[22ch] text-[clamp(2.2rem,5.4vw,3.9rem)] font-semibold leading-[1.04] tracking-[-0.038em]">
                From download to your first sentence.
              </h1>
            </Reveal>
            <Reveal delay={140}>
              <p className="mt-6 max-w-[60ch] text-[17px] leading-[1.65] text-muted-foreground md:text-[18px]">
                Every screen you will see, in order, including the two that look alarming and are
                not. No prior knowledge assumed, and nothing skipped. About six minutes end to end.
              </p>
            </Reveal>
            <Reveal delay={210}>
              <dl className="mt-10 grid max-w-[640px] gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-3">
                {[
                  ["Time needed", "~6 min"],
                  ["Admin rights", "Not needed"],
                  ["Internet", "Not needed"],
                ].map(([k, v]) => (
                  <div key={k} className="bg-card px-5 py-4">
                    <dt className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
                      {k}
                    </dt>
                    <dd className="mt-1.5 text-[17px] font-semibold tracking-[-0.02em]">{v}</dd>
                  </div>
                ))}
              </dl>
            </Reveal>
          </div>
        </section>

        <div className="mx-auto max-w-[1200px] px-6 py-16 md:px-10 md:py-24">
          <div className="grid gap-14 lg:grid-cols-[minmax(0,220px)_minmax(0,1fr)] lg:gap-20">
            <nav aria-label="Steps" className="lg:sticky lg:top-24 lg:self-start">
              <h2 className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
                Steps
              </h2>
              <ol className="mt-4 space-y-1">
                {STEPS.map((s) => (
                  <li key={s.id}>
                    <a
                      href={`#${s.id}`}
                      className="group flex gap-3 rounded py-1.5 text-[13.5px] leading-snug text-muted-foreground transition-colors hover:text-foreground"
                    >
                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground group-hover:text-accent">
                        {s.n}
                      </span>
                      <span className="min-w-0">{s.title}</span>
                    </a>
                  </li>
                ))}
                <li className="pt-2">
                  <a
                    href="#trouble"
                    className="group flex gap-3 rounded py-1.5 text-[13.5px] leading-snug text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <span className="font-mono text-[11px] text-muted-foreground group-hover:text-accent">
                      ?
                    </span>
                    <span>If something goes wrong</span>
                  </a>
                </li>
              </ol>
            </nav>

            <div className="min-w-0">
              {STEPS.map((s) => (
                <section
                  key={s.id}
                  id={s.id}
                  className="scroll-mt-24 border-t border-border py-12 first:border-t-0 first:pt-0"
                >
                  <Reveal>
                    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
                      <span className="font-mono text-[12px] tabular-nums text-accent">{s.n}</span>
                      <h2 className="text-[clamp(1.4rem,2.6vw,1.85rem)] font-semibold tracking-[-0.028em]">
                        {s.title}
                      </h2>
                      {s.minutes ? (
                        <span className="rounded-full border border-border-strong px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                          {s.minutes}
                        </span>
                      ) : null}
                    </div>
                  </Reveal>

                  <div className="mt-6 grid gap-10 xl:grid-cols-[minmax(0,1fr)_minmax(0,420px)] xl:gap-12">
                    <Reveal delay={60}>
                      <div className="max-w-[64ch] space-y-4 text-[15.5px] leading-[1.75] text-muted-foreground [&_a]:text-foreground [&_a]:underline [&_a]:underline-offset-4 [&_li]:pl-1 [&_strong]:font-semibold [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:space-y-2.5 [&_ul]:pl-5">
                        {s.body}
                      </div>
                    </Reveal>
                    {s.visual ? (
                      <Reveal delay={140} className="min-w-0">
                        <div className="xl:sticky xl:top-24">{s.visual}</div>
                      </Reveal>
                    ) : null}
                  </div>
                </section>
              ))}

              <section id="trouble" className="scroll-mt-24 border-t border-border py-12">
                <Reveal>
                  <div className="flex items-baseline gap-4">
                    <span className="font-mono text-[12px] text-accent">?</span>
                    <h2 className="text-[clamp(1.4rem,2.6vw,1.85rem)] font-semibold tracking-[-0.028em]">
                      If something goes wrong
                    </h2>
                  </div>
                  <p className="mt-4 max-w-[62ch] text-[15.5px] leading-[1.75] text-muted-foreground">
                    In rough order of how often it happens.
                  </p>
                </Reveal>
                <Reveal delay={80} className="mt-8">
                  <FaqList items={TROUBLE} name="guide-trouble" />
                </Reveal>
              </section>

              <section className="border-t border-border py-12">
                <Reveal>
                  <h2 className="text-[clamp(1.4rem,2.6vw,1.85rem)] font-semibold tracking-[-0.028em]">
                    That is the whole thing.
                  </h2>
                  <p className="mt-4 max-w-[58ch] text-[15.5px] leading-[1.75] text-muted-foreground">
                    Hold a key, talk, let go. Everything else is optional.
                  </p>
                  <div className="mt-7 flex flex-wrap items-center gap-3">
                    <a
                      href="/download"
                      className="inline-flex min-h-12 items-center gap-3 rounded-md bg-accent px-6 text-[15px] font-medium text-accent-foreground transition-transform hover:-translate-y-px"
                    >
                      Download for Windows
                      <span aria-hidden="true" className="font-mono text-[11px] opacity-70">
                        {SITE.installerSize} →
                      </span>
                    </a>
                    <Link
                      to="/"
                      className="inline-flex min-h-12 items-center rounded-md border border-border-strong bg-card px-5 text-[15px] font-medium transition-colors hover:bg-surface"
                    >
                      How it works
                    </Link>
                  </div>
                </Reveal>
              </section>
            </div>
          </div>
        </div>
      </article>
    </SiteLayout>
  );
}
