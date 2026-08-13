; Inno Setup script for Casper Flow.
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; Normally invoked by build_installer.ps1, which runs PyInstaller first and then
; passes the payload directory in with /DPayloadDir.
;
; Per-user, into %LOCALAPPDATA%\Programs\CasperFlow, and therefore with
; PrivilegesRequired=lowest. That is a deliberate trust decision rather than a
; convenience: it means there is no UAC prompt at any point. This binary is
; unsigned and already shows the user a SmartScreen warning, so removing the one
; other alarming dialog matters more than installing for all users would. It also
; means the app installs on a managed or locked-down laptop, and that the install
; directory is writable, which is what lets settings.json and casper.log live
; beside the executable where a user can find them.
;
; No model is downloaded here. Earlier drafts of the plan had the installer
; fetching weights with progress, resume and a Cancel button; the models are now
; bundled instead, so installation is pure file copying and works with the network
; unplugged. That deleted an entire class of failure - a half-downloaded model on
; a hotel connection - rather than handling it.

#define AppName        "Casper Flow"
#define AppShortName   "CasperFlow"
#define AppExe         "CasperFlow.exe"
#define AppPublisher   "Casper Flow contributors"
#define AppRepo        "https://github.com/wheretostudio/casper-flow"

; Overridable so the build script and CI decide the version, not this file.
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

; The --onedir payload. Built outside the repository because the tree is in
; OneDrive, which locks files while syncing half a gigabyte of build output.
#ifndef PayloadDir
  #define PayloadDir GetEnv("LOCALAPPDATA") + "\CasperFlowBuild\dist\CasperFlow"
#endif

#ifndef OutputDir
  #define OutputDir GetEnv("LOCALAPPDATA") + "\CasperFlowBuild\out"
#endif

; Fail at compile time rather than producing an installer with no application in
; it. An empty [Files] wildcard is otherwise only a warning.
#if !FileExists(AddBackslash(PayloadDir) + AppExe)
  #error Payload not found. Run build_installer.ps1 first, or pass /DPayloadDir=...
#endif

[Setup]
; Never change AppId: it is what links an upgrade to the thing it upgrades, and
; what lets the uninstaller find a previous install.
AppId={{7C1B4E52-9A3D-4F86-B0E7-2D5A8C41F9B3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppRepo}
AppSupportURL={#AppRepo}/issues
AppUpdatesURL={#AppRepo}/releases
DefaultDirName={localappdata}\Programs\{#AppShortName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=LICENSE
SetupIconFile=assets\casper.ico
OutputDir={#OutputDir}
OutputBaseFilename={#AppShortName}Setup
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; No administrator rights, and no offer of them. See the header.
PrivilegesRequired=lowest

; The running app holds open every DLL in _internal, so an upgrade over the top
; of a live instance would fail on locked files. This is the mutex main.py claims
; in _claim_single_instance, so Inno asks the user to quit first instead.
AppMutex=CasperFlow_SingleInstance_Mutex

; The seven screens are welcome, licence, disclosure, profile, location, install,
; finish. These three suppress the pages that would otherwise pad that out: the
; Start Menu group is not a question worth asking, and "Ready to install" adds a
; screen that only repeats the previous two.
DisableWelcomePage=no
DisableProgramGroupPage=yes
DisableReadyPage=yes

[Files]
; The payload, unchanged. settings.json and casper.log are deliberately absent
; from it - they are created by the app in {app} on first run, so there is nothing
; here that could overwrite a user's settings during an upgrade.
Source: "{#PayloadDir}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; \
    Check: WantsDesktopIcon

[Registry]
; Must match tray.py exactly - APP_NAME, STARTUP_REG_KEY and the quoted form that
; _launcher_command() writes. If they disagree, the tray's "Launch at login"
; toggle and this entry become two switches for the same lamp, and the tray shows
; the wrong state.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "Casper Flow"; \
    ValueData: """{app}\{#AppExe}"""; \
    Flags: uninsdeletevalue; Check: WantsAutostart

; The same value, recorded for deletion at uninstall whether or not the entry
; above ran. `uninsdeletevalue` only applies to entries Inno actually processed,
; so leaving the box unticked at install and later switching on "Launch at login"
; from the tray - which writes this exact value name, see tray.py - left a startup
; entry behind pointing at a deleted executable. Windows then reports a failing
; startup item forever, with nothing left on the machine to explain it.
; ValueType: none creates nothing; it only registers the value for removal.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: none; ValueName: "Casper Flow"; \
    Flags: uninsdeletevalue dontcreatekey

; Names this application used before it was called Casper Flow. An entry left
; under an old name keeps starting the app at login, and nothing in the current
; product can see it - the tray toggle reads "Casper Flow" and reports off. Found
; on a development machine that still had one. Removed on install and on
; uninstall, so a machine cannot be left with an invisible autostart.
; legacy value name, deleted on install and uninstall
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueName: "VoxPad"; Flags: deletevalue uninsdeletevalue

[Run]
; Writes the profile chosen on screen 4 into settings.json before the app ever
; starts. Done by the app itself rather than by Pascal script here, because the
; model ids and the language each profile pins already live in
; settings_ui.PROFILES and a second copy would drift.
; Only on a first install. On an upgrade the user already has a settings.json,
; and this would overwrite whisper_model and language with whatever the profile
; page happens to show - which is always the first radio button, because the page
; does not read existing settings. Someone on the English profile who reinstalled
; to get a bug fix was silently moved back to the Hinglish model.
Filename: "{app}\{#AppExe}"; Parameters: "--set-profile {code:GetProfileId}"; \
    StatusMsg: "Applying your language choice..."; \
    Flags: runhidden waituntilterminated; Check: IsFirstInstall

; Launches the app, not `--setup`. The wizard's practice step dictates for real,
; which needs a live keyboard hook and a loaded model, and `--setup` alone starts
; neither - the user would reach the last step and be unable to complete it. The
; app opens the wizard itself because the shipped settings have
; setup_complete=false.
Filename: "{app}\{#AppExe}"; \
    Description: "Start {#AppName} and finish setting up"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Written by the app at runtime, so Inno has no record of them and would otherwise
; leave them - along with a non-empty {app} that RemoveDir then cannot delete.
; casper.log is listed here rather than in the "keep my settings" prompt because a
; log is ours, not the user's.
Type: files; Name: "{app}\settings.json.tmp"
Type: filesandordirs; Name: "{app}\__pycache__"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nCasper Flow turns speech into text anywhere in Windows: hold a key, talk, and the words appear at your cursor. It runs entirely on this machine - no account, no internet connection, and your voice is never uploaded.%n%nIt installs for you only and needs no administrator rights.
FinishedHeadingLabel=Casper Flow is installed
FinishedLabelNoIcons=Setup is finished. The first time it runs, a short setup will check your microphone, let you pick your key, and have you dictate one sentence to prove it works.
FinishedLabel=Setup is finished. The first time it runs, a short setup will check your microphone, let you pick your key, and have you dictate one sentence to prove it works.

[Code]
var
  DisclosurePage: TWizardPage;
  DisclosureAgree: TNewCheckBox;
  ProfilePage: TWizardPage;
  ProfileHinglish: TNewRadioButton;
  ProfileEnglish: TNewRadioButton;
  AutostartBox: TNewCheckBox;
  DesktopBox: TNewCheckBox;

procedure OpenRepo(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', '{#AppRepo}', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure OpenDefenderHelp(Sender: TObject);
var
  ErrorCode: Integer;
begin
  ShellExec('open', '{#AppRepo}#windows-defender', '', '',
            SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

{ A clickable link. Inno has no link control, so it is a label that looks and
  behaves like one. }
function MakeLink(AParent: TWinControl; ACaption: String; ATop: Integer;
                  AHandler: TNotifyEvent): TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := AParent;
  Result.Caption := ACaption;
  Result.Top := ATop;
  Result.Left := 0;
  Result.Cursor := crHand;
  Result.Font.Color := clBlue;
  Result.Font.Style := [fsUnderline];
  Result.OnClick := AHandler;
end;

procedure DisclosureAgreeClicked(Sender: TObject);
begin
  { The disclosure is the one screen here that must be agreed to rather than
    clicked past, so Next follows the checkbox. This handler only ever fires while
    that page is showing, because that is the only page the checkbox is on. }
  WizardForm.NextButton.Enabled := DisclosureAgree.Checked;
end;

procedure CreateDisclosurePage;
var
  Body: TNewMemo;
  Link: TNewStaticText;
begin
  DisclosurePage := CreateCustomPage(
    wpLicense,
    'What this app does to your system',
    'Please read this before anything is written to disk.');

  { A memo rather than labels: it scrolls, so no part of this can be clipped by a
    display scale or font size we did not test on. A trust screen that is cut off
    is worse than no trust screen. }
  Body := TNewMemo.Create(WizardForm);
  Body.Parent := DisclosurePage.Surface;
  Body.Left := 0;
  Body.Top := 0;
  Body.Width := DisclosurePage.SurfaceWidth;
  Body.Height := DisclosurePage.SurfaceHeight - ScaleY(74);
  Body.ReadOnly := True;
  Body.ScrollBars := ssVertical;
  Body.WordWrap := True;
  Body.TabStop := False;
  Body.Text :=
    'KEYBOARD' + #13#10 +
    'Casper Flow installs a global keyboard hook. That is how it notices your' +
    ' push-to-talk key while you are typing in any other application. It is the' +
    ' same Windows mechanism a keylogger uses, which is why antivirus software' +
    ' sometimes flags this kind of program.' + #13#10#13#10 +
    'It does not log, store or transmit keystrokes. The two files that touch your' +
    ' keyboard, hotkey.py and paste.py, are short enough to read in a few' +
    ' minutes, and the repository is linked below.' + #13#10#13#10 +
    'MICROPHONE' + #13#10 +
    'It uses your microphone while the key is held down. The audio stream is' +
    ' opened when the app starts rather than when you press the key, because' +
    ' opening it on demand costs over a second and used to swallow the beginning' +
    ' of every sentence. Nothing is captured until the key goes down, and the' +
    ' recording is deleted as soon as the text has been produced.' + #13#10#13#10 +
    'CLIPBOARD' + #13#10 +
    'To place text at your cursor it copies the text, pastes it, and then puts' +
    ' back whatever was on your clipboard before.' + #13#10#13#10 +
    'NETWORK' + #13#10 +
    'None. The speech models are installed with the app and run on this' +
    ' computer. Your voice never leaves the machine.' + #13#10#13#10 +
    'WINDOWS DEFENDER' + #13#10 +
    'Defender may quarantine or even delete this program, sometimes naming it' +
    ' HackTool:SH/PythonKeylogger.B. That is a false positive caused by the' +
    ' keyboard hook above and by how the app is packaged. What to do about it is' +
    ' linked below. We will never ask you to turn Defender off.';

  DisclosureAgree := TNewCheckBox.Create(WizardForm);
  DisclosureAgree.Parent := DisclosurePage.Surface;
  DisclosureAgree.Left := 0;
  DisclosureAgree.Top := Body.Top + Body.Height + ScaleY(10);
  DisclosureAgree.Width := DisclosurePage.SurfaceWidth;
  DisclosureAgree.Caption :=
    'I understand what Casper Flow does to my system';
  DisclosureAgree.OnClick := @DisclosureAgreeClicked;

  Link := MakeLink(DisclosurePage.Surface, 'Read the source code',
                   DisclosureAgree.Top + ScaleY(24), @OpenRepo);
  Link := MakeLink(DisclosurePage.Surface, 'What to do if Defender flags it',
                   DisclosureAgree.Top + ScaleY(44), @OpenDefenderHelp);
end;

procedure CreateProfilePage;
var
  Intro: TNewStaticText;
  Note: TNewStaticText;
begin
  ProfilePage := CreateCustomPage(
    DisclosurePage.ID,
    'How you talk',
    'This picks which speech model runs. You can change it later in Settings.');

  Intro := TNewStaticText.Create(WizardForm);
  Intro.Parent := ProfilePage.Surface;
  Intro.Left := 0;
  Intro.Top := 0;
  Intro.Width := ProfilePage.SurfaceWidth;
  Intro.WordWrap := True;
  Intro.Caption :=
    'Both models are already included - nothing is downloaded. You can change' +
    ' this later in Settings.';
  Intro.AdjustHeight;

  ProfileHinglish := TNewRadioButton.Create(WizardForm);
  ProfileHinglish.Parent := ProfilePage.Surface;
  ProfileHinglish.Left := 0;
  ProfileHinglish.Top := Intro.Top + Intro.Height + ScaleY(18);
  ProfileHinglish.Width := ProfilePage.SurfaceWidth;
  ProfileHinglish.Caption := 'Hindi and English mixed (Hinglish)';
  ProfileHinglish.Checked := True;

  Note := TNewStaticText.Create(WizardForm);
  Note.Parent := ProfilePage.Surface;
  Note.Left := ScaleX(18);
  Note.Top := ProfileHinglish.Top + ScaleY(20);
  Note.Width := ProfilePage.SurfaceWidth - ScaleX(18);
  Note.WordWrap := True;
  Note.Caption :=
    'Handles sentences that switch between the two mid-flow. Measured 81%' +
    ' accurate on mixed speech, about 1.3 seconds per sentence.';
  Note.AdjustHeight;

  ProfileEnglish := TNewRadioButton.Create(WizardForm);
  ProfileEnglish.Parent := ProfilePage.Surface;
  ProfileEnglish.Left := 0;
  ProfileEnglish.Top := Note.Top + Note.Height + ScaleY(16);
  ProfileEnglish.Width := ProfilePage.SurfaceWidth;
  ProfileEnglish.Caption := 'English only';

  Note := TNewStaticText.Create(WizardForm);
  Note.Parent := ProfilePage.Surface;
  Note.Left := ScaleX(18);
  Note.Top := ProfileEnglish.Top + ScaleY(20);
  Note.Width := ProfilePage.SurfaceWidth - ScaleX(18);
  Note.WordWrap := True;
  Note.Caption :=
    'More accurate if you never mix in Hindi - measured 91%, about 1.1 seconds.' +
    ' It cannot transcribe Hindi at all.';
  Note.AdjustHeight;
end;

procedure CreateLocationExtras;
var
  Anchor: Integer;
begin
  { These two live on the directory page rather than on a Tasks page of their
    own. "Where it goes" and "should it start with Windows" are one question in
    the user's head, and splitting them would add an eighth screen. }
  Anchor := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(34);

  AutostartBox := TNewCheckBox.Create(WizardForm);
  AutostartBox.Parent := WizardForm.SelectDirPage;
  AutostartBox.Left := WizardForm.DirEdit.Left;
  AutostartBox.Top := Anchor;
  AutostartBox.Width := WizardForm.SelectDirPage.ClientWidth -
                        WizardForm.DirEdit.Left;
  AutostartBox.Caption := 'Start Casper Flow when I sign in to Windows';
  AutostartBox.Checked := True;

  DesktopBox := TNewCheckBox.Create(WizardForm);
  DesktopBox.Parent := WizardForm.SelectDirPage;
  DesktopBox.Left := WizardForm.DirEdit.Left;
  DesktopBox.Top := Anchor + ScaleY(24);
  DesktopBox.Width := AutostartBox.Width;
  DesktopBox.Caption := 'Create a desktop shortcut';
  DesktopBox.Checked := False;
end;

procedure InitializeWizard;
begin
  CreateDisclosurePage;
  CreateProfilePage;
  CreateLocationExtras;

  // A silent install has nobody to tick the box, and Inno still asks each page
  // whether it may advance - so without this, /SILENT aborts with "failed to
  // proceed to next wizard page" and no explanation.
  //
  // Treating silent as accepted matches what Inno already does with the licence
  // page, and the disclosure is aimed at the person double-clicking the .exe, not
  // at someone scripting a deployment who had to read the documentation to find
  // this switch at all.
  if WizardSilent then
    DisclosureAgree.Checked := True;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (DisclosurePage <> nil) and (CurPageID = DisclosurePage.ID) then
    WizardForm.NextButton.Enabled := DisclosureAgree.Checked;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  { Belt and braces: the button is already disabled, but a page could be reached
    by a path that did not run CurPageChanged. }
  if (DisclosurePage <> nil) and (CurPageID = DisclosurePage.ID) then
    Result := DisclosureAgree.Checked;
end;

function GetProfileId(Param: String): String;
begin
  if (ProfileEnglish <> nil) and ProfileEnglish.Checked then
    Result := 'base.en'
  else
    Result := 'swift-ct2';
end;

// True when this machine has no Casper Flow settings yet.
//
// settings.json is written by the app into the install folder on first run and is
// never part of the payload, whose copy lands in the _internal subfolder. So its
// presence in the install folder means a previous install ran here, and its
// absence means a genuinely new one. Used to keep the profile question, and the
// profile write it drives, off the upgrade path.
//
// Line comments, not braces: a brace comment ends at the first closing brace, so
// naming an Inno constant inside one turns the rest of the sentence into code.
function IsFirstInstall: Boolean;
begin
  Result := not FileExists(ExpandConstant('{app}\settings.json'));
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  { Don't ask which language you speak when we are going to ignore the answer.
    On an upgrade the existing settings win, so the page would be a question with
    no effect - worse than not asking, because the user would reasonably expect
    ticking "English only" to change something. }
  if (ProfilePage <> nil) and (PageID = ProfilePage.ID) then
    Result := not IsFirstInstall;
end;

function WantsAutostart: Boolean;
begin
  Result := (AutostartBox <> nil) and AutostartBox.Checked;
end;

function WantsDesktopIcon: Boolean;
begin
  Result := (DesktopBox <> nil) and DesktopBox.Checked;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Settings: String;
  Models: String;
  Cache: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;

  // A silent uninstall must not stop to ask anything, or it waits forever for a
  // dialog nobody can see - which is how an unattended removal or a scripted
  // upgrade would hang. Silence means keep the user's data: it is the choice that
  // loses nothing, and the directory is trivial to delete by hand.
  if UninstallSilent then
    Exit;

  { Asked separately, and asked at all, because these are the user's and not
    ours. Settings someone spent time tuning, and a model they may have waited on
    a slow connection for, should not disappear as a side effect of uninstalling
    the program. }
  Settings := ExpandConstant('{app}\settings.json');
  if FileExists(Settings) then
  begin
    if MsgBox('Also delete your Casper Flow settings?' + #13#10#13#10 +
              'This is your hotkey, vocabulary and corrections. Keep them if you' +
              ' might reinstall.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DeleteFile(Settings);
      DeleteFile(ExpandConstant('{app}\settings.local.json'));
      DeleteFile(ExpandConstant('{app}\casper.log'));
      DeleteFile(ExpandConstant('{app}\.env'));
    end;
  end;

  // Models the app downloaded after installation, and models the user dropped in
  // by hand. The bundled ones live in the install folder and go with the program.
  //
  // This used to name {localappdata}\CasperFlow\models, which nothing in the
  // application has ever created - it was a planned download location that was
  // never implemented, so DirExists was always false and this prompt never
  // appeared while the real downloads sat in the HuggingFace cache untouched.
  // Both real locations are now offered.
  //
  // Line comments here, not braces: a brace comment ends at the first closing
  // brace, so writing an Inno constant inside one silently turns the rest of the
  // sentence into code.
  Models := ExpandConstant('{app}\models');
  Cache := ExpandConstant('{userprofile}\.cache\huggingface\hub');
  if DirExists(Models) or DirExists(Cache) then
  begin
    if MsgBox('Also delete downloaded speech models?' + #13#10#13#10 +
              'These can be several hundred megabytes and would have to be' +
              ' downloaded again. Only Casper Flow''s own models are removed.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      if DirExists(Models) then
        DelTree(Models, True, True, True);
      // Scoped to the speech-model repositories by name. The HuggingFace cache is
      // shared with any other tool on the machine that uses it, so deleting the
      // whole directory would take data that is not ours.
      if DirExists(Cache) then
      begin
        DelTree(Cache + '\models--Systran--faster-whisper-*', True, True, True);
        DelTree(Cache + '\models--guillaumekln--faster-whisper-*', True, True, True);
      end;
    end;
  end;

  { Empty now if the user kept nothing; leave it alone if they did. }
  RemoveDir(ExpandConstant('{app}'));
end;
