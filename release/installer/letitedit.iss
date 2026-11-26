; letitedit installer (Inno Setup 6.7). Built by build.ps1; nothing here is uploaded or published.
; Per-user install (no admin rights), into any folder: the editor and the tools find their files from where they are
; installed (LETITEDIT_ROOT / the exe's folder). /SANDBOX=1 = test install: no Add/Remove Programs entry and no
; Start menu entries or file associations (used for the sandbox tests; everything else is the same).

#ifndef Src
  #define Src "C:\LetItEdit"
#endif
#ifndef Exe
  #error Exe (the editor file name) must be passed: /DExe=letitedit-....exe
#endif
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
; the copyright holder and publisher, in one place (also README-LETITEDIT.txt, README.md, the editor's version resource)
#define Holder "letitedit"

[Setup]
AppId={{F34B43B4-618E-46BD-9D43-6BE33675D356}
AppName=letitedit
AppVersion={#AppVersion}
AppVerName=letitedit {#AppVersion}
AppPublisher={#Holder}
AppCopyright=Copyright (C) 2026 {#Holder}
VersionInfoCompany={#Holder}
VersionInfoCopyright=Copyright (C) 2026 {#Holder}
VersionInfoDescription=letitedit setup
VersionInfoProductName=letitedit
DefaultDirName={localappdata}\Programs\letitedit
DisableDirPage=no
DisableProgramGroupPage=yes
DefaultGroupName=letitedit
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=out
OutputBaseFilename=letitedit-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
InfoBeforeFile=files\BEFORE-INSTALL.txt
UninstallDisplayName=letitedit
UninstallDisplayIcon={app}\app\{#Exe}
CreateUninstallRegKey=not IsSandbox
SetupLogging=yes
ChangesAssociations=yes
UsePreviousAppDir=no
DirExistsWarning=no
AppendDefaultDirName=no

[Types]
Name: "standard"; Description: "Standard"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "main"; Description: "letitedit (editor, tools, editing skills, styles, effects library, animated titles, fonts, platform profiles, guide, Codex plugin)"; Types: standard custom; Flags: fixed

[Tasks]
Name: "startmenu"; Description: "Start menu entries (letitedit editor, setup, repair, uninstall)"; Check: not IsSandbox
Name: "mltassociation"; Description: "Open .mlt projects with letitedit"; Check: not IsSandbox

[Dirs]
Name: "{app}\models"

[Files]
Source: "{#Src}\Open letitedit.vbs"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "{#Src}\assets\letitedit.ico"; DestDir: "{app}\assets"; Flags: ignoreversion; Components: main
Source: "{#Src}\tools\register-mlt-association.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion; Components: main
; editor: the newest build only, with its licence texts and notices. app\share\shotcut\elements\sounds holds letitedit's
; own CC0 sound effects; the engine's GDC sounds (their EULA forbids AI use) were deleted on 2026-10-29.
; (not open-in-ai-assist.vbs: the retired managed episodes' launcher)
Source: "{#Src}\app\*"; DestDir: "{app}\app"; Excludes: "letitedit*.exe,shotcut.exe,shotcut-official.exe,*.bak,ai-assist-executable.txt,open-in-ai-assist.vbs,\lib\mlt\libmltqt6.dll,\lib\mlt\libmltplus.dll,\lib\mlt\libmltresample.dll,\libmlt-7.dll"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\app\{#Exe}"; DestDir: "{app}\app"; Flags: ignoreversion; Components: main
; the engine's text and captions modules with letitedit's patches (bold and other weights, the font library, a caption
; that runs to the video's end): engine-patches\modules, built by build_modules.sh, checked by build.ps1
Source: "{#Src}\engine-patches\modules\libmltqt6.dll"; DestDir: "{app}\app\lib\mlt"; Flags: ignoreversion; Components: main
Source: "{#Src}\engine-patches\modules\libmltplus.dll"; DestDir: "{app}\app\lib\mlt"; Flags: ignoreversion; Components: main
; the engine itself and its resample module with letitedit's leak fixes (engine-patches\README.md), checked the same way
Source: "{#Src}\engine-patches\modules\libmltresample.dll"; DestDir: "{app}\app\lib\mlt"; Flags: ignoreversion; Components: main
Source: "{#Src}\engine-patches\modules\libmlt-7.dll"; DestDir: "{app}\app"; Flags: ignoreversion; Components: main
Source: "files\licences\*"; DestDir: "{app}\licences"; Flags: ignoreversion; Components: main
; letitedit's own licence (GPL-3.0, the full text; the editor's copy is app\COPYING.txt)
Source: "{#Src}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion; Components: main
Source: "{#Src}\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "files\README-LETITEDIT.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme; Components: main
; tool server (bridge) and what it reads
Source: "{#Src}\bridge\*.py"; DestDir: "{app}\bridge"; Excludes: "test_*.py"; Flags: ignoreversion; Components: main
Source: "{#Src}\bridge\ai_list.json"; DestDir: "{app}\bridge"; Flags: ignoreversion; Components: main
Source: "{#Src}\bridge\*.ps1"; DestDir: "{app}\bridge"; Flags: ignoreversion; Components: main
; the bridge's data files: the timing thresholds and the measured accuracy tables the tools read
Source: "{#Src}\bridge\*.json"; DestDir: "{app}\bridge"; Flags: ignoreversion; Components: main
; the tool code by job (bridge\letitedit\<job>\); the files in bridge\ above start it or keep its old names
Source: "{#Src}\bridge\letitedit\*.py"; DestDir: "{app}\bridge\letitedit"; Excludes: "__pycache__\*,test_*.py"; Flags: ignoreversion recursesubdirs; Components: main
; letitedit Studio (jobs from other programs): its contract (CONTRACT.md, schemas, examples: what callers read)
; and its typical times
Source: "{#Src}\bridge\letitedit\studio\contract\*"; DestDir: "{app}\bridge\letitedit\studio\contract"; Excludes: "__pycache__\*,*.py,*.pyc,\examples"; Flags: ignoreversion recursesubdirs; Components: main
Source: "{#Src}\bridge\letitedit\studio\typical.json"; DestDir: "{app}\bridge\letitedit\studio"; Flags: ignoreversion; Components: main
Source: "{#Src}\bridge\graphics_templates\*.py"; DestDir: "{app}\bridge\graphics_templates"; Flags: ignoreversion; Components: main
Source: "{#Src}\bridge\vendor\rea_video\*"; DestDir: "{app}\bridge\vendor\rea_video"; Excludes: "__pycache__\*"; Flags: ignoreversion; Components: main
Source: "{#Src}\GUIDE_V2.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "{#Src}\GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "{#Src}\toolset.txt"; DestDir: "{app}"; Flags: ignoreversion; Components: main
; the app's How to reference (AI > How to / Command Finder, and letitedit_command_help)
Source: "{#Src}\command-reference.json"; DestDir: "{app}"; Flags: ignoreversion; Components: main
Source: "{#Src}\chat\panel-prompt.md"; DestDir: "{app}\chat"; Flags: ignoreversion; Components: main
Source: "{#Src}\chat\mcp_proxy.py"; DestDir: "{app}\chat"; Flags: ignoreversion; Components: main
Source: "{#Src}\chat\session_event.py"; DestDir: "{app}\chat"; Flags: ignoreversion; Components: main
Source: "{#Src}\src\third_party\libvterm\LICENSE"; DestDir: "{app}\licences"; DestName: "libvterm-MIT.txt"; Flags: ignoreversion; Components: main
Source: "{#Src}\src\third_party\webview2\LICENSE.txt"; DestDir: "{app}\licences"; DestName: "WebView2Loader-BSD-3.txt"; Flags: ignoreversion; Components: main
Source: "{#Src}\src\third_party\webview2\NOTICE.txt"; DestDir: "{app}\licences"; DestName: "WebView2Loader-NOTICE.txt"; Flags: ignoreversion; Components: main
; the editing skills: three core tools run their scripts (letitedit_quality_gate and letitedit_review_bundle run
; letitedit-gate\scripts\gate.py, letitedit_critic letitedit-review\scripts\critic.py) and Connect Your AI / the setup
; window copy them into the person's Claude Code and Codex (skills\install.py)
Source: "{#Src}\skills\*"; DestDir: "{app}\skills"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
; Looks: one public catalogue with recipes, portable settings, resources and previews; personal Looks never ship
; and poster. Never tests\.
Source: "{#Src}\looks\*"; DestDir: "{app}\looks"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
; creator and VFX code the tools import (their models are in the manifest; VFX beta stays off)
Source: "{#Src}\creator\letitedit_creator\*"; DestDir: "{app}\creator\letitedit_creator"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\creator\letitedit_filter_ui\*"; DestDir: "{app}\creator\letitedit_filter_ui"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\vfx\letitedit_vfx\*"; DestDir: "{app}\vfx\letitedit_vfx"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\vfx\letitedit_filter_ui\*"; DestDir: "{app}\vfx\letitedit_filter_ui"; Excludes: "__pycache__"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\vfx\library\*"; Excludes: "test-*"; DestDir: "{app}\vfx\library"; Flags: recursesubdirs createallsubdirs ignoreversion skipifsourcedoesntexist; Components: main
Source: "{#Src}\vfx\README.md"; DestDir: "{app}\vfx"; Flags: ignoreversion; Components: main
Source: "{#Src}\vfx\setup_vfx.py"; DestDir: "{app}\vfx"; Flags: ignoreversion; Components: main
Source: "files\vfx-settings.json"; DestDir: "{app}\vfx"; DestName: "settings.json"; Flags: onlyifdoesntexist; Components: main
; fonts, platform profiles, Codex plugin
Source: "{#Src}\fonts\library\*"; DestDir: "{app}\fonts\library"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\fonts\catalog.json"; DestDir: "{app}\fonts"; Flags: ignoreversion; Components: main
; the Google Fonts index: every family searchable, each one downloaded when chosen (bridge\google_fonts.py)
Source: "{#Src}\fonts\google-fonts.json.gz"; DestDir: "{app}\fonts"; Flags: ignoreversion; Components: main
Source: "{#Src}\fonts\google-fonts-glyphs.bin"; DestDir: "{app}\fonts"; Flags: ignoreversion; Components: main
; asset library (bridge\assets.py, letitedit_assets): manifests, licence texts and the MIT / CC0 media - Fluent Emoji
; and Tabler Icons (MIT), the CC0 sound library, Kenney packs and letitedit's synthesised sounds (CC0). Shotcut's
; Elements (Noto animated emoji: CC BY 4.0, a credit per video; Lottie stickers; the CC0 sounds) come with app\ above.
; The CC0 music library (music-library, ~5 GB) is not shipped whole; its songs are indexed only where it exists. A starter set of 32 of its songs
; (about 126 MB, listed in starter-music\starter-list.csv and chosen by tools\music\select_starter.py) is shipped through the generated include below.
#include "starter-music.iss"
Source: "{#Src}\assets\README.md"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist; Components: main
Source: "{#Src}\assets\popular.json"; DestDir: "{app}\assets"; Flags: ignoreversion; Components: main
Source: "{#Src}\assets\manifest\*.json"; DestDir: "{app}\assets\manifest"; Flags: ignoreversion; Components: main
Source: "{#Src}\assets\licences\*"; DestDir: "{app}\assets\licences"; Flags: ignoreversion; Components: main
Source: "{#Src}\assets\emoji\*"; DestDir: "{app}\assets\emoji"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\assets\icons\*"; DestDir: "{app}\assets\icons"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\assets\sfx\*"; DestDir: "{app}\assets\sfx"; Excludes: "desktop.ini,*.part"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
; music written as a score (letitedit_music_write): one bundled file, run by the Node below
Source: "{#Src}\written-music\written-music.mjs"; DestDir: "{app}\written-music"; Flags: ignoreversion; Components: main
Source: "{#Src}\written-music\README.md"; DestDir: "{app}\written-music"; Flags: ignoreversion; Components: main
Source: "{#Src}\written-music\LICENSE-anidoodle.txt"; DestDir: "{app}\written-music"; Flags: ignoreversion; Components: main
Source: "{#Src}\written-music\NOTICE-anidoodle.txt"; DestDir: "{app}\written-music"; Flags: ignoreversion; Components: main
; motion clips (letitedit_motion; the styles' place tags and count-ups): our blocks and runtime, the HyperFrames engine
; (its npm packages as package-lock.json pins them, without type definitions, source maps and readmes) and a portable
; Node to run it (staged by build.ps1). No browser: the engine draws with the PC's own Microsoft Edge or Google Chrome
; (bridge\motion.py installed_browsers); without one, motion items are drawn as their nearest graphic instead.
Source: "{#Src}\motion\README.md"; DestDir: "{app}\motion"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\LICENSE-hyperframes.txt"; DestDir: "{app}\motion"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\blocks\*.js"; DestDir: "{app}\motion\blocks"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\runtime\*.js"; DestDir: "{app}\motion\runtime"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\runtime\looks\*"; DestDir: "{app}\motion\runtime\looks"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\runtime\shaders\*"; DestDir: "{app}\motion\runtime\shaders"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\engine\package.json"; DestDir: "{app}\motion\engine"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\engine\package-lock.json"; DestDir: "{app}\motion\engine"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\engine\node_modules\*"; DestDir: "{app}\motion\engine\node_modules"; Excludes: "*.d.ts,*.d.mts,*.d.cts,*.map,*.tsbuildinfo,README.md,CHANGELOG.md,HISTORY.md,*.test.mjs,*.test.js,*.test.cjs,*.test.ts"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "out\stage\node\node.exe"; DestDir: "{app}\motion\node"; Flags: ignoreversion; Components: main
Source: "{#Src}\motion\LICENSE-node.txt"; DestDir: "{app}\motion\node"; DestName: "LICENSE.txt"; Flags: ignoreversion; Components: main
Source: "{#Src}\platforms\*"; DestDir: "{app}\platforms"; Flags: ignoreversion; Components: main
Source: "{#Src}\codex\.agents\*"; DestDir: "{app}\codex\.agents"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "{#Src}\codex\plugins\*"; DestDir: "{app}\codex\plugins"; Excludes: "\letitedit\.codex-plugin\plugin.json"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
; the plugin manifest with a neutral server command (build.ps1, stage_plugin.py); setup points it at the install
Source: "out\stage\codex-plugin.json"; DestDir: "{app}\codex\plugins\letitedit\.codex-plugin"; DestName: "plugin.json"; Flags: ignoreversion; Components: main
; settings, model manifest, setup programs
Source: "files\setup\default-settings.json"; DestDir: "{app}"; DestName: "settings.json"; Flags: onlyifdoesntexist uninsneveruninstall; Components: main
; the beat finder (T72): in the installer, so any song on any PC has beats with no download
Source: "{#Src}\models\beat-finder\beat_this_final0_fp16.onnx"; DestDir: "{app}\models\beat-finder"; Flags: ignoreversion; Components: main
Source: "models-manifest.json"; DestDir: "{app}\models"; DestName: "manifest.json"; Flags: ignoreversion; Components: main
Source: "files\setup\*"; DestDir: "{app}\setup"; Flags: ignoreversion; Components: main
Source: "{#Src}\release\env\requirements-bridge.txt"; DestDir: "{app}\setup\env"; Flags: ignoreversion; Components: main
Source: "{#Src}\release\env\requirements-bridge-nodeps.txt"; DestDir: "{app}\setup\env"; Flags: ignoreversion; Components: main
Source: "{#Src}\release\env\licence_scan.py"; DestDir: "{app}\setup\env"; Flags: ignoreversion; Components: main
; model environment recipes (pinned package lists; built on first use by bridge\env_build.py)
Source: "{#Src}\release\envs\envs.json"; DestDir: "{app}\setup\envs"; Flags: ignoreversion; Components: main
Source: "{#Src}\release\envs\requirements-*.txt"; DestDir: "{app}\setup\envs"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: main
Source: "tools\uv\uv.exe"; DestDir: "{app}\setup\uv"; Flags: ignoreversion; Components: main
Source: "files\uv-LICENSE-*.txt"; DestDir: "{app}\setup\uv"; Flags: ignoreversion; Components: main
; Microsoft's own C++ runtime installer: setup runs it (one admin prompt) only when Windows lacks the runtime
Source: "tools\vcredist\vc_redist.x64.exe"; DestDir: "{app}\setup"; Flags: ignoreversion; Components: main
Source: "out\stage\install-marker.json"; DestDir: "{app}\setup"; DestName: "letitedit-install.json"; Flags: ignoreversion; Components: main

[Icons]
Name: "{autoprograms}\letitedit\letitedit editor"; Filename: "{app}\app\{#Exe}"; Parameters: "--noupgrade --appdata ""{app}\appdata"""; WorkingDir: "{app}\app"; Tasks: startmenu
Name: "{autoprograms}\letitedit\letitedit setup"; Filename: "{app}\env\Scripts\pythonw.exe"; Parameters: """{app}\setup\setup_wizard.py"""; WorkingDir: "{app}\setup"; IconFilename: "{app}\app\{#Exe}"; Tasks: startmenu
Name: "{autoprograms}\letitedit\Repair letitedit's Python tools"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\install_env.ps1"" -App ""{app}"" -Repair"; Tasks: startmenu
Name: "{autoprograms}\letitedit\Uninstall letitedit"; Filename: "{uninstallexe}"; Tasks: startmenu

[Registry]
; letitedit Studio's command line, so another program can find it (bridge\letitedit\studio\contract\CONTRACT.md, section 3)
Root: HKCU; Subkey: "Software\letitedit\Studio"; ValueType: string; ValueName: "cli"; ValueData: """{app}\env\Scripts\python.exe"" ""{app}\bridge\letitedit_studio.py"""; Flags: uninsdeletekey; Components: main; Check: not IsSandbox

[Run]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\setup\register-mlt-association.ps1"" -Root ""{app}"""; Tasks: mltassociation; Flags: runhidden waituntilterminated; Check: not IsSandbox
Filename: "{app}\env\Scripts\pythonw.exe"; Parameters: """{app}\setup\setup_wizard.py"""; WorkingDir: "{app}\setup"; Description: "Open letitedit setup now (connect Claude Code / Codex, choose folders)"; Flags: postinstall nowait skipifsilent; Check: EnvReady

; The .mlt association is taken out by RemoveAssociation (below) when the uninstaller runs. An [UninstallRun] entry
; can't do it: its Check runs at install time, before [Run] has registered the association, so a fresh install never
; recorded it (T288: the association stayed after every uninstall that followed a fresh install).

[UninstallDelete]
; what letitedit's tools make while they run, removed every time (T288): caches, job records, test windows' folders,
; temporary files and the model environments env_build made. The person's settings stay unless they ask (CleanupWorking).
Type: filesandordirs; Name: "{app}\cache"
Type: filesandordirs; Name: "{app}\jobs"
Type: filesandordirs; Name: "{app}\instances"
Type: filesandordirs; Name: "{app}\temp"
Type: filesandordirs; Name: "{app}\envs"
; the editor's own caches outside the install folder: its QML cache, playback copies and previews (the sandbox test
; leaves the real profile alone)
Type: filesandordirs; Name: "{localappdata}\letitedit\letitedit\cache"; Check: not IsSandbox
Type: filesandordirs; Name: "{localappdata}\letitedit\playback-copies"; Check: not IsSandbox
Type: filesandordirs; Name: "{localappdata}\letitedit\playback-previews"; Check: not IsSandbox
; the Studio's job records and New video's run folders, job records like {app}\jobs (T377: 35.5 MB stayed)
Type: filesandordirs; Name: "{localappdata}\letitedit\studio"; Check: not IsSandbox
Type: filesandordirs; Name: "{localappdata}\letitedit\new-video-runs"; Check: not IsSandbox
Type: dirifempty; Name: "{localappdata}\letitedit\letitedit"; Check: not IsSandbox
Type: dirifempty; Name: "{localappdata}\letitedit"; Check: not IsSandbox
Type: filesandordirs; Name: "{app}\env"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\setup\uv-cache"
Type: filesandordirs; Name: "{app}\cache\uv"
Type: filesandordirs; Name: "{app}\cache\assets"
Type: filesandordirs; Name: "{app}\setup\__pycache__"
Type: filesandordirs; Name: "{app}\bridge\__pycache__"
Type: filesandordirs; Name: "{app}\bridge\graphics_templates\__pycache__"
Type: filesandordirs; Name: "{app}\bridge\vendor\rea_video\__pycache__"
Type: filesandordirs; Name: "{app}\bridge\letitedit"
Type: filesandordirs; Name: "{app}\creator\letitedit_creator\__pycache__"
Type: filesandordirs; Name: "{app}\creator\letitedit_filter_ui\__pycache__"
Type: filesandordirs; Name: "{app}\vfx\letitedit_vfx\__pycache__"
Type: filesandordirs; Name: "{app}\vfx\letitedit_filter_ui\__pycache__"
Type: filesandordirs; Name: "{app}\skills\__pycache__"
Type: filesandordirs; Name: "{app}\skills\letitedit-gate\scripts\__pycache__"
Type: filesandordirs; Name: "{app}\skills\letitedit-review\scripts\__pycache__"
Type: files; Name: "{app}\setup\install-env.log"
Type: files; Name: "{app}\setup\warm-up.log"
Type: files; Name: "{app}\setup\relocated.json"
Type: files; Name: "{app}\setup\relocate-stuck.log"
Type: filesandordirs; Name: "{app}\setup\relocating"
Type: files; Name: "{app}\setup\registrations.json"
Type: files; Name: "{app}\setup\first-run.json"
Type: files; Name: "{app}\app\ai-assist-executable.txt"
Type: files; Name: "{app}\settings.json.before-letitedit-*"
Type: files; Name: "{app}\appdata\ai-audio-libraries.json"
Type: files; Name: "{app}\appdata\ai-audio-libraries.lock"
Type: dirifempty; Name: "{app}\appdata"
Type: dirifempty; Name: "{app}\models"
Type: dirifempty; Name: "{app}\looks"
Type: dirifempty; Name: "{app}"

[Code]
#include "runstep.iss"

const
  { Limits for a step, from what was measured (tests\t76\REPORT.md, eighth round). IDLE: nothing at all done by the step or its children. CEILING: still moving. }
  ENV_IDLE_S = 900;
  ENV_CEILING_S = 21600;
  RELOCATE_IDLE_S = 300;
  RELOCATE_CEILING_S = 3600;
  CLEANUP_IDLE_S = 300;
  CLEANUP_CEILING_S = 1800;

var
  EnvOk: Boolean;
  CleanupWorking: Boolean;
  StuckStep: String;

function IsSandbox: Boolean;
begin
  Result := ExpandConstant('{param:SANDBOX|0}') = '1';
end;

function EnvReady: Boolean;
begin
  Result := EnvOk;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Dir: String;
begin
  Result := '';
  Dir := ExpandConstant('{app}');
  if Pos('''', Dir) > 0 then
    Result := 'Please choose a folder without a quote mark ('') in its name.'
  else if DirExists(Dir + '\bridge') and not FileExists(Dir + '\setup\letitedit-install.json') then
    Result := 'This folder already holds a copy of letitedit that this installer did not make ' +
              '(for example the one it was built from). Nothing was changed. Please choose another folder.';
end;

{ Only with /SANDBOX=1, for run_sandbox_stuck.ps1: /TESTSTUCK=<step> or <step>-once puts a stand-in that never ends in place of that step (always, or for the first try
  only), /TESTSCRIPT=<file> is the stand-in, /TESTIDLE=<seconds> shortens the limit so the test doesn't take ten minutes, and /TESTCEILSTEP=<step> /TESTCEILING=<seconds> stops the
  real step partway. A customer's setup never reaches any of this. }
procedure TestStandIn(const StepId: String; Attempt: Integer; var Exe, Params: String; var IdleS, CeilingS: Integer);
var
  Mode: String;
begin
  if not IsSandbox then
    Exit;
  if ExpandConstant('{param:TESTIDLE|0}') <> '0' then
    IdleS := StrToIntDef(ExpandConstant('{param:TESTIDLE|0}'), IdleS);
  if ExpandConstant('{param:TESTCEILSTEP|}') = StepId then
    CeilingS := StrToIntDef(ExpandConstant('{param:TESTCEILING|0}'), CeilingS);
  Mode := ExpandConstant('{param:TESTSTUCK|}');
  if (Mode = StepId) or ((Mode = StepId + '-once') and (Attempt = 1)) then
  begin
    Exe := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{param:TESTSCRIPT|}') + '"';
  end;
end;

{ Runs one step with its limits. Stuck: stopped, then tried once more. Still stuck, or past its ceiling: StuckStep says which, and setup moves on. }
procedure RunStep(const Msg, StepId, Exe, Params: String; IdleS, CeilingS: Integer; var Ok: Boolean);
var
  Code, Outcome, Attempt, Idle, Ceiling: Integer;
  E, P: String;
begin
  for Attempt := 1 to 2 do
  begin
    E := Exe;
    P := Params;
    Idle := IdleS;
    Ceiling := CeilingS;
    TestStandIn(StepId, Attempt, E, P, Idle, Ceiling);
    if Attempt = 1 then
      WizardForm.StatusLabel.Caption := Msg
    else
      WizardForm.StatusLabel.Caption := Msg + ' (trying again)';
    Log('Running: ' + E + ' ' + P);
    Outcome := RunWithLimit(E, P, ExpandConstant('{app}'), Idle, Ceiling, Code);
    if Outcome = STEP_DONE then
    begin
      Log('Exit code ' + IntToStr(Code));
      Ok := Ok and (Code = 0);
      Exit;
    end;
    if Outcome = STEP_NOSTART then
    begin
      Log('Could not start: ' + SysErrorMessage(Code));
      Ok := False;
      Exit;
    end;
    if (Outcome = STEP_TOOLONG) or (Attempt = 2) then
    begin
      StuckStep := Msg;
      Ok := False;
      Exit;
    end;
    Log('Trying that step once more.');
    Sleep(3000);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  App, Text, Step: String;
  Ok: Boolean;
  Code: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    App := ExpandConstant('{app}');
    Ok := True;
    StuckStep := '';
    RunStep('Setting up letitedit''s Python tools (needs the internet; a few minutes)...', 'env',
            ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
            '-NoProfile -ExecutionPolicy Bypass -File "' + App + '\setup\install_env.ps1" -App "' + App + '"', ENV_IDLE_S, ENV_CEILING_S, Ok);
    if Ok then
    begin
      RunStep('Fitting the tools to this folder...', 'relocate', App + '\env\Scripts\python.exe',
              '-I "' + App + '\setup\relocate.py" "' + App + '" --exe {#Exe}', RELOCATE_IDLE_S, RELOCATE_CEILING_S, Ok);
      if (not Ok) and (StuckStep = '') then
      begin
        { a new process can fail to start once right after the environment is made (seen: 0xC0000142); retry }
        Sleep(3000);
        Ok := True;
        RunStep('Fitting the tools to this folder (again)...', 'relocate', App + '\env\Scripts\python.exe',
                '-I "' + App + '\setup\relocate.py" "' + App + '" --exe {#Exe}', RELOCATE_IDLE_S, RELOCATE_CEILING_S, Ok);
      end;
    end;
    EnvOk := Ok;
    { T288: the editor's libraries are mapped once and the video engine loads every module once now, while setup is
      already running, so the person's first open doesn't wait while the antivirus checks each file for the first time
      (setup\warm_up.ps1). A failure here changes nothing. }
    WizardForm.StatusLabel.Caption := 'Getting letitedit ready for its first start...';
    Log('Warm-up: ' + IntToStr(RunWithLimit(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        '-NoProfile -ExecutionPolicy Bypass -File "' + App + '\setup\warm_up.ps1" -App "' + App + '"', App + '\setup',
        120, 600, Code)) + ', exit code ' + IntToStr(Code));
    if not Ok then
    begin
      if StuckStep <> '' then
        Text := 'Setup got stuck on this step and stopped it: ' + StuckStep + #13#10#13#10 +
                'The editor is installed, but letitedit''s AI tools aren''t ready yet. Nothing of yours was changed.' + #13#10#13#10 +
                'What to do: restart your PC, then run this installer again into the same folder. If it sticks again, pause your antivirus while it runs. ' +
                'You can also use "Repair letitedit''s Python tools" from the Start menu. Details: ' + App + '\setup\install-env.log'
      else
        Text := 'letitedit''s Python tools could not be set up (is the internet on?). The editor is installed. ' +
                'Run "Repair letitedit''s Python tools" from the Start menu later, or run this installer again. Details: ' + App + '\setup\install-env.log';
      Log('Python tools not ready. Message for the person: ' + Text);
      { T368: the editor's first start offers a problem report for this (the person sees it all; nothing is sent
        without their Send). A repair that works removes the note (setup\install_env.ps1). }
      Step := 'letitedit''s Python tools';
      if StuckStep <> '' then
        Step := 'stuck: ' + StuckStep;
      StringChangeEx(Step, '"', '', True);
      StringChangeEx(Step, '\', '/', True);
      SaveStringToFile(App + '\setup\setup-problem.json', '{"format": "letitedit-setup-problem/1", "step": "' + Step +
                       '", "when": "' + GetDateTimeString('yyyy-mm-dd hh:nn', '-', ':') + '"}', False);
      if not WizardSilent then
        MsgBox(Text, mbError, MB_OK);
    end;
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := True;
  CleanupWorking := False;
  if not UninstallSilent then
    CleanupWorking := MsgBox('Also remove your letitedit settings (editor settings, AI choices, chat history, ' +
      'Look sharing choice)?' + #13#10#13#10 + 'Keep them if you will install letitedit again. Caches and downloaded ' +
      'models are removed either way. Your projects, videos, music, Looks and other files are never removed.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES
  else
    CleanupWorking := Pos('/WORKINGFILES=1', Uppercase(GetCmdTail)) > 0;
  Log('Uninstall command line: ' + GetCmdTail + '; working files: ' + IntToStr(Ord(CleanupWorking)));
end;

function CleanupFlag(Param: String): String;
begin
  if CleanupWorking then
    Result := '--working-files'
  else
    Result := '';
end;

{ Takes letitedit's .mlt association out (T288): the registration script puts back what it found when it registered
  (its backup in appdata), then anything still letitedit's own goes: the progid that opens projects with this folder's
  launcher, and the .mlt entries naming it. Another program's entries are never touched. }
procedure RemoveAssociation(const App: String);
var
  Code: Integer;
  Value: String;
begin
  if FileExists(App + '\appdata\mlt-association-backup.json') and FileExists(App + '\setup\register-mlt-association.ps1') then
  begin
    if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
            '-NoProfile -ExecutionPolicy Bypass -File "' + App + '\setup\register-mlt-association.ps1" -Root "' + App + '" -Undo',
            App + '\setup', SW_HIDE, ewWaitUntilTerminated, Code) then
      Log('Association put back, exit code ' + IntToStr(Code))
    else
      Log('Association script could not start: ' + SysErrorMessage(Code));
  end;
  if RegQueryStringValue(HKCU, 'Software\Classes\letitedit.Project\shell\open\command', '', Value) and
     (Pos(Lowercase(App + '\'), Lowercase(Value)) > 0) then
  begin
    RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\letitedit.Project');
    Log('Removed the letitedit.Project progid');
  end;
  if not RegKeyExists(HKCU, 'Software\Classes\letitedit.Project') then
  begin
    RegDeleteValue(HKCU, 'Software\Classes\.mlt\OpenWithProgids', 'letitedit.Project');
    if RegQueryStringValue(HKCU, 'Software\Classes\.mlt', '', Value) and (Value = 'letitedit.Project') then
      RegDeleteValue(HKCU, 'Software\Classes\.mlt', '');
    RegDeleteKeyIfEmpty(HKCU, 'Software\Classes\.mlt\OpenWithProgids');
    RegDeleteKeyIfEmpty(HKCU, 'Software\Classes\.mlt');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App, Py, Params: String;
  Code, Outcome: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    RemoveAssociation(ExpandConstant('{app}'));
    { before any file is deleted: take the Claude Code / Codex entries back out, delete downloaded models and,
      when asked, the working files (letitedit_setup.py cleanup) }
    App := ExpandConstant('{app}');
    Py := App + '\env\Scripts\python.exe';
    Params := '-I "' + App + '\setup\letitedit_setup.py" cleanup ' + CleanupFlag('');
    if FileExists(Py) then
    begin
      Log('Running: ' + Py + ' ' + Params);
      Outcome := RunWithLimit(Py, Params, App + '\setup', CLEANUP_IDLE_S, CLEANUP_CEILING_S, Code);
      if Outcome = STEP_STUCK then
      begin
        Log('Clean-up stuck: trying once more');
        Outcome := RunWithLimit(Py, Params, App + '\setup', CLEANUP_IDLE_S, CLEANUP_CEILING_S, Code);
      end;
      if Outcome = STEP_DONE then
        Log('Clean-up exit code ' + IntToStr(Code))
      else
      begin
        Log('Clean-up did not finish (' + IntToStr(Outcome) + '); the Claude Code and Codex entries may be left');
        if not UninstallSilent then
          MsgBox('letitedit is being removed, but setup couldn''t finish taking it out of Claude Code and Codex. ' +
                 'If either one complains about letitedit later, remove its letitedit entry there.', mbInformation, MB_OK);
      end;
    end
    else
      Log('No Python environment; Claude Code / Codex entries (if any) are left: ' + Py);
  end;
end;

