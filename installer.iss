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
DefaultDirName={localappdata}\Programs\ScreenTranslator
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
OutputBaseFilename=ScreenTranslator-{#AppVersion}-Setup
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
Source: "dist\ScreenTranslator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他选项："; Flags: checkedonce

[Icons]
Name: "{group}\Screen Translator"; Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; IconFilename: "{app}\{#ProductIcon}"; AppUserModelID: "{#ProductUserModelId}"
Name: "{group}\卸载 Screen Translator"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Screen Translator"; Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; IconFilename: "{app}\{#ProductIcon}"; Tasks: desktopicon; AppUserModelID: "{#ProductUserModelId}"

[Run]
Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; Description: "启动 Screen Translator"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\ScreenTranslator"; Check: ShouldPurgeUserData
Type: filesandordirs; Name: "{localappdata}\ScreenTranslator"; Check: ShouldPurgeUserData

[Code]
#include "installer.versioning.iss"

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
