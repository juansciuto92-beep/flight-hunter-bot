$Action = New-ScheduledTaskAction -Execute "python.exe" -Argument "`"C:\Users\juans\.gemini\antigravity\scratch\flight-hunter-bot\main.py`" --once" -WorkingDirectory "C:\Users\juans\.gemini\antigravity\scratch\flight-hunter-bot"
$Trigger = New-ScheduledTaskTrigger -Once -At "09:00" -RepetitionInterval (New-TimeSpan -Hours 12) -RepetitionDuration (New-TimeSpan -Days 365)
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "FlightHunterBot_BUE_MIA" -Action $Action -Trigger $Trigger -Settings $Settings -Force
Write-Output "Tarea programada 'FlightHunterBot_BUE_MIA' configurada para correr 2 veces por dia (cada 12 horas: 09:00 hs y 21:00 hs)."
