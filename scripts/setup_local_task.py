# -*- coding: utf-8 -*-
"""注册 Windows 计划任务：本机兜底采集（每天 06:30 / 14:30 / 18:30 自动运行）。

用法:
    python scripts/setup_local_task.py

说明:
    - 任务名: ExpertDBFallback
    - 优先以 SYSTEM 账户注册（电脑开机即可执行、无需用户登录；需要管理员权限）
    - 若权限不足，自动降级为"当前用户"任务（需用户登录电脑后运行，锁屏不影响）
    - 若电脑在计划时间处于关机状态，开机后会自动补跑一次（StartWhenAvailable）
    - 删除任务: schtasks /Delete /TN ExpertDBFallback /F
"""
import os
import subprocess
import sys
import tempfile

PYTHON = sys.executable
RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_runner.py")


def build_xml(principal_block):
    return '''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>专家库动态采集-本机兜底(国内网络直连)，每天06:30/14:30/18:30自动运行并同步GitHub</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-08-27T06:30:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-08-27T14:30:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <CalendarTrigger>
      <StartBoundary>2026-08-27T18:30:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    %s
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>%s</Command>
      <Arguments>&quot;%s&quot;</Arguments>
    </Exec>
  </Actions>
</Task>
''' % (principal_block, PYTHON, RUNNER)


def try_create(xml_content, label):
    xml_path = os.path.join(tempfile.gettempdir(), "expert_db_fallback.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml_content)
    r = subprocess.run(
        ["schtasks", "/Create", "/TN", "ExpertDBFallback", "/XML", xml_path, "/F"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    os.remove(xml_path)
    if r.returncode == 0:
        print("[成功] %s 注册成功" % label)
        return True
    print("[失败] %s 注册失败(exit=%s): %s" % (label, r.returncode, (r.stderr or r.stdout).strip()))
    return False


if __name__ == "__main__":
    system_principal = (
        '    <Principal id="Author">\n'
        '      <UserId>S-1-5-18</UserId>\n'
        '      <RunLevel>LeastPrivilege</RunLevel>\n'
        '    </Principal>')
    user_principal = (
        '    <Principal id="Author">\n'
        '      <LogonType>InteractiveToken</LogonType>\n'
        '      <RunLevel>LeastPrivilege</RunLevel>\n'
        '    </Principal>')

    if try_create(build_xml(system_principal), "SYSTEM 模式(开机即跑,无需登录)"):
        sys.exit(0)
    print(">>> 无管理员权限，降级为当前用户模式...")
    if try_create(build_xml(user_principal), "当前用户模式(需登录电脑)"):
        sys.exit(0)
    print(">>> 注册失败。请以管理员身份打开终端后重试：")
    print('    schtasks /Create /TN ExpertDBFallback /XML "%%TEMP%%\\expert_db_fallback.xml" /F')
    sys.exit(1)
