@echo off
REM Builds PianoPlayer_EN.exe and PianoPlayer_ES.exe (they ask for admin rights on launch).
REM Genera PianoPlayer_EN.exe y PianoPlayer_ES.exe (piden permisos de administrador al abrirse).
REM Requires Python 3.9+ in PATH / Requiere Python 3.9+ en el PATH.
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --uac-admin --name PianoPlayer_EN src\piano_player_en.py
python -m PyInstaller --noconfirm --onefile --uac-admin --name PianoPlayer_ES src\piano_player_es.py
echo.
if not exist dist\midis mkdir dist\midis
echo Done / Listo: dist\PianoPlayer_EN.exe  dist\PianoPlayer_ES.exe  (put .mid files in dist\midis)
pause
