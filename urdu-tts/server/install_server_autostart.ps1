# Starts the Urdu voice server (server/serve.py) at every logon, hidden, so BOL's
# piper TTS provider can always reach it at http://localhost:8030.
#
#   powershell -ExecutionPolicy Bypass -File server\install_server_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File server\install_server_autostart.ps1 -Remove
param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$ProjectDir = "~/urdu-tts",
    [int]$Port = 8030,
    [switch]$Remove
)

$TaskName = "UrduTTS-Server"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task $TaskName."
    exit
}

$command = "cd $ProjectDir && source piper1-gpl/.venv/bin/activate && exec python server/serve.py --voices export --port $Port >> server.log 2>&1"
# conhost --headless: no console window to close by accident (closing it would stop the server).
$action = New-ScheduledTaskAction -Execute "conhost.exe" -Argument "--headless wsl.exe -d $Distro -- bash -lc `"$command`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered $TaskName. The voice server starts at every logon on http://localhost:$Port."
Write-Host "Start it now:  Start-ScheduledTask -TaskName $TaskName"
