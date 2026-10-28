@echo off
rem GroundHop starten op Windows: dubbelklik dit bestand.
rem
rem Hetzelfde als GroundHop.command op de Mac. Het werk zelf staat in
rem opstarten.py; dit bestand zoekt alleen Python. Laat het venster open
rem zolang je GroundHop gebruikt; sluit het om te stoppen.

cd /d "%~dp0"

set PY=
where py >nul 2>nul && set PY=py
if not defined PY (python --version >nul 2>nul && set PY=python)
if not defined PY (
  echo.
  echo   Python ontbreekt. Installeer het via python.org en vink daarbij
  echo   "Add python.exe to PATH" aan. Start GroundHop daarna opnieuw.
  echo.
  pause
  exit /b 1
)

rem Op een regel: cmd leest dit bestand terwijl het draait, en bijwerken kan
rem het intussen veranderen. Gaat er iets mis, dan blijft de melding staan.
(%PY% opstarten.py %* || pause) & exit /b
