; Inno Setup Script for ASIOverlayWatchDog
; Creates a Windows installer that supports upgrades
; Requires: Inno Setup 6.0 or later (https://jrsoftware.org/isinfo.php)

#define MyAppName "ASIOverlayWatchDog"
#define MyAppVersion "2.0.2"
#define MyAppPublisher "Paul Fox-Reeks"
#define MyAppExeName "ASIOverlayWatchDog.exe"
#define MyAppAssocName MyAppName + " File"
#define MyAppAssocExt ".asiow"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
; (To generate a new GUID, click Tools | Generate GUID inside the IDE.)
AppId={{8B9C4A5D-6E7F-4A8B-9C0D-1E2F3A4B5C6D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output directory for installer
OutputDir=installer\dist
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-setup
; Compression
Compression=lzma
SolidCompression=yes
; Modern UI
WizardStyle=modern
; Privileges (run as user, not admin)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Uninstall
UninstallDisplayIcon={app}\{#MyAppExeName}
; Setup icon
SetupIconFile=..\app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Source files from PyInstaller build
Source: "dist\ASIOverlayWatchDog\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
; Start Menu shortcut
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
; Desktop shortcut (optional, user-selectable)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Option to launch application after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up any generated files (but NOT user data in %LOCALAPPDATA%)
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
{ Custom installation messages }
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    // Show info message about log location
    MsgBox('Log files are stored in:' + #13#10 + 
           ExpandConstant('{localappdata}\ASIOverlayWatchDog\Logs') + #13#10#13#10 +
           'Logs are automatically rotated daily and kept for 7 days.',
           mbInformation, MB_OK);
  end;
end;

{ Detect and handle previous installation }
function GetUninstallString: String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade: Boolean;
begin
  Result := (GetUninstallString <> '');
end;

function UnInstallOldVersion: Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
  { Return Values: }
  { 1 - uninstall string is empty }
  { 2 - error executing the UnInstallString }
  { 3 - successfully executed the UnInstallString }

  { default return value }
  Result := 0;

  { get the uninstall string of the old app }
  sUnInstallString := GetUninstallString;
  if sUnInstallString <> '' then begin
    sUnInstallString := RemoveQuotes(sUnInstallString);
    if Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
      Result := 3
    else
      Result := 2;
  end else
    Result := 1;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep=ssInstall) then
  begin
    if (IsUpgrade) then
    begin
      UnInstallOldVersion;
    end;
  end;
end;
