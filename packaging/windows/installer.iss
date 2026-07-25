; Inno Setup script for the Insurance Policy Extractor.
;
; Produces a single InsurancePolicyExtractorSetup.exe that installs the
; PyInstaller onefolder build (dist/InsurancePolicyExtractor) into
; Program Files, with Start Menu / optional desktop shortcuts and a proper
; uninstaller. The app itself is a local Flask server that opens itself in
; the OS default browser (no native window, no WebView2/WebKitGTK
; dependency), so this installer works unmodified on Windows 7 SP1 through
; Windows 11.
;
; Build (after `pyinstaller app.spec` has produced dist\InsurancePolicyExtractor):
;   iscc packaging\windows\installer.iss
;
; Output: packaging\windows\Output\InsurancePolicyExtractorSetup.exe

#define MyAppName "Insurance Policy Extractor"
#define MyAppVersion GetEnv("APP_VERSION")
#if MyAppVersion == ""
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "Insurance Policy Extractor"
#define MyAppExeName "InsurancePolicyExtractor.exe"
#define SourceDir "..\..\dist\InsurancePolicyExtractor"

[Setup]
AppId={{7B4B6C8C-6C1E-4E9D-9D2C-4A2E9E9B7A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=InsurancePolicyExtractorSetup
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Windows 7 SP1 (6.1) and later — the app has no WebView2/native-window
; dependency, it just runs a local server and opens the default browser.
MinVersion=6.1sp1
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bundled by the CI build step (not committed to git — see build.yml). The
; frozen Python 3.8 exe links against the Universal C Runtime, which ships
; built into Windows 10+ but is NOT present on a stock Windows 7 SP1 install;
; without it the app fails to launch at all with a missing api-ms-win-crt-*.dll
; error, even though this installer's MinVersion=6.1sp1 runs fine. Skipped
; automatically (see VCRedistNeedsInstall) when already present.
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Visual C++ runtime (needed on Windows 7)…"; Check: VCRedistNeedsInstall; Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Skip the (silent, ~15s) redistributable install whenever a new-enough
// VC++ 2015-2022 x64 runtime is already on the machine — true on Windows 10/11
// and on any Windows 7 box that already has it from another app.
function VCRedistNeedsInstall: Boolean;
var
  Installed: Cardinal;
begin
  Result := not (RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64', 'Installed', Installed) and (Installed = 1));
end;
