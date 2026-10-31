[Setup]
AppName=Merchant POS Systems
AppVersion=1.0.0
AppPublisher=Merchant Retail
DefaultDirName={autopf}\MerchantPOS
DefaultGroupName=Merchant POS Systems
OutputBaseFilename=MerchantPOS_Setup_v1.0.0
SetupIconFile=..\..\assets\merchant_pos.ico
UninstallDisplayIcon={app}\assets\merchant_pos.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; Flags: unchecked

[Files]
Source: "..\..\dist\MerchantPOS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Merchant POS Systems"; Filename: "{app}\MerchantPOS.exe"
Name: "{autodesktop}\Merchant POS Systems"; Filename: "{app}\MerchantPOS.exe"; Tasks: desktopicon

[Dirs]
Name: "{app}\data";     Permissions: users-modify
Name: "{app}\receipts"; Permissions: users-modify
Name: "{app}\labels";   Permissions: users-modify

[Run]
Filename: "{app}\MerchantPOS.exe"; Description: "Launch Merchant POS"; Flags: nowait postinstall skipifsilent
