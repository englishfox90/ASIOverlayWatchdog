; Inno Setup Script for PFR Sentinel
; Creates a Windows installer that supports upgrades
; Requires: Inno Setup 6.0 or later (https://jrsoftware.org/isinfo.php)
; Version is automatically synced from ../version.py by build scripts

#define MyAppName "PFR Sentinel"
#include "..\version.iss"
#define MyAppPublisher "Paul Fox-Reeks"
#define MyAppExeName "PFRSentinel.exe"
#define MyAppAssocName MyAppName + " File"
#define MyAppAssocExt ".pfrs"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
; New GUID for renamed app - existing ASIOverlayWatchDog installs won't conflict
AppId={{7F8E9A0B-1C2D-3E4F-5A6B-7C8D9E0F1A2B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PFRSentinel
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; Output directory for installer (absolute path to avoid nesting)
OutputDir=..\installer\dist
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
SetupIconFile=..\assets\app_icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Source files from PyInstaller build
Source: "..\dist\PFRSentinel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
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
    // Show info message about data locations
    MsgBox('User data is stored in:' + #13#10 + 
           ExpandConstant('{localappdata}\PFRSentinel\') + #13#10#13#10 +
           '- config.json (preserved during upgrades)' + #13#10 +
           '- Logs\ (rotated daily, kept for 7 days)',
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
      // Don't uninstall - just overwrite files to preserve user data
      // Config.json is now stored in %LOCALAPPDATA%\PFRSentinel\
      // so it won't be affected by upgrades anyway
    end;
  end;
end;
