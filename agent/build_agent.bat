@echo off
REM Сборка агента в один exe. Запускать на Windows в venv с установленными зависимостями.
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name 5agent agent.py
echo Готово: dist\5agent.exe
pause
