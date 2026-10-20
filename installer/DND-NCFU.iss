; Optional second stage. build_windows.ps1 runs EXE probes before invoking ISCC.
#ifndef AppVersion
  #error AppVersion must be supplied by the checked build script
#endif
#ifndef BundleDir
  #error BundleDir must be supplied by the checked build script
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied by the checked build script
#endif
[Setup]
AppId={{29C2AC1B-534A-493D-9E35-1F32F05AFB9E}
AppName=DND-NCFU — Хроники забытых королевств
AppVersion={#AppVersion}
AppPublisher=Проект DND-NCFU
DefaultDirName={localappdata}\Programs\DND-NCFU
DefaultGroupName=DND-NCFU
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#ReleaseDir}
OutputBaseFilename=DND-NCFU-Setup
SetupIconFile={#BundleDir}\_internal\rpg_vkr\ui\assets\DND-NCFU.ico
UninstallDisplayIcon={app}\DND-NCFU.exe
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\DND-NCFU"; Filename: "{app}\DND-NCFU.exe"
Name: "{autodesktop}\DND-NCFU"; Filename: "{app}\DND-NCFU.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\DND-NCFU.exe"; Description: "Запустить DND-NCFU"; Flags: nowait postinstall skipifsilent
; No UninstallDelete for LOCALAPPDATA\DND-NCFU: saves, keys and images survive.
