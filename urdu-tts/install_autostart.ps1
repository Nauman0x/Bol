# Makes training restart by itself after a power cut or reboot.
#
# Registers a Windows scheduled task that, when you log on, runs
# `scripts/train.sh auto` inside WSL. That continues from the newest intact
# checkpoint, or starts fresh if there is none. Output goes to runs/train.log.
#
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove   # when training is finished
#
# For a fully unattended restart the PC must also power on and log on by itself:
# see "Surviving a power cut" in README.md.
param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$ProjectDir = "~/urdu-tts",
    [switch]$Remove
)

$TaskName = "UrduTTS-Train"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName."
    exit
}

$command = "cd $ProjectDir && mkdir -p runs && scripts/train.sh auto >> runs/train.log 2>&1"
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro -- bash -lc `"$command`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Default task settings would kill the run after 3 days and refuse to start on battery.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered scheduled task $TaskName. Training will resume at every logon."
Write-Host "Start it now without logging off:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "Follow progress:                   wsl -d $Distro -- tail -f $ProjectDir/runs/train.log"
