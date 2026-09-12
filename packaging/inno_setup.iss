; Inno Setup script for Spiced (Connect-a-Project Setup Simplification spec,
; Finding 3 fix 2). Wraps the PyInstaller --onedir build at dist\Spiced\
; (see packaging/spiced.spec) into a single Spiced-Setup.exe installer.
;
; Build order:
;   1. pyinstaller packaging/spiced.spec    (produces dist\Spiced\)
;   2. iscc packaging\inno_setup.iss        (produces packaging\output\Spiced-Setup.exe)
;
; Requires Inno Setup 6 (https://jrsoftware.org/isinfo.php) and its `iscc`
; compiler on PATH. See packaging/README.md for the full build and
; packaging/vendor/README.md for the optional bundled ffmpeg.

#define MyAppName "Spiced"
#define MyAppVersion "0.0.1"
#define MyAppPublisher "Lauren Rousell"
#define MyAppURL "https://github.com/celestewish/spiced-ai"
#define MyAppExeName "Spiced.exe"
; Relative to this .iss file (packaging\) -- matches spiced.spec's --distpath.
#define DistDir "..\dist\Spiced"

[Setup]
AppId={{B6C4B9D0-6E5E-4B0D-9D1E-6B3F6E9A6E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; No signing certificate is wired up yet -- Finding 3 fix 7 flags this as a
; deliberate, budgeted yes/no decision for Lauren, not an oversight. An
; unsigned build still installs and runs; it just trips Windows
; SmartScreen's "unrecognized publisher" warning on first run, which reads
; as a virus alert to exactly the non-technical audience this installer is
; for. See packaging/README.md's "Code signing" section.
OutputDir=output
OutputBaseFilename=Spiced-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; The entire PyInstaller onedir output, including the bundled ffmpeg.exe if
; packaging/vendor/ffmpeg/ffmpeg.exe was present at build time (spiced.spec
; already folded it into this folder -- nothing ffmpeg-specific to do here).
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Registry]
; Points the bundled ffmpeg (if this build includes one -- see [Files]
; above) at itself for ffmpeg-normalize's FFMPEG_PATH env var read (Finding
; 3 fix 4; see docs/loudness_normalize_ffmpeg.md). A per-machine env var so
; it's visible to Spiced.exe regardless of which user account launches it.
; Harmless no-op if ffmpeg.exe wasn't bundled -- Spiced already handles a
; missing/unset FFMPEG_PATH by falling back to PATH, then a clear
; FfmpegNotAvailableError, never a crash.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "FFMPEG_PATH"; ValueData: "{app}\ffmpeg.exe"; \
    Flags: preservestringtype; Check: FileExists(ExpandConstant('{app}\ffmpeg.exe'))

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// Writing FFMPEG_PATH to the registry above (see [Registry]) doesn't
// retroactively update this installer's own already-running process
// environment -- without this broadcast, [Run]'s "Launch Spiced" button
// would spawn Spiced.exe as a child of *this* process, which still
// wouldn't have FFMPEG_PATH set, missing the bundled ffmpeg on exactly the
// first run Finding 3 fix 4 exists to make work. This is Inno Setup's own
// documented pattern (FAQ: "How do I make changes to environment variables
// take effect immediately?") for broadcasting WM_SETTINGCHANGE so new
// processes pick up a just-written registry env var without a full login.
const
  WM_SETTINGCHANGE = $001A;
  SMTO_ABORTIFHUNG = $0002;
  HWND_BROADCAST = $FFFF;

function SendMessageTimeoutA(
  hWnd: LongInt; Msg: LongInt; wParam: LongInt; lParam: AnsiString;
  fuFlags: LongInt; uTimeout: LongInt; var lpdwResult: LongInt
): LongInt; external 'SendMessageTimeoutA@user32.dll stdcall';

procedure BroadcastEnvironmentChange;
var
  ResultCode: LongInt;
begin
  SendMessageTimeoutA(
    HWND_BROADCAST, WM_SETTINGCHANGE, 0, 'Environment',
    SMTO_ABORTIFHUNG, 5000, ResultCode
  );
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    BroadcastEnvironmentChange;
end;
