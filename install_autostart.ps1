$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$bat = "$dir\start_tray.bat"

$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
New-Item -Path $key -Force | Out-Null
Set-ItemProperty -Path $key -Name "WireGuardBot" -Value "`"$bat`""

Write-Host "OK. Autostart registered (HKCU Run). Tray + bot will start at logon."
Write-Host "To remove:  Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name WireGuardBot"
