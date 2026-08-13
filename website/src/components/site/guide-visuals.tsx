import type { ReactNode } from "react";
import { Mark } from "./Mark";
import { SITE } from "./constants";

/**
 * Mockups of the dialogs a first-time user meets, for the guide page.
 *
 * These are drawn in the site's own design language rather than being photographs
 * of a Windows desktop. Three reasons: real screenshots of an unreleased build go
 * stale on the next change and nobody notices; a PNG of a dialog cannot be read by
 * a screen reader or found by in-page search, whereas this markup can; and a
 * screenshot taken at 100% scaling looks soft on every other display.
 *
 * They are recognisable rather than pixel-exact. The wording, the button labels
 * and the order of the steps are taken from installer.iss, wizard.py, tray.py and
 * settings_ui.py, so what the guide promises is what the software says.
 */

function Chrome({
  title,
  children,
  tone = "light",
  footer,
}: {
  title: string;
  children: ReactNode;
  tone?: "light" | "dark";
  footer?: ReactNode;
}) {
  const dark = tone === "dark";
  return (
    <figure
      className={`overflow-hidden rounded-xl border ${
        dark
          ? "border-white/12 bg-surface-deep text-surface-deep-foreground"
          : "border-border bg-card"
      }`}
      style={{ boxShadow: "var(--shadow-panel)" }}
    >
      <div
        className={`flex items-center gap-3 border-b px-4 py-2.5 ${
          dark ? "border-white/10 bg-white/[0.03]" : "border-border bg-surface"
        }`}
      >
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
          <span className="h-2.5 w-2.5 rounded-full bg-border-strong" />
        </span>
        <span
          className={`truncate font-mono text-[10.5px] uppercase tracking-[0.14em] ${
            dark ? "text-surface-deep-foreground/70" : "text-muted-foreground"
          }`}
        >
          {title}
        </span>
      </div>
      <div className="px-5 py-5 sm:px-7 sm:py-6">{children}</div>
      {footer ? (
        <div
          className={`flex flex-wrap items-center justify-end gap-2 border-t px-5 py-3 sm:px-7 ${
            dark ? "border-white/10 bg-white/[0.02]" : "border-border bg-surface"
          }`}
        >
          {footer}
        </div>
      ) : null}
    </figure>
  );
}

function Button({
  children,
  variant = "default",
}: {
  children: ReactNode;
  variant?: "default" | "primary" | "ghost";
}) {
  const base =
    "inline-flex items-center rounded-md px-3.5 py-1.5 text-[12.5px] font-medium select-none";
  if (variant === "primary")
    return <span className={`${base} bg-accent text-accent-foreground`}>{children}</span>;
  if (variant === "ghost")
    return <span className={`${base} text-muted-foreground`}>{children}</span>;
  return (
    <span className={`${base} border border-border-strong bg-background text-foreground`}>
      {children}
    </span>
  );
}

/** Step 1: what Windows shows before it will run an unsigned installer. */
export function SmartScreenMock() {
  return (
    <Chrome
      title="Windows — SmartScreen"
      footer={
        <>
          <Button variant="ghost">Don&rsquo;t run</Button>
          <Button variant="primary">Run anyway</Button>
        </>
      }
    >
      <p className="text-[17px] font-semibold tracking-[-0.015em]">Windows protected your PC</p>
      <p className="mt-2.5 max-w-[52ch] text-[14px] leading-[1.7] text-muted-foreground">
        Microsoft Defender SmartScreen prevented an unrecognised app from starting. Running this app
        might put your PC at risk.
      </p>
      <dl className="mt-4 space-y-1 border-t border-border pt-4 font-mono text-[11.5px]">
        <div className="flex gap-3">
          <dt className="w-16 shrink-0 text-muted-foreground">App</dt>
          <dd>CasperFlowSetup.exe</dd>
        </div>
        <div className="flex gap-3">
          <dt className="w-16 shrink-0 text-muted-foreground">Publisher</dt>
          <dd className="text-muted-foreground">Unknown publisher</dd>
        </div>
      </dl>
      <p className="mt-4 text-[13px] text-muted-foreground">
        <span className="text-foreground underline underline-offset-4">More info</span> reveals the
        Run anyway button. This appears because the build is not code-signed yet — not because
        Windows found anything in it.
      </p>
    </Chrome>
  );
}

/** Step 2, screen 3 of 7: the disclosure. The screen this whole project turns on. */
export function InstallerDisclosureMock() {
  return (
    <Chrome
      title="Setup — Casper Flow 0.1.0"
      footer={
        <>
          <Button variant="ghost">Back</Button>
          <Button variant="primary">Next</Button>
        </>
      }
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[16px] font-semibold tracking-[-0.015em]">
            What this app does to your system
          </p>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Please read this before anything is written to disk.
          </p>
        </div>
        <span className="shrink-0 font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
          3 of 7
        </span>
      </div>

      <div className="mt-4 max-h-[190px] overflow-hidden rounded-md border border-border bg-background px-4 py-3.5">
        <p className="font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
          Keyboard
        </p>
        <p className="mt-1.5 text-[13.5px] leading-[1.7] text-muted-foreground">
          Casper Flow installs a global keyboard hook. That is how it notices your push-to-talk key
          while you are typing in any other application. It is the same Windows mechanism a
          keylogger uses, which is why antivirus software sometimes flags this kind of program.
        </p>
        <p className="mt-3 font-mono text-[10.5px] uppercase tracking-[0.16em] text-muted-foreground">
          Microphone
        </p>
        <p className="mt-1.5 text-[13.5px] leading-[1.7] text-muted-foreground">
          It uses your microphone while the key is held down. Nothing is captured until the key goes
          down&hellip;
        </p>
      </div>

      <label className="mt-4 flex items-center gap-2.5 text-[13.5px]">
        <span
          aria-hidden="true"
          className="grid h-4 w-4 shrink-0 place-items-center rounded-[3px] border border-accent bg-accent text-[10px] leading-none text-accent-foreground"
        >
          ✓
        </span>
        I understand what Casper Flow does to my system
      </label>
      <p className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-accent">
        <span className="underline underline-offset-4">Read the source code</span>
        <span className="underline underline-offset-4">What to do if Defender flags it</span>
      </p>
    </Chrome>
  );
}

/** Step 3: the last step of first-run setup, where you dictate for real. */
export function WizardPracticeMock() {
  return (
    <Chrome
      title="Set up Casper Flow"
      footer={
        <>
          <Button variant="ghost">Skip setup</Button>
          <Button>Back</Button>
          <Button variant="primary">Finish</Button>
        </>
      }
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="text-[17px] font-semibold tracking-[-0.02em]">Try it once</p>
        <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-muted-foreground">
          Step 4 of 4
        </span>
      </div>
      <p className="mt-2 max-w-[54ch] text-[13.5px] leading-[1.7] text-muted-foreground">
        Click in the box below, hold your key for two seconds, and say something. The text should
        appear where the cursor is.
      </p>

      <div className="mt-4 rounded-md border border-border-strong bg-background px-4 py-3.5">
        <p className="text-[14.5px] leading-[1.7]">
          testing one two three
          <span
            aria-hidden="true"
            className="ml-[1px] inline-block h-[1.05em] w-[1.5px] translate-y-[0.18em] bg-accent"
          />
        </p>
      </div>

      <p className="mt-3.5 inline-flex items-center gap-2 text-[13px] font-medium text-accent">
        <span aria-hidden="true">✓</span>
        Heard you. That is a real transcription, not a simulation.
      </p>
    </Chrome>
  );
}

/** Where the app lives once it is running. */
export function TrayMock() {
  return (
    <Chrome title="Windows — notification area" tone="dark">
      <div className="flex items-center justify-end gap-3">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-surface-deep-foreground/70">
          ^
        </span>
        <Mark className="h-4 w-4" />
        <span className="font-mono text-[10.5px] text-surface-deep-foreground/70">14:32</span>
      </div>
      <div className="mt-4 w-full max-w-[260px] rounded-md border border-white/10 bg-white/[0.04] p-1.5">
        {[
          ["Casper Flow — enabled", true],
          ["Settings…", false],
          ["Run diagnostics", false],
          ["Launch at login", false],
          ["Open log", false],
          ["Quit", false],
        ].map(([label, strong]) => (
          <p
            key={String(label)}
            className={`rounded px-2.5 py-1.5 text-[13px] ${
              strong ? "bg-white/[0.06] font-medium text-white" : "text-surface-deep-foreground/70"
            }`}
          >
            {label}
          </p>
        ))}
      </div>
      <p className="mt-3 text-[12.5px] text-surface-deep-foreground/70">
        There is no main window. Right-click the icon for everything.
      </p>
    </Chrome>
  );
}

/** The settings window, with the six real tabs. */
export function SettingsMock() {
  const tabs = ["Dictation", "Words", "Accuracy & speed", "Appearance", "Privacy", "Diagnostics"];
  return (
    <Chrome
      title="Casper Flow — Settings"
      footer={
        <>
          <Button variant="ghost">Cancel</Button>
          <Button variant="primary">Save</Button>
        </>
      }
    >
      <div className="-mx-1 flex flex-wrap gap-1 border-b border-border pb-2.5">
        {tabs.map((t, i) => (
          <span
            key={t}
            className={`rounded-md px-2.5 py-1.5 text-[12.5px] ${
              i === 0
                ? "border border-border-strong bg-background font-medium text-foreground"
                : "text-muted-foreground"
            }`}
          >
            {t}
          </span>
        ))}
      </div>

      <dl className="mt-4 space-y-3.5">
        {[
          ["Push-to-talk key", "Caps Lock", "Change…"],
          ["Hold before recording starts", "2.0 seconds", ""],
          ["How you talk", "Hindi and English mixed", ""],
        ].map(([label, value, action]) => (
          <div key={label} className="flex flex-wrap items-center gap-3">
            <dt className="w-[220px] shrink-0 text-[13.5px] text-muted-foreground">{label}</dt>
            <dd className="flex items-center gap-2">
              <span className="rounded border border-border-strong bg-background px-2.5 py-1 font-mono text-[12px]">
                {value}
              </span>
              {action ? <Button>{action}</Button> : null}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 border-t border-border pt-3.5 text-[12.5px] text-muted-foreground">
        Every setting is also a plain line in <span className="font-mono">settings.json</span>, in{" "}
        <span className="font-mono">{SITE.settingsPath}</span>.
      </p>
    </Chrome>
  );
}
