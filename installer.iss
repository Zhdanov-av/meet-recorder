; Inno Setup Script для сборки MeetRecorder-Setup.exe
#define MyAppName "Meet Recorder"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "MeetRecorder"
#define MyAppExeName "MeetRecorder.exe"

[Setup]
AppId={{8B3F5D92-4C10-4A9E-B7D4-2D9E8F3C7E12}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MeetRecorder
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Разрешаем пользователю выбрать произвольную папку установки
DisableDirPage=no
OutputDir=release
OutputBaseFilename=MeetRecorder-Setup-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\icon.ico

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать значок на Рабочем столе"; GroupDescription: "Дополнительные значки:"

[Dirs]
; Папка recordings с полными правами записи для пользователей и защитой от удаления
Name: "{app}\recordings"; Permissions: users-full; Flags: uninsneveruninstall

[Files]
; Все файлы собранного приложения
Source: "dist\MeetRecorder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName}\Удалить {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName} прямо сейчас"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Хотите также удалить скачанные модели Whisper (занимающие до 1.5-3 ГБ) из кэша пользователя?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec('powershell.exe', '-NoProfile -Command "Remove-Item -Path \"$HOME\.cache\huggingface\hub\models--Systran--faster-whisper-*\" -Recurse -Force -ErrorAction SilentlyContinue"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
