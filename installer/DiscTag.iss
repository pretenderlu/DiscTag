#ifndef MyAppVersion
  #define VersionFile FileOpen(AddBackslash(SourcePath) + "..\disctag\__init__.py")
  #define VersionLine FileRead(VersionFile)
  #expr FileClose(VersionFile)
  #define MyAppVersion Copy(VersionLine, Pos('"', VersionLine) + 1, RPos('"', VersionLine) - Pos('"', VersionLine) - 1)
#endif
#define MyAppName "DiscTag"
#define MyAppPublisher "pretenderlu"
#define MyAppURL "https://github.com/pretenderlu/DiscTag"

[Setup]
AppId={{D6A7B1D8-7D29-4F0D-9B2C-91E5A6C4D001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}.0
DefaultDirName={localappdata}\Programs\DiscTag
DefaultGroupName=DiscTag
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=DiscTagSetup-v{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\DiscTag.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\DiscTag\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"

[Icons]
Name: "{autoprograms}\DiscTag"; Filename: "{app}\DiscTag.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\DiscTag"; Filename: "{app}\DiscTag.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\DiscTag.exe"; Description: "启动 DiscTag"; Flags: postinstall nowait
