; Inno Setup: instalador de Imago. Requiere Inno Setup 6.3 o superior.
; empaquetar.ps1 pasa MyAppVersion desde la fuente única imago_version.py.
; Resultado: installer\ImagoSetup.exe
;
; IMPORTANTE: antes de compilar el instalador hay que haber construido el .exe
; (dist\Imago\ con PyInstaller). Este script empaqueta esa carpeta.

#ifndef MyAppVersion
  #error MyAppVersion no definida. Ejecuta empaquetar.ps1 para compilar.
#endif

[Setup]
AppName=Imago
AppVersion={#MyAppVersion}
AppPublisher=AVNSoft
DefaultDirName={autopf}\Imago
DefaultGroupName=Imago
UninstallDisplayIcon={app}\Imago.ico
; Muestra la GPLv3 en una página del asistente durante la instalación. El
; archivo LICENSE está en la raíz del repositorio (mismo que se copia a la
; carpeta instalada desde empaquetar.ps1).
LicenseFile=LICENSE
OutputBaseFilename=ImagoSetup
OutputDir=installer
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=icons\imago.ico
ChangesAssociations=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
; Nombre del acceso directo de desinstalación en el menú Inicio, en los tres
; idiomas de Imago. Sigue el idioma elegido al instalar (el mismo que reutiliza
; el asistente del desinstalador).
es.UninstallImago=Desinstalar Imago
en.UninstallImago=Uninstall Imago
fr.UninstallImago=Désinstaller Imago

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Imago\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "icons\imago.ico"; DestDir: "{app}"; DestName: "Imago.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\Imago"; Filename: "{app}\Imago.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Imago.ico"; IconIndex: 0; AppUserModelID: "AVNSoft.Imago"
Name: "{group}\{cm:UninstallImago}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Imago"; Filename: "{app}\Imago.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Imago.ico"; IconIndex: 0; AppUserModelID: "AVNSoft.Imago"; Tasks: desktopicon

[Registry]
; Registro no invasivo para «Abrir con»: anuncia los formatos admitidos, pero
; no cambia la aplicación predeterminada que el usuario tenga para cada uno.
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Imago"
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Imago.ico,0"
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Imago.exe"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".imago"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".png"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".jpg"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".jpeg"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".bmp"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".gif"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".webp"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".tif"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".tiff"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".tga"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".ico"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".svg"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".svgz"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".psd"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".psb"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".avif"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".heic"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".heif"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\Imago.exe\SupportedTypes"; ValueType: string; ValueName: ".jxl"; ValueData: ""

[Run]
Filename: "{app}\Imago.exe"; Description: "{cm:LaunchProgram,Imago}"; Flags: nowait postinstall skipifsilent
