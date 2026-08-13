import { createFileRoute } from "@tanstack/react-router";
import { SiteLayout } from "@/components/site/SiteLayout";
import { LegalPage, type LegalSection } from "@/components/site/Legal";
import { SITE, url } from "@/components/site/constants";

const TITLE = "Privacy — Casper Flow";
const DESCRIPTION =
  "Casper Flow transcribes speech on your own computer. It has no account, no server and no telemetry, and it cannot send your audio anywhere. This page also states plainly what this website does.";

export const Route = createFileRoute("/privacy")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:type", content: "article" },
      { property: "og:url", content: url("/privacy") },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: url("/privacy") }],
  }),
  component: PrivacyPage,
});

const SECTIONS: LegalSection[] = [
  {
    id: "summary",
    title: "The short version",
    body: (
      <>
        <p>
          Casper Flow runs speech recognition on your computer. There is no account to create, no
          server to send audio to, and no analytics. We do not receive your voice, your transcripts,
          your keystrokes or your settings, because nothing in the application transmits them.
        </p>
        <p>
          That is a property of how it is built rather than a policy we are choosing to follow. The
          distinction matters: a policy can be revised, and an architecture with no network code in
          it cannot start sending your data because somebody changed their mind.
        </p>
      </>
    ),
  },
  {
    id: "no-collection",
    title: "What the application collects",
    body: (
      <>
        <p>
          <strong>Nothing.</strong> Specifically, and so that this is testable rather than
          reassuring:
        </p>
        <ul>
          <li>No account, email address, licence key or device identifier.</li>
          <li>No usage analytics, crash reporting, feature flags or update pings.</li>
          <li>No audio, transcripts or keystrokes.</li>
          <li>No advertising or tracking libraries of any kind.</li>
        </ul>
        <p>
          The build also <strong>excludes</strong> the client libraries for cloud transcription
          services. The program on your disk is not configured to avoid them; it is incapable of
          reaching them.
        </p>
      </>
    ),
  },
  {
    id: "audio",
    title: "What happens to your audio",
    body: (
      <>
        <p>
          When you hold the key, audio is written to a temporary file on your own disk. It is
          transcribed by a speech model that was installed alongside the application, and the
          temporary file is deleted as soon as the text has been produced.
        </p>
        <p>
          The microphone stream is opened when the application starts, not when you press the key.
          That is a latency decision — opening it on demand cost over a second and swallowed the
          beginning of every sentence — and it captures nothing while the key is up.
        </p>
        <p>
          The resulting text is placed on your clipboard for a moment in order to paste it at your
          cursor, and whatever was on your clipboard beforehand is put back.
        </p>
      </>
    ),
  },
  {
    id: "on-disk",
    title: "What stays on your computer",
    body: (
      <>
        <p>
          Everything the application saves lives next to the program, in a folder you can open, read
          and delete:
        </p>
        <ul>
          <li>
            <code>settings.json</code> — your hotkey, chosen model, vocabulary and corrections.
          </li>
          <li>
            <code>casper.log</code> — a diagnostic log. It records events and errors, not the text
            you dictated.
          </li>
        </ul>
        <p>
          Both are in <code>{SITE.settingsPath}</code>. Uninstalling asks before deleting them,
          because settings you spent time tuning are yours and not ours to discard.
        </p>
      </>
    ),
  },
  {
    id: "network",
    title: "When the application uses the network",
    body: (
      <>
        <p>
          Never during dictation. Both speech models it needs are inside the installer, so it works
          with the network disconnected, including the first time you run it.
        </p>
        <p>
          There are exactly two things that would cause it to make a request, and both are opt-in:
        </p>
        <ul>
          <li>
            Turning on live captions, or choosing a model that is not bundled, downloads that model
            once from Hugging Face.
          </li>
          <li>
            Enabling the optional local cleanup model, which talks to Ollama on{" "}
            <code>localhost</code> — on your own machine, and not out to the internet.
          </li>
        </ul>
        <p>
          The <code>offline_only</code> setting is on by default and refuses any backend that would
          send audio or text off the machine, regardless of what the rest of the configuration says.
        </p>
      </>
    ),
  },
  {
    id: "website",
    title: "What this website does",
    body: (
      <>
        <p>
          The application and the website are different things, and it would be misleading to
          describe the first and let you assume the second. This site has no analytics, no cookies
          and no tracking pixels. It does not set or read any cookie, and there is nothing to
          consent to.
        </p>
        <p>
          Three third parties are nonetheless involved in serving it, and you should know which:
        </p>
        <ul>
          <li>
            <strong>Vercel</strong> hosts it. Like any web host, its servers process the IP address
            and user agent of each request in order to answer it, and keep short-lived operational
            logs.
          </li>
          <li>
            <strong>Google Fonts</strong> serves the two typefaces this page uses, so your browser
            requests them from Google. This is the one third-party request your browser makes here,
            and removing it is on the list.
          </li>
          <li>
            <strong>GitHub</strong> hosts the download. Clicking Download sends you to GitHub's
            release storage, which is subject to GitHub's privacy policy. The installer is 234 MB;
            it has to be hosted somewhere.
          </li>
        </ul>
        <p>
          The download counter on the homepage is read from GitHub's API <em>by our server</em>, on
          a timer, so your browser never contacts GitHub to render it.
        </p>
      </>
    ),
  },
  {
    id: "rights",
    title: "Your data rights",
    body: (
      <>
        <p>
          Data protection law gives you rights to access, correct, export and delete personal data
          that an organisation holds about you. We hold none, so there is nothing for you to request
          and no process for you to go through.
        </p>
        <p>
          Your dictation data is on your own computer, under your own account. You can inspect it or
          delete it without asking anyone.
        </p>
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes to this page",
    body: (
      <>
        <p>
          If this page changes, the date at the top changes with it, and the edit is visible in the
          repository's history along with everything else. There is no mailing list to notify,
          because we do not have your email address.
        </p>
      </>
    ),
  },
];

function PrivacyPage() {
  return (
    <SiteLayout>
      <LegalPage
        eyebrow="Privacy"
        title="We do not have your voice."
        summary={
          <p>
            Casper Flow transcribes on your own processor. This page describes exactly what the
            application does with your audio, what it writes to your disk, the two occasions it
            would use the network, and — separately and honestly — what this website does.
          </p>
        }
        sections={SECTIONS}
        updated={SITE.lastUpdated}
        footnote={
          <>
            This page describes behaviour you can verify rather than take on trust. The files that
            touch your microphone, keyboard and clipboard are short, and the whole application is{" "}
            <a href={SITE.repoUrl}>public under the {SITE.license} licence</a>.
          </>
        }
      />
    </SiteLayout>
  );
}
