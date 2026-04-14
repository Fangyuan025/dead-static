; ══════════════════════════════════════════════════════════════
; DEAD STATIC — Inno Setup Installer Script
; ══════════════════════════════════════════════════════════════
;
; Prerequisites:
;   1. Run build.py then package.py first
;   2. Install Inno Setup from https://jrsoftware.org/isinfo.php
;   3. Open this file in Inno Setup Compiler → click Build
;
; This creates a single setup exe: DeadStatic_Setup.exe
; ══════════════════════════════════════════════════════════════

[Setup]
AppName=Dead Static
AppVersion=1.0
AppPublisher=Dead Static
DefaultDirName={autopf}\DeadStatic
DefaultGroupName=Dead Static
OutputDir=installer_output
OutputBaseFilename=DeadStatic_Setup
Compression=lzma2/ultra64
SolidCompression=yes
ExtraDiskSpaceRequired=1610612736
SetupIconFile=
LicenseFile=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Game executable and dependencies (from PyInstaller)
Source: "release\DeadStatic\DeadStatic.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "release\DeadStatic\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

; llama-server runtime + CUDA libs
Source: "release\DeadStatic\runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs

; AI Model
Source: "release\DeadStatic\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs

; Launcher and docs
Source: "release\DeadStatic\Play DeadStatic.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "release\DeadStatic\README.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Dead Static"; Filename: "{app}\Play DeadStatic.bat"; WorkingDir: "{app}"; Comment: "Play Dead Static"
Name: "{group}\Uninstall Dead Static"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Dead Static"; Filename: "{app}\Play DeadStatic.bat"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "Play Dead Static"

[Run]
Filename: "{app}\Play DeadStatic.bat"; Description: "Play Dead Static now!"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: files; Name: "{app}\dead_static_save.json"
