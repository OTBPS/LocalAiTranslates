#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

#ifndef AppFileVersion
#define AppFileVersion AppVersion + ".0"
#endif

#ifndef MinimumBaseVersion
#define MinimumBaseVersion "0.3.0"
#endif

#define ProductExe "ScreenTranslator.exe"
#define ProductIcon "_internal\screen_translator\assets\app-icon.ico"
#define ProductPublisher "Screen Translator"
#define MinimumWindowsVersion "10.0.22000"

; The full edition carries the models; the client edition captures here and
; sends the work to another device. They are alternative installations of the
; same product, so each owns its own identity, install directory and payload
; while sharing every script below.
#define FullAppId "{{B7F58F3D-7AD0-4617-99BF-7D3DBD3ABAA1}"
#define FullUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{B7F58F3D-7AD0-4617-99BF-7D3DBD3ABAA1}_is1"

#ifdef ClientEdition
  #define ProductName "Screen Translator Client"
  #define ProductAppId "{{5E2C9A41-0F63-4C8E-9D2A-6B4F1C7E83D5}"
  #define ProductUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{5E2C9A41-0F63-4C8E-9D2A-6B4F1C7E83D5}_is1"
  #define ProductUninstallKeyDirective "Software\Microsoft\Windows\CurrentVersion\Uninstall\{{5E2C9A41-0F63-4C8E-9D2A-6B4F1C7E83D5}_is1"
  #define ProductUserModelId "ScreenTranslator.Client"
  #define InstallDirName "ScreenTranslatorClient"
  #define PayloadDir "dist\ScreenTranslatorClient"
  #define OutputBaseName "ScreenTranslator-Client-" + AppVersion + "-Setup"
  #define ShortcutName "屏译客户端"
#else
  #define ProductName "Screen Translator"
  #define ProductAppId FullAppId
  #define ProductUninstallKey FullUninstallKey
  #define ProductUninstallKeyDirective "Software\Microsoft\Windows\CurrentVersion\Uninstall\{{B7F58F3D-7AD0-4617-99BF-7D3DBD3ABAA1}_is1"
  #define ProductUserModelId "ScreenTranslator.Desktop"
  #define InstallDirName "ScreenTranslator"
  #define PayloadDir "dist\ScreenTranslator"
  #define OutputBaseName "ScreenTranslator-" + AppVersion + "-Setup"
  #define ShortcutName "Screen Translator"
#endif
