{ Running a step of setup with a time limit, so setup can never sit there forever (T76, 5 Nov: relocate.py sat at 0 CPU for two hours, once).
  Included in letitedit.iss's [Code] and in tests\runstep_test.iss, so the test runs this very code.
  
  A step can run out two ways:
    * STUCK: the step and everything it started did nothing at all (no CPU, no reads, writes or network) for IdleS seconds. A slow step isn't stuck:
      a slow download or a slow PC keeps these counters moving, however slowly, so it's left alone.
    * TOO LONG: it's still moving, but past CeilingS seconds. A far larger number, so that "every step ends" has no exception.
  Either way the step and everything it started are stopped (a job object, which catches its children too). Inno's own Exec can't do this: it gives no
  process handle, so nothing can wait on it with a limit. This runs inside setup itself, because a watchdog that's a new process could hang the same way.
  Setup is a 32-bit program, so these records are the 32-bit layouts. }

const
  STEP_DONE = 0;       { it ended by itself: Code is its exit code }
  STEP_NOSTART = 1;    { it couldn't start }
  STEP_STUCK = 2;      { stopped: no activity for IdleS seconds }
  STEP_TOOLONG = 3;    { stopped: still moving at CeilingS seconds }
  WAIT_OBJECT_0_ = 0;
  CREATE_SUSPENDED_ = $00000004;
  CREATE_NO_WINDOW_ = $08000000;
  CREATE_UNICODE_ENV_ = $00000400;
  STARTF_USESHOWWINDOW_ = 1;
  JobBasicAndIo = 8;   { JobObjectBasicAndIoAccountingInformation }
  PM_REMOVE_ = 1;

type
  TStepStartup = record
    cb: DWORD; lpReserved, lpDesktop, lpTitle: Longint;
    dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags: DWORD;
    wShowWindow, cbReserved2: Word; lpReserved2, hStdInput, hStdOutput, hStdError: Longint;
  end;
  TStepProcess = record
    hProcess, hThread: Longint; dwProcessId, dwThreadId: DWORD;
  end;
  TStepCounters = record   { JOBOBJECT_BASIC_AND_IO_ACCOUNTING_INFORMATION }
    TotalUser, TotalKernel, PeriodUser, PeriodKernel: Int64;
    PageFaults, TotalProcesses, ActiveProcesses, Terminated: DWORD;
    ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes: Int64;
  end;
  TStepMsg = record
    hwnd: Longint; message: DWORD; wParam, lParam: Longint; time: DWORD; x, y: Longint;
  end;

function StepCreateProcess(lpApp, lpCmd: String; lpProcAttr, lpThreadAttr: Longint; bInherit: BOOL; dwFlags: DWORD; lpEnv: Longint; lpDir: String;
  var si: TStepStartup; var pi: TStepProcess): BOOL; external 'CreateProcessW@kernel32.dll stdcall';
function StepCreateJob(lpAttr: Longint; lpName: Longint): Longint; external 'CreateJobObjectW@kernel32.dll stdcall';
function StepAssign(hJob, hProcess: Longint): BOOL; external 'AssignProcessToJobObject@kernel32.dll stdcall';
function StepTerminateJob(hJob: Longint; code: DWORD): BOOL; external 'TerminateJobObject@kernel32.dll stdcall';
function StepTerminateProcess(hProcess: Longint; code: DWORD): BOOL; external 'TerminateProcess@kernel32.dll stdcall';
function StepQueryJob(hJob: Longint; cls: Integer; var info: TStepCounters; size: DWORD; ret: Longint): BOOL; external 'QueryInformationJobObject@kernel32.dll stdcall';
function StepResume(hThread: Longint): DWORD; external 'ResumeThread@kernel32.dll stdcall';
function StepWait(h: Longint; ms: DWORD): DWORD; external 'WaitForSingleObject@kernel32.dll stdcall';
function StepExitCode(h: Longint; var code: DWORD): BOOL; external 'GetExitCodeProcess@kernel32.dll stdcall';
function StepClose(h: Longint): BOOL; external 'CloseHandle@kernel32.dll stdcall';
function StepLastError(): DWORD; external 'GetLastError@kernel32.dll stdcall';
function StepPeek(var m: TStepMsg; hwnd: Longint; a, b, remove: DWORD): BOOL; external 'PeekMessageW@user32.dll stdcall';
function StepTranslate(var m: TStepMsg): BOOL; external 'TranslateMessage@user32.dll stdcall';
function StepDispatch(var m: TStepMsg): Longint; external 'DispatchMessageW@user32.dll stdcall';
function StepTicks(): DWORD; external 'GetTickCount@kernel32.dll stdcall';

{ keeps setup's window alive while a step runs, as Exec does }
procedure StepPump;
var
  m: TStepMsg;
begin
  while StepPeek(m, 0, 0, 0, PM_REMOVE_) do
  begin
    StepTranslate(m);
    StepDispatch(m);
  end;
end;

{ everything the step and its children have done so far, as one number that only grows }
function StepActivity(hJob, hProcess: Longint; var seen: Int64): Boolean;
var
  c: TStepCounters;
begin
  Result := False;
  if hJob = 0 then
    Exit;
  if StepQueryJob(hJob, JobBasicAndIo, c, 96, 0) then
  begin
    seen := c.TotalUser + c.TotalKernel + c.ReadOps + c.WriteOps + c.OtherOps + c.ReadBytes + c.WriteBytes + c.OtherBytes + c.TotalProcesses;
    Result := True;
  end;
end;

function RunWithLimit(const Exe, Params, Dir: String; IdleS, CeilingS: Integer; var Code: Integer): Integer;
var
  si: TStepStartup;
  pi: TStepProcess;
  hJob: Longint;
  flags, ec, startTick, lastMove, now_: DWORD;
  before, seen: Int64;
  prev, canWatch: Boolean;
begin
  Code := -1;
  si.cb := 68;
  si.dwFlags := STARTF_USESHOWWINDOW_;
  si.wShowWindow := 0;
  flags := CREATE_SUSPENDED_ or CREATE_NO_WINDOW_;     { no console: a click in one can freeze what's writing to it, and nothing of ours opens one }
  hJob := StepCreateJob(0, 0);
  prev := EnableFsRedirection(False);     { setup is 32-bit: without this, System32 means the 32-bit copy }
  if not StepCreateProcess(Exe, '"' + Exe + '" ' + Params, 0, 0, False, flags, 0, Dir, si, pi) then
  begin
    Code := StepLastError();
    EnableFsRedirection(prev);
    if hJob <> 0 then
      StepClose(hJob);
    Result := STEP_NOSTART;
    Exit;
  end;
  EnableFsRedirection(prev);
  if hJob <> 0 then
    if not StepAssign(hJob, pi.hProcess) then
    begin
      Log('The step could not join a job (error ' + IntToStr(StepLastError()) + '); only its own process can be stopped, and only the time limit applies.');
      StepClose(hJob);
      hJob := 0;
    end;
  StepResume(pi.hThread);
  StepClose(pi.hThread);

  startTick := StepTicks();
  lastMove := startTick;
  before := -1;
  canWatch := hJob <> 0;
  Result := STEP_DONE;
  while StepWait(pi.hProcess, 200) <> WAIT_OBJECT_0_ do
  begin
    StepPump;
    now_ := StepTicks();
    if canWatch and StepActivity(hJob, pi.hProcess, seen) then
      if seen <> before then
      begin
        before := seen;
        lastMove := now_;
      end;
    if canWatch and ((now_ - lastMove) div 1000 >= IdleS) then
    begin
      Log('Stopping the step: no activity at all for ' + IntToStr(IdleS) + ' s, after ' + IntToStr((now_ - startTick) div 1000) + ' s.');
      Result := STEP_STUCK;
      Break;
    end;
    if (now_ - startTick) div 1000 >= CeilingS then
    begin
      Log('Stopping the step: still running after ' + IntToStr(CeilingS) + ' s.');
      Result := STEP_TOOLONG;
      Break;
    end;
  end;
  if Result = STEP_DONE then
  begin
    if StepExitCode(pi.hProcess, ec) then
      Code := ec;
    { its children, if it left any, end with it: nothing of a step outlives the step }
    if hJob <> 0 then
      StepTerminateJob(hJob, 0);
  end
  else
  begin
    if hJob <> 0 then
      StepTerminateJob(hJob, 1)
    else
      StepTerminateProcess(pi.hProcess, 1);
    StepWait(pi.hProcess, 15000);
    Code := -1;
  end;
  StepClose(pi.hProcess);
  if hJob <> 0 then
    StepClose(hJob);
end;
