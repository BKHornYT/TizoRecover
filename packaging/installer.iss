; Inno Setup script: TizoRecover-<version>-setup.exe from the folder build (dist\TizoRecover\).
; Built by packaging\build.ps1 / the release workflow:  ISCC /DAppVersion=0.2.0 packaging\installer.iss
;
; Installs per user (no administrator prompt), like the electron-builder installers of the other
; Tizo apps; "for all users" is offered on the first page. The .installed marker tells the app it
; may update itself: the in-app updater runs a newer setup with /SILENT /UPDATE=1, and the
; [Run] entry for that case starts the new version again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E4C3A52-9B1F-4E3B-A7D2-5C8F0B1E2D47}
AppName=TizoRecover
AppVersion={#AppVersion}
AppVerName=TizoRecover {#AppVersion}
AppPublisher=TizoRecover contributors
AppPublisherURL=https://github.com/BKHornYT/TizoRecover
AppSupportURL=https://github.com/BKHornYT/TizoRecover/issues
AppUpdatesURL=https://github.com/BKHornYT/TizoRecover/releases
DefaultDirName={autopf}\TizoRecover
DefaultGroupName=TizoRecover
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\LICENSE
OutputDir=..\release
OutputBaseFilename=TizoRecover-{#AppVersion}-setup
SetupIconFile=tizorecover.ico
UninstallDisplayIcon={app}\TizoRecover.exe
UninstallDisplayName=TizoRecover
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
VersionInfoVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; a previous version's libraries must not linger next to the new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\TizoRecover\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installed.marker"; DestDir: "{app}"; DestName: ".installed"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\TizoRecover"; Filename: "{app}\TizoRecover.exe"
Name: "{autodesktop}\TizoRecover"; Filename: "{app}\TizoRecover.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TizoRecover.exe"; Description: "{cm:LaunchProgram,TizoRecover}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\TizoRecover.exe"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;
