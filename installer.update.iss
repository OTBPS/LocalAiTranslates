#include "installer.common.iss"

[Setup]
AppId={{EDE7309B-0D18-4BC8-94D1-00D5DA17F12E}
AppName={#ProductName} Update
AppVerName={#ProductName} Update {#AppVersion}
AppVersion={#AppVersion}
AppPublisher={#ProductPublisher}
AppCopyright=Copyright (C) 2026 Screen Translator contributors
VersionInfoVersion={#AppFileVersion}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductName={#ProductName}
VersionInfoDescription={#ProductName} incremental update
DefaultDirName={code:GetExistingInstallDir}
PrivilegesRequired=lowest
MinVersion={#MinimumWindowsVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist\updates
OutputBaseFilename=ScreenTranslator-{#AppVersion}-Update
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=screen_translator\assets\app-icon.ico
ChangesAssociations=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName={#ProductName}
DisableReadyPage=yes
Uninstallable=no
CreateUninstallRegKey=no
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
#ifdef SignToolName
SignTool={#SignToolName}
#endif

[Files]
; Python application code is embedded in the onedir launcher. The update
; deliberately excludes Python, Qt, Paddle, CUDA, llama.cpp, and model files.
Source: "dist\ScreenTranslator\{#ProductExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ScreenTranslator\_internal\screen_translator\assets\*"; DestDir: "{app}\_internal\screen_translator\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; Keep Windows Installed Apps pointed at the full installer's uninstaller.
Root: HKCU; Subkey: "{#ProductUninstallKeyDirective}"; ValueType: string; ValueName: "DisplayVersion"; ValueData: "{#AppVersion}"
; DisplayName is what the user actually reads in Installed Apps. Updating only
; DisplayVersion left it showing whichever version last ran a full installer,
; so the list disagreed with the application about what was installed. The
; value must match AppVerName in installer.iss.
Root: HKCU; Subkey: "{#ProductUninstallKeyDirective}"; ValueType: string; ValueName: "DisplayName"; ValueData: "{#ProductName} {#AppVersion}"

[Icons]
Name: "{autoprograms}\{#ProductName}\Screen Translator"; Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; IconFilename: "{app}\{#ProductIcon}"; AppUserModelID: "{#ProductUserModelId}"
Name: "{autodesktop}\Screen Translator"; Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; IconFilename: "{app}\{#ProductIcon}"; AppUserModelID: "{#ProductUserModelId}"; Check: ExistingDesktopShortcut

[Run]
Filename: "{app}\{#ProductExe}"; Parameters: "--show-settings"; Description: "启动 Screen Translator"; Flags: nowait postinstall skipifsilent

[Code]
#include "installer.versioning.iss"
#include "installer.shell.iss"

function GetExistingInstallDir(Param: String): String;
var
  InstallDir: String;
begin
  if RegQueryStringValue(HKCU, '{#ProductUninstallKey}', 'InstallLocation', InstallDir) then
    Result := RemoveBackslashUnlessRoot(InstallDir)
  else
    Result := '';
end;

function ExistingDesktopShortcut(): Boolean;
begin
  Result := FileExists(ExpandConstant('{autodesktop}\Screen Translator.lnk'));
end;

function InitializeSetup(): Boolean;
var
  InstallDir, InstalledVersion: String;
begin
  InstallDir := GetExistingInstallDir('');
  Result := (InstallDir <> '') and
            FileExists(AddBackslash(InstallDir) + '{#ProductExe}') and
            DirExists(AddBackslash(InstallDir) + '_internal') and
            RegQueryStringValue(HKCU, '{#ProductUninstallKey}', 'DisplayVersion', InstalledVersion);
  if not Result then begin
    if not WizardSilent then
      MsgBox('未找到可维护的完整安装版。请先安装 Screen Translator 完整安装包。', mbError, MB_OK);
    Exit;
  end;

  if CompareSemanticVersions(InstalledVersion, '{#MinimumBaseVersion}') < 0 then begin
    Log('Base version rejected: installed=' + InstalledVersion + ', minimum={#MinimumBaseVersion}');
    if not WizardSilent then
      MsgBox('当前完整安装版为 ' + InstalledVersion + '，此补丁要求至少 {#MinimumBaseVersion}。请改用完整安装包升级。', mbError, MB_OK);
    Result := False;
    Exit;
  end;

  if CompareSemanticVersions(InstalledVersion, '{#AppVersion}') > 0 then begin
    Log('Downgrade blocked: installed=' + InstalledVersion + ', package={#AppVersion}');
    if not WizardSilent then
      MsgBox('已安装的版本 ' + InstalledVersion + ' 比此补丁更新。为避免降级，更新已取消。', mbError, MB_OK);
    Result := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    // The icon file is replaced in place, so Explorer has to be told
    // or the taskbar and existing shortcuts keep the cached artwork.
    RefreshShellIcons();
end;
