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
; Close a running instance before upgrading — it locks the exe and _internal
; DLLs/pyds, which would otherwise fail the file copy. Restart Manager closes
; (and, with RestartApplications, relaunches) instances the installer can reach.
; An elevated auto-start instance is closed separately via --shutdown in
; PrepareToInstall below, since a non-elevated installer can't terminate it.
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "runadmin"; Description: "Run as Administrator (recommended for USB camera recovery)"; GroupDescription: "Privileges:"; Flags: unchecked
Name: "startupreg"; Description: "Run PFR Sentinel when Windows starts (auto-resume capture after a reboot)"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Source files from PyInstaller build.
; This also carries nina_plugin\PFRSentinel.NINA.dll (staged by build_sentinel.bat,
; bundled by PFRSentinel.spec) — recursesubdirs picks it up, no separate entry needed.
Source: "..\dist\PFRSentinel\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
; Start Menu shortcut
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
; Desktop shortcut (optional, user-selectable)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; If user selected "Run as Administrator", set Windows compatibility flag
; This makes the EXE always prompt for UAC elevation (same as right-click > Properties > Compatibility > Run as administrator)
Root: HKCU; Subkey: "Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"; ValueType: string; ValueName: "{app}\{#MyAppExeName}"; ValueData: "RUNASADMIN"; Flags: uninsdeletevalue; Tasks: runadmin

[Run]
; Option to launch application after install
; shellexec flag allows UAC elevation if "Run as Administrator" task was selected
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Clean up any generated files (but NOT user data in %LOCALAPPDATA%)
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
{ Customize the finished page with data location and analytics notice }
procedure CurPageChanged(CurPageID: Integer);
var
  Msg: String;
begin
  if CurPageID = wpFinished then
  begin
    Msg := 'Setup has finished installing {#MyAppName} on your computer.' + #13#10 + #13#10 +
           'Anonymous usage analytics is enabled by default to help improve ' +
           'the app. No personal data is collected. You can disable this ' +
           'in Settings > System.';
    WizardForm.FinishedLabel.Caption := Msg;
  end;
end;

{ Detect old ASIOverlayWatchDog installation by searching registry }
function GetOldAppUninstallString: String;
var
  sUnInstPath: String;
  sUnInstallString: String;
  sDisplayName: String;
  Keys: TArrayOfString;
  i: Integer;
begin
  Result := '';
  { Search for ASIOverlayWatchDog in uninstall registry - check HKCU first (lowest privileges) }
  if RegGetSubkeyNames(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall', Keys) then
  begin
    for i := 0 to GetArrayLength(Keys) - 1 do
    begin
      sUnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + Keys[i];
      if RegQueryStringValue(HKCU, sUnInstPath, 'DisplayName', sDisplayName) then
      begin
        if Pos('ASIOverlayWatchDog', sDisplayName) > 0 then
        begin
          RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
          Result := sUnInstallString;
          Exit;
        end;
      end;
    end;
  end;
  { Also check HKLM }
  if RegGetSubkeyNames(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall', Keys) then
  begin
    for i := 0 to GetArrayLength(Keys) - 1 do
    begin
      sUnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + Keys[i];
      if RegQueryStringValue(HKLM, sUnInstPath, 'DisplayName', sDisplayName) then
      begin
        if Pos('ASIOverlayWatchDog', sDisplayName) > 0 then
        begin
          RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString);
          Result := sUnInstallString;
          Exit;
        end;
      end;
    end;
  end;
end;

function HasOldAppInstalled: Boolean;
begin
  Result := (GetOldAppUninstallString <> '');
end;

function UninstallOldApp: Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
  Result := 0;
  sUnInstallString := GetOldAppUninstallString;
  if sUnInstallString <> '' then begin
    sUnInstallString := RemoveQuotes(sUnInstallString);
    if Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES','', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
      Result := 1
    else
      Result := 2;
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

{ ===================================================================== }
{  PostHog Analytics — track install/upgrade/error events                }
{ ===================================================================== }

var
  PostHogDistinctId: String;   { Cached for the lifetime of the installer }
  PostHogIsUpgrade: Boolean;

function HexDigit(N: Integer): Char;
begin
  if N < 10 then
    Result := Chr(Ord('0') + N)
  else
    Result := Chr(Ord('a') + N - 10);
end;

function RandomHex(Len: Integer): String;
var
  i: Integer;
begin
  Result := '';
  for i := 1 to Len do
    Result := Result + HexDigit(Random(16));
end;

function GenerateUUID: String;
{ Generate a v4-like UUID: 8-4-4-4-12 hex }
begin
  Result := RandomHex(8) + '-' + RandomHex(4) + '-4' + RandomHex(3) + '-' +
            HexDigit(8 + Random(4)) + RandomHex(3) + '-' + RandomHex(12);
end;

function GetConfigPath: String;
begin
  Result := ExpandConstant('{localappdata}\PFRSentinel\config.json');
end;

function GetConfigDir: String;
begin
  Result := ExpandConstant('{localappdata}\PFRSentinel');
end;

function ReadConfigFile: String;
{ Load entire config.json into a single string, or '' if missing }
var
  Lines: TArrayOfString;
  i: Integer;
begin
  Result := '';
  if FileExists(GetConfigPath) then
  begin
    if LoadStringsFromFile(GetConfigPath, Lines) then
      for i := 0 to GetArrayLength(Lines) - 1 do
        Result := Result + Lines[i];
  end;
end;

function ReadJsonValue(const Json, Key: String): String;
{ Minimal JSON string-value reader — finds "key": "value" }
var
  SearchKey, Rest: String;
  StartPos, EndPos: Integer;
begin
  Result := '';
  SearchKey := '"' + Key + '"';
  StartPos := Pos(SearchKey, Json);
  if StartPos = 0 then Exit;

  Rest := Copy(Json, StartPos + Length(SearchKey), Length(Json));
  StartPos := Pos('"', Rest);
  if StartPos = 0 then Exit;
  Rest := Copy(Rest, StartPos + 1, Length(Rest));
  EndPos := Pos('"', Rest);
  if EndPos = 0 then Exit;
  Result := Copy(Rest, 1, EndPos - 1);
end;

function IsAnalyticsEnabled: Boolean;
{ Check if user has opted out via config. Default is enabled. }
var
  ConfigText: String;
begin
  Result := True;
  ConfigText := ReadConfigFile;
  if (Pos('"analytics_enabled": false', ConfigText) > 0) or
     (Pos('"analytics_enabled":false', ConfigText) > 0) then
    Result := False;
end;

function GetOrCreateDistinctId: String;
{ Read posthog_distinct_id from config, or generate a UUID and seed it }
var
  ConfigText, ConfigDir: String;
begin
  { Return cached value if already resolved }
  if PostHogDistinctId <> '' then
  begin
    Result := PostHogDistinctId;
    Exit;
  end;

  { Try to read from existing config (upgrade path) }
  ConfigText := ReadConfigFile;
  if ConfigText <> '' then
    Result := ReadJsonValue(ConfigText, 'posthog_distinct_id');

  { Generate a new UUID for fresh installs }
  if Result = '' then
  begin
    Result := GenerateUUID;

    { Seed config.json so the app picks up the same distinct_id on first launch.
      Only create the file if it doesn't exist — never overwrite an existing
      config (the app will generate its own distinct_id on first launch). }
    if not FileExists(GetConfigPath) then
    begin
      ConfigDir := GetConfigDir;
      if not DirExists(ConfigDir) then
        ForceDirectories(ConfigDir);

      SaveStringToFile(GetConfigPath,
        '{' + #13#10 +
        '    "posthog_distinct_id": "' + Result + '"' + #13#10 +
        '}' + #13#10,
        False);
      Log('PostHog: seeded distinct_id into config.json for fresh install');
    end
    else
      Log('PostHog: config.json exists but lacks distinct_id, app will generate on first launch');
  end;

  PostHogDistinctId := Result;
end;

procedure SendPostHogEvent(const EventName, PropertiesJson: String);
{ Fire-and-forget POST to PostHog capture API.
  PropertiesJson should be the inner JSON object body (no outer braces). }
var
  Http: Variant;
  Json: String;
  DistinctId: String;
begin
  if not IsAnalyticsEnabled then Exit;

  DistinctId := GetOrCreateDistinctId;
  try
    Json := '{' +
      '"api_key": "phc_yZQPicEvLtuwo4ws6uMCX2RuLc23fsJVbrh7PdSBggyt",' +
      '"event": "' + EventName + '",' +
      '"distinct_id": "' + DistinctId + '",' +
      '"properties": {' +
        '"version": "{#MyAppVersion}",' +
        '"installer": "inno_setup"' +
        PropertiesJson +
      '}' +
    '}';

    Http := CreateOleObject('WinHttp.WinHttpRequest.5.1');
    Http.Open('POST', 'https://us.i.posthog.com/capture/', False);
    Http.SetRequestHeader('Content-Type', 'application/json');
    Http.SetTimeouts(2000, 2000, 2000, 2000);
    Http.Send(Json);
    Log('PostHog: sent ' + EventName + ' event');
  except
    Log('PostHog: failed to send event (non-critical)');
  end;
end;

{ ===================================================================== }
{  Close / relaunch a running instance across an upgrade                 }
{ ===================================================================== }

function AutostartTaskExists: Boolean;
{ True if the logon scheduled task is registered (auto-start is enabled). }
var
  ResultCode: Integer;
begin
  Result := Exec('schtasks.exe', '/Query /TN "PFR Sentinel Autostart"', '',
                 SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
{ Ask a running instance to quit GRACEFULLY before we overwrite its files.
  Restart Manager (CloseApplications) handles a normally-launched instance, but
  the auto-start logon task runs the app elevated (/RL HIGHEST) and a
  non-elevated installer cannot terminate an elevated process. The app can be
  asked to exit itself, though: --shutdown signals the running instance over its
  single-instance channel (works regardless of elevation, and releases the
  camera cleanly). No-op on builds that predate --shutdown — Restart Manager and
  the close-applications prompt remain the fallback. }
var
  ResultCode: Integer;
  ExePath: String;
  Tries: Integer;
begin
  Result := '';
  ExePath := ExpandConstant('{app}\{#MyAppExeName}');
  if not FileExists(ExePath) then
    Exit;
  Log('PrepareToInstall: asking any running instance to exit (--shutdown)...');
  { Send quit and poll until the instance is gone (file locks released).
    --shutdown exits 0 when it signalled a live instance, 1 when none is
    running; re-poll while it keeps reporting 0. Capped at ~100s (100 x 1s) —
    graceful teardown can take ~75s (timelapse flush) and the shutdown watchdog
    force-kills at 90s, so the poll must outlast the watchdog rather than
    giving up first. An old build (which errors on the unknown flag, exit
    code <> 0) still can't stall the installer beyond one failed attempt. }
  Tries := 0;
  while (Tries < 100)
        and ShellExec('', ExePath, '--shutdown', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
        and (ResultCode = 0) do
  begin
    Sleep(1000);
    Tries := Tries + 1;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  InstallType: String;
  ResultCode: Integer;
begin
  if (CurStep=ssInstall) then
  begin
    { Cache upgrade status before anything changes }
    PostHogIsUpgrade := IsUpgrade;

    { Uninstall old ASIOverlayWatchDog if present }
    if HasOldAppInstalled then
    begin
      Log('Found old ASIOverlayWatchDog installation, uninstalling...');
      UninstallOldApp;
    end;

    if PostHogIsUpgrade then
    begin
      // Don't uninstall PFRSentinel - just overwrite files to preserve user data
      // Config.json is now stored in %LOCALAPPDATA%\PFRSentinel\
      // so it won't be affected by upgrades anyway
    end;

    { Send install_started so we can detect failed installs
      (install_started without a matching app_installed = failure) }
    if PostHogIsUpgrade then
      InstallType := 'upgrade'
    else
      InstallType := 'fresh';
    SendPostHogEvent('install_started',
      ',"install_type": "' + InstallType + '"');
  end;

  if (CurStep=ssPostInstall) then
  begin
    { Send success event after files are written }
    if PostHogIsUpgrade then
      InstallType := 'upgrade'
    else
      InstallType := 'fresh';
    SendPostHogEvent('app_installed',
      ',"install_type": "' + InstallType + '"');

    { Register the Windows logon task by reusing the app's own --register-startup
      path (schtasks logic lives only in services/autostart.py). ShellExec honours
      the RUNASADMIN AppCompat flag so it elevates when "Run as Administrator" was
      selected; otherwise the app self-elevates for the schtasks call. We swallow
      any failure (incl. a declined UAC prompt) so install never aborts. }
    if WizardIsTaskSelected('startupreg') then
    begin
      if not ShellExec('', ExpandConstant('{app}\{#MyAppExeName}'),
                       '--register-startup', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
        Log('Startup: could not launch --register-startup (non-fatal)');
    end;

    { After a SILENT UPGRADE, if the logon task exists, relaunch now so capture
      resumes without waiting for the next logon. /Run uses the task's stored
      HIGHEST privileges — an elevated relaunch with no UAC prompt. The single-
      instance guard makes this a no-op if something already relaunched.
      Gated on WizardSilent: in an interactive install the final "Launch PFR
      Sentinel" page is the user's one chance to ask for it to open. Relaunching
      here as well would start the app (in --tray) before they answer, so the
      app appears already-open behind the launch prompt. Silent installs have no
      such page, so the relaunch stays the unattended resume path there. }
    if PostHogIsUpgrade and AutostartTaskExists and WizardSilent then
      Exec('schtasks.exe', '/Run /TN "PFR Sentinel Autostart"', '',
           SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;

{ ===================================================================== }
{  NINA plugin cleanup on uninstall                                      }
{                                                                        }
{  The plugin is installed at runtime (not by Setup) into the PER-USER   }
{  %LOCALAPPDATA%\NINA\Plugins\<version>\PFRSentinel.NINA\, so Inno has  }
{  no record of it and will not remove it. This mirrors the guards in    }
{  services\nina_plugin_install.py::check_removable — a bug here deletes }
{  someone else's plugin. A folder only qualifies when it:               }
{    * sits exactly two levels under ...\NINA\Plugins (we build the path,}
{      and the middle component must parse as a version number);         }
{    * is named exactly PFRSentinel.NINA;                                }
{    * is a real directory, not a symlink/junction (checked on BOTH the  }
{      version folder and the plugin folder — DelTree would otherwise    }
{      follow a link out of the plugins root);                           }
{    * contains PFRSentinel.NINA.dll, or is empty.                       }
{  Anything else is logged and left alone. Best-effort throughout: a     }
{  failure must never block the uninstall.                               }
{ ===================================================================== }

function IsVersionFolderName(const Name: String): Boolean;
{ '3.0.0' -> True. Digits and dots only, 1..4 parts, every part non-empty.
  Matches _parse_version() in nina_plugin_install.py. }
var
  i, Parts, PartLen: Integer;
  C: Char;
begin
  Result := False;
  if Name = '' then Exit;
  Parts := 1;
  PartLen := 0;
  for i := 1 to Length(Name) do
  begin
    C := Name[i];
    if C = '.' then
    begin
      if PartLen = 0 then Exit;
      Parts := Parts + 1;
      PartLen := 0;
    end
    else if (C >= '0') and (C <= '9') then
      PartLen := PartLen + 1
    else
      Exit;
  end;
  Result := (PartLen > 0) and (Parts <= 4);
end;

function IsReparsePoint(const Path: String): Boolean;
{ Symlink or NTFS junction. $400 = FILE_ATTRIBUTE_REPARSE_POINT. }
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(Path, FindRec) then
  try
    Result := (FindRec.Attributes and $400) <> 0;
  finally
    FindClose(FindRec);
  end;
end;

function PluginDirLooksLikeOurs(const Dir: String): Boolean;
{ True when the folder is empty, or contains PFRSentinel.NINA.dll. }
var
  FindRec: TFindRec;
  HasAny, HasDll: Boolean;
begin
  HasAny := False;
  HasDll := False;
  if FindFirst(AddBackslash(Dir) + '*', FindRec) then
  try
    repeat
      if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
      begin
        HasAny := True;
        if CompareText(FindRec.Name, 'PFRSentinel.NINA.dll') = 0 then
          HasDll := True;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
  Result := (not HasAny) or HasDll;
end;

procedure RemoveOneNinaPluginDir(const Dir: String);
begin
  if IsReparsePoint(Dir) then
  begin
    Log('NINA plugin: refusing to delete ' + Dir + ' - it is a link, not a real folder.');
    Exit;
  end;
  if not PluginDirLooksLikeOurs(Dir) then
  begin
    Log('NINA plugin: refusing to delete ' + Dir + ' - it does not contain PFRSentinel.NINA.dll.');
    Exit;
  end;
  if DelTree(Dir, True, True, True) then
    Log('NINA plugin: removed ' + Dir)
  else
    Log('NINA plugin: could not remove ' + Dir + ' (non-fatal - is NINA running?)');
end;

procedure RemoveNinaPlugin;
{ Sweep every <version> folder, not just the current one: an install left under
  an older plugin-API folder must be cleaned up too. }
var
  PluginsRoot, VersionDir, TargetDir: String;
  FindRec: TFindRec;
begin
  PluginsRoot := ExpandConstant('{localappdata}\NINA\Plugins');
  if not DirExists(PluginsRoot) then
    Exit;
  if not FindFirst(AddBackslash(PluginsRoot) + '*', FindRec) then
    Exit;
  try
    repeat
      { $10 = FILE_ATTRIBUTE_DIRECTORY }
      if ((FindRec.Attributes and $10) <> 0) and
         (FindRec.Name <> '.') and (FindRec.Name <> '..') and
         IsVersionFolderName(FindRec.Name) then
      begin
        VersionDir := AddBackslash(PluginsRoot) + FindRec.Name;
        if IsReparsePoint(VersionDir) then
          Log('NINA plugin: skipping linked version folder ' + VersionDir)
        else
        begin
          TargetDir := AddBackslash(VersionDir) + 'PFRSentinel.NINA';
          if DirExists(TargetDir) then
            RemoveOneNinaPluginDir(TargetDir);
        end;
      end;
    until not FindNext(FindRec);
  finally
    FindClose(FindRec);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  { Remove the logon task on uninstall - it lives outside the install dir, so
    file cleanup won't catch it. Runs before files are deleted so the exe still
    exists. Best-effort: a missing task or declined elevation must not block uninstall. }
  if CurUninstallStep = usUninstall then
  begin
    if FileExists(ExpandConstant('{app}\{#MyAppExeName}')) then
      ShellExec('', ExpandConstant('{app}\{#MyAppExeName}'),
                '--unregister-startup', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    { The NINA plugin lives in per-user LOCALAPPDATA, outside the install
      directory, so nothing else here would ever remove it. }
    RemoveNinaPlugin;
  end;
end;
