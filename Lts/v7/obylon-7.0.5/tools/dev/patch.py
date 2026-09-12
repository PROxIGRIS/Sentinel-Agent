import re

with open('obylon-setup.iss', 'r', encoding='utf-8') as f:
    iss = f.read()

pattern = re.compile(r"WarmupPage: TOutputProgressWizardPage;.*?BootLog := ExpandConstant", re.DOTALL)

replacement = r'''WarmupPage: TOutputProgressWizardPage;
    LockFile: string;
    ElapsedSecs, MaxWaitSecs, QuoteIdx: Integer;
    Quotes: array[0..5] of string;
  begin
    if CurStep = ssPostInstall then
    begin
      Quotes[0] := 'Asking Windows Defender for permission to exist...';
      Quotes[1] := 'Uploading telemetry profile for advanced cloud analysis...';
      Quotes[2] := 'Still waiting. Defender is really inspecting those 1s and 0s...';
      Quotes[3] := 'Any minute now... We promise this only happens once.';
      Quotes[4] := 'Defender is making sure we aren''t a crypto miner...';
      Quotes[5] := 'Almost there! The cloud is thinking very hard...';
      
      LockFile := ExpandConstant('{app}\warmup.lock');
      DeleteFile(LockFile);
      
      // Warm up the executable asynchronously
      Exec('cmd.exe', '/C ""' + ExpandConstant('{app}\obylon.exe') + '" --warmup"', '', SW_HIDE, ewNoWait, ResultCode);
      
      // Wait for 3 seconds to see if it finishes instantly
      Sleep(3000);
      
      if not FileExists(LockFile) then
      begin
        WarmupPage := CreateOutputProgressPage('Analyzing Security Payload', 'Windows Defender "Block at First Sight" is performing a one-time cloud analysis.');
        WarmupPage.Show;
        
        MaxWaitSecs := 300;
        ElapsedSecs := 3;
        
        while not FileExists(LockFile) do
        begin
          if ElapsedSecs >= MaxWaitSecs then break;
          
          WarmupPage.SetProgress(ElapsedSecs, MaxWaitSecs);
          QuoteIdx := (ElapsedSecs div 10) mod 6;
          WarmupPage.SetText(Quotes[QuoteIdx], 'Elapsed Time: ' + IntToStr(ElapsedSecs) + 's / Estimated Max Timeout: 300s');
          
          Sleep(1000);
          ElapsedSecs := ElapsedSecs + 1;
        end;
        
        WarmupPage.SetProgress(MaxWaitSecs, MaxWaitSecs);
        WarmupPage.SetText('Analysis Complete!', 'The executable has been successfully verified and cached.');
        Sleep(1000);
        
        WarmupPage.Hide;
        WarmupPage.Free;
      end;

      BootLog := ExpandConstant'''

iss = pattern.sub(lambda m: replacement, iss)

with open('obylon-setup.iss', 'w', encoding='utf-8') as f:
    f.write(iss)
