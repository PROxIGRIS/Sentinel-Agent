[Setup]
AppName=Test
AppVersion=1.0
DefaultDirName={tmp}
OutputDir=.
[Code]
var
  DownloadPage: TDownloadWizardPage;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;
#include "deps_test.pas"