@echo off
cd /d "%~dp0"
echo Installation d'Albion Kill History...
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python n'est pas installe ou pas dans le PATH.
    echo Telechargez Python sur https://www.python.org/downloads/
    echo Cochez bien "Add Python to PATH" lors de l'installation.
    pause
    exit /b 1
)

echo Python detecte. Installation des dependances...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Erreur lors de l'installation des dependances.
    pause
    exit /b 1
)

echo.
echo Installation terminee ! Lancez lancer.bat pour demarrer.
pause
