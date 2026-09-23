#include "installer.common.iss"

[Setup]
AppId={#ProductAppId}
AppName={#ProductName}
AppVerName={#ProductName} {#AppVersion}
AppVersion={#AppVersion}
AppPublisher={#ProductPublisher}
AppCopyright=Copyright (C) 2026 Screen Translator contributors
VersionInfoVersion={#AppFileVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductName={#ProductName}
VersionInfoDescription={#ProductName} installer
UninstallDisplayName={#ProductName}
UninstallDisplayIcon={app}\{#ProductIcon}
DefaultDirName={localappdata}\Programs\{#InstallDirName}
DefaultGroupName={#ProductName}
PrivilegesRequired=lowest
MinVersion={#MinimumWindowsVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
DisableProgramGroupPage=yes
AllowNoIcons=yes
OutputDir=dist\installer
OutputBaseFilename={#OutputBaseName}
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupIconFile=screen_translator\assets\app-icon.ico
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项："; Flags: checkedonce

[Icons]
Name: "{group}\{#ShortcutName}"; Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; IconFilename: "{app}\{#ProductIcon}"; AppUserModelID: "{#ProductUserModelId}"
Name: "{group}\卸载 {#ShortcutName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#ShortcutName}"; Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; IconFilename: "{app}\{#ProductIcon}"; Tasks: desktopicon; AppUserModelID: "{#ProductUserModelId}"

[Run]
Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; Description: "启动 {#ShortcutName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\ScreenTranslator"; Check: ShouldPurgeUserData
Type: filesandordirs; Name: "{localappdata}\ScreenTranslator"; Check: ShouldPurgeUserData

[Code]
#include "installer.versioning.iss"
#include "installer.shell.iss"

var
  PurgeUserData: Boolean;

function HasCommandLineParameter(Name: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), Name) = 0 then begin
      Result := True;
      Exit;
    end;
end;

function InitializeSetup(): Boolean;
var
  InstalledVersion: String;
begin
  Result := True;
#ifdef ClientEdition
  { The two editions share the per-user configuration file and the
    single-instance lock, so only one of them can usefully run on a machine.
    Refusing here is clearer than shipping two entries that fight. }
  if RegQueryStringValue(HKCU, '{#FullUninstallKey}', 'DisplayVersion', InstalledVersion) then begin
    Log('Client installation blocked: full edition ' + InstalledVersion + ' is installed');
    if not WizardSilent then
      MsgBox('这台电脑已安装完整版屏译 ' + InstalledVersion + '。' + #13#10 +
             '完整版本身就能作为主机，无需再安装客户端；如需改用客户端，请先卸载完整版。',
             mbError, MB_OK);
    Result := False;
    Exit;
  end;
#endif
  if RegQueryStringValue(HKCU, '{#ProductUninstallKey}', 'DisplayVersion', InstalledVersion) and
     (CompareSemanticVersions(InstalledVersion, '{#AppVersion}') > 0) then begin
    Log('Downgrade blocked: installed=' + InstalledVersion + ', package={#AppVersion}');
    if not WizardSilent then
      MsgBox('已安装的版本 ' + InstalledVersion + ' 比此安装包更新。为避免损坏配置，安装已取消。', mbError, MB_OK);
    Result := False;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  PurgeUserData := HasCommandLineParameter('/PURGEUSERDATA');
  if (not UninstallSilent) and (not PurgeUserData) then
    PurgeUserData := MsgBox(
      '是否同时删除屏译自己的设置和日志？' + #13#10 + #13#10 +
      '共享模型仓库和训练工作区始终保留，不受卸载影响。',
      mbConfirmation, MB_YESNO) = idYes;
  Result := True;
end;

function ShouldPurgeUserData(): Boolean;
begin
  Result := PurgeUserData;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    // The icon file is replaced in place, so Explorer has to be told
    // or the taskbar and existing shortcuts keep the cached artwork.
    RefreshShellIcons();
end;
