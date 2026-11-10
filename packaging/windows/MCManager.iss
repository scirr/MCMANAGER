; Inno Setup script for the MC Manager installer.
; Built by build_installer.py, which passes AppVersion, StageDir and OutDir.

#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef StageDir
  #error StageDir is required
#endif
#ifndef OutDir
  #define OutDir "."
#endif

#define ServiceName "MCManagerDaemon"

[Setup]
AppId={{0E3B0BEA-C398-4B2F-8D82-59B317372038}
AppName=MC Manager
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=Cris
AppPublisherURL=https://github.com/scirr/MCMANAGER
AppSupportURL=https://github.com/scirr/MCMANAGER/issues
DefaultDirName={autopf}\MCManager
DefaultGroupName=MC Manager
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutDir}
OutputBaseFilename=MCManager-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
CloseApplications=yes
UninstallDisplayName=MC Manager
UninstallDisplayIcon={app}\app\MCManager.exe

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Dirs]
Name: "{commonappdata}\MCManager"; Permissions: users-modify
Name: "{app}\core\logs"; Permissions: users-modify
Name: "{app}\core\run"; Permissions: users-modify

[InstallDelete]
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\core\__pycache__"

[Files]
Source: "{#StageDir}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\core\*"; DestDir: "{app}\core"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MC Manager"; Filename: "{app}\app\MCManager.exe"; WorkingDir: "{app}\app"
Name: "{group}\{cm:UninstallProgram,MC Manager}"; Filename: "{uninstallexe}"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "MCMANAGER_DATA_DIR"; ValueData: "{commonappdata}\MCManager"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\python\python.exe"; Parameters: """{app}\core\mc_config.py"" --install-only"; WorkingDir: "{app}\core"; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: """{app}\core\mc_config.py"" --install-daemon"; WorkingDir: "{app}\core"; Flags: runhidden waituntilterminated
Filename: "{app}\app\MCManager.exe"; Description: "{cm:LaunchProgram,MC Manager}"; WorkingDir: "{app}\app"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{sys}\mc.bat"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"

[Code]
function SetEnvironmentVariable(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure StopService;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Stop-Service -Name {#ServiceName} -Force -ErrorAction SilentlyContinue"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure RemoveService;
var
  Code: Integer;
begin
  StopService;
  Exec(ExpandConstant('{sys}\sc.exe'), 'delete {#ServiceName}', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure WriteLanguage;
var
  Path, Icacls: String;
  Code: Integer;
begin
  ForceDirectories(ExpandConstant('{app}\core'));
  Path := ExpandConstant('{app}\core\language.txt');
  if not FileExists(Path) then
    SaveStringToFile(Path, ActiveLanguage, False);
  Icacls := ExpandConstant('{sys}\icacls.exe');
  Exec(Icacls, '"' + Path + '" /grant *S-1-5-32-545:M', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

// The service runs as SYSTEM and locks run\ to itself: it also lets in the users listed here.
// shortcut: lists the account that ran Setup (elevated with another admin's password, that admin), add others by hand.
procedure WriteDesktopUser;
var
  Path, User: String;
  Users: TArrayOfString;
  I: Integer;
begin
  Path := ExpandConstant('{app}\core\desktop_users.txt');
  User := GetUserNameString;
  if LoadStringsFromFile(Path, Users) then
    for I := 0 to GetArrayLength(Users) - 1 do
      if CompareText(Trim(Users[I]), User) = 0 then
        Exit;
  SetArrayLength(Users, 1);
  Users[0] := User;
  SaveStringsToUTF8File(Path, Users, True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
  begin
    StopService;
    WriteLanguage;
    WriteDesktopUser;
    SetEnvironmentVariable('MCMANAGER_DATA_DIR', ExpandConstant('{commonappdata}\MCManager'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RemoveService;
end;
