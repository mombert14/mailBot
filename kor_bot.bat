@echo off
REM MailBot. Lagg till flaggor pa sista raden nar du vill att den ska agera:
REM   --utkast            draftar svar        (ofarligt)
REM   --utkast --sopa     + slanger brus      (30 dagar i papperskorgen)
REM   --skarp             + avregistrerar     (gar inte att angra)
cd /d "%~dp0"
.venv\Scripts\python.exe listen.py >> bot.out 2>&1
