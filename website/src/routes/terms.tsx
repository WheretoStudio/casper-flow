import { createFileRoute } from "@tanstack/react-router";
import { SiteLayout } from "@/components/site/SiteLayout";
import { LegalPage, type LegalSection } from "@/components/site/Legal";
import { SITE, url } from "@/components/site/constants";

const TITLE = "Terms of use — Casper Flow";
const DESCRIPTION =
  "Casper Flow is free software under the MIT licence, provided as-is and without warranty. These terms explain what that means in practice, including what you are responsible for when you dictate.";

export const Route = createFileRoute("/terms")({
  head: () => ({
    meta: [
      { title: TITLE },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: TITLE },
      { property: "og:description", content: DESCRIPTION },
      { property: "og:type", content: "article" },
      { property: "og:url", content: url("/terms") },
      { name: "twitter:card", content: "summary_large_image" },
    ],
    links: [{ rel: "canonical", href: url("/terms") }],
  }),
  component: TermsPage,
});

const SECTIONS: LegalSection[] = [
  {
    id: "summary",
    title: "The short version",
    body: (
      <>
        <p>
          Casper Flow is free and open-source software. You may use it, read it, change it and
          redistribute it under the {SITE.license} licence. It comes with no warranty and no support
          commitment, and you are responsible for how you use it.
        </p>
        <p>
          There is no subscription, no account and no usage limit, so there is nothing to cancel and
          no billing relationship between us.
        </p>
      </>
    ),
  },
  {
    id: "licence",
    title: "The licence is what actually governs",
    body: (
      <>
        <p>
          Your rights to this software come from the{" "}
          <a href="https://opensource.org/licenses/MIT">{SITE.license} licence</a>, which ships in
          the repository as <code>LICENSE</code>. This page is a plain-language summary written to
          be read; it does not add terms, and if anything here appears to conflict with the licence,{" "}
          <strong>the licence wins</strong>.
        </p>
        <p>
          In particular, the licence grants permission to use the software commercially, to modify
          it, and to distribute your modified version, provided the copyright notice travels with
          it.
        </p>
      </>
    ),
  },
  {
    id: "no-warranty",
    title: "No warranty, and what that means here",
    body: (
      <>
        <p>
          The software is provided <strong>as is</strong>, without warranty of any kind. That is
          standard licence language, but it has a specific meaning for a dictation tool, so it is
          worth being concrete about it.
        </p>
        <p>
          <strong>Transcription is not reliable in the way typing is.</strong> Published accuracy
          figures are around 91% for English and 81% for mixed Hindi and English, measured on a
          small corpus. Speech recognition misreads names, numbers and unfamiliar terms. Text is
          inserted into whatever window has focus, and that could be the wrong window.
        </p>
        <p>
          Read what was inserted before you send, sign, commit or submit it. Do not use it as the
          sole input for anything where a wrong word carries real consequence — medical, legal,
          financial or safety-critical text — without checking it.
        </p>
        <p>
          To the extent the law allows, we are not liable for any loss arising from your use of the
          software, including incorrect text in a document, work lost, or a dictation that went into
          the wrong application.
        </p>
      </>
    ),
  },
  {
    id: "your-responsibilities",
    title: "What you are responsible for",
    body: (
      <>
        <ul>
          <li>
            <strong>Consent to record.</strong> The application records your microphone while you
            hold the key. If other people can be heard, recording and transcribing them may require
            their consent where you live. That is your call to make, not something the software can
            check.
          </li>
          <li>
            <strong>Where the text lands.</strong> Text is pasted at the cursor, so it goes wherever
            focus is.
          </li>
          <li>
            <strong>Your own policies.</strong> If you are using a work machine, installing software
            that hooks the keyboard may be against your employer's rules regardless of what it does.
          </li>
          <li>
            <strong>Lawful use.</strong> Do not use it to record or transcribe people covertly, or
            for anything illegal where you are.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "antivirus",
    title: "Unsigned builds and antivirus",
    body: (
      <>
        <p>
          To notice your push-to-talk key while you are working in other applications, Casper Flow
          installs a global keyboard hook. That is the same Windows mechanism a keylogger uses, so
          antivirus software sometimes flags it, and Windows Defender may quarantine or delete the
          executable outright.
        </p>
        <p>
          Releases are <strong>not code-signed yet</strong>, so Windows will also show a SmartScreen
          warning. We publish SHA-256 checksums for every artefact so you can verify a download
          instead of trusting it, and the source is public so you can read the parts that touch your
          keyboard.
        </p>
        <p>
          We will never ask you to disable your antivirus. If you choose to add an exclusion for the
          install folder, that is a decision you are making about your own machine, and the
          consequences of it are yours.
        </p>
      </>
    ),
  },
  {
    id: "third-party",
    title: "Third-party components and models",
    body: (
      <>
        <p>
          The application code is {SITE.license}. The speech models and libraries it depends on are
          under their own licences, which are not all the same, and using Casper Flow means using
          those too:
        </p>
        <ul>
          <li>faster-whisper, CTranslate2 and the OpenAI Whisper weights — MIT.</li>
          <li>
            The bundled Hinglish model, from the Whisper-Hindi2Hinglish family — Apache 2.0, which
            requires that its notice and attribution travel with it.
          </li>
        </ul>
        <p>
          No model is bundled without checking its licence first. Where attribution is required, it
          is carried with the binary rather than only mentioned in a repository file.
        </p>
      </>
    ),
  },
  {
    id: "no-support",
    title: "Support and availability",
    body: (
      <>
        <p>
          There is no support desk, no response-time commitment and no guarantee that this project
          continues to be maintained. Bugs and questions belong in the{" "}
          <a href={`${SITE.repoUrl}/issues`}>issue tracker</a>, where the answers are useful to
          everyone rather than to one person.
        </p>
        <p>
          Because the software runs entirely on your machine and needs no server, nothing we do can
          switch off a copy you have already installed. It will keep working whether or not this
          project does.
        </p>
      </>
    ),
  },
  {
    id: "law",
    title: "Applicable law",
    body: (
      <>
        <p>
          These terms are governed by the laws of {SITE.jurisdiction}, where the maintainer is
          based. Nothing here limits any right you have under the {SITE.license} licence, or any
          consumer right that cannot be waived where you live.
        </p>
      </>
    ),
  },
  {
    id: "changes",
    title: "Changes to these terms",
    body: (
      <>
        <p>
          If these terms change, the date at the top changes and the edit appears in the
          repository's history. A version you have already installed is governed by the licence that
          shipped with it, which does not change retroactively.
        </p>
      </>
    ),
  },
];

function TermsPage() {
  return (
    <SiteLayout>
      <LegalPage
        eyebrow="Terms of use"
        title="Free software, provided as is."
        summary={
          <p>
            The {SITE.license} licence is the document that grants your rights; this page explains
            in plain language what it means to use a dictation tool that runs on your own machine —
            including the parts that are your responsibility rather than ours.
          </p>
        }
        sections={SECTIONS}
        updated={SITE.lastUpdated}
        footnote={
          <>
            The full licence text is in the repository as <code>LICENSE</code>, alongside{" "}
            <a href={SITE.repoUrl}>every line of the software it covers</a>.
          </>
        }
      />
    </SiteLayout>
  );
}
