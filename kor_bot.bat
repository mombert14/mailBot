@echo off
REM MailBot - slanger brus och sparar utkast. Avregistrering AVSTANGD.
REM   --utkast  draftar svar      --sopa  slanger brus
REM   lagg till --avreg for att aven avregistrera (gar inte att angra)
cd /d "%~dp0"
.venv\Scripts\python.exe listen.py --utkast --sopa >> bot.out 2>&1
