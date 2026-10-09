@echo off
rem Prompt Box launcher for Windows. Keep this next to promptbox.py, promptbox.html and promptbox.png.
rem First run installs the three packages it needs; after that it just starts the app (no console window).
pyw -3 -c "import webview, keyring, pyperclip" 2>nul || (
  echo Installing Prompt Box dependencies, one time only...
  py -3 -m pip install --user pywebview keyring pyperclip || (echo Install failed. Is Python 3 installed from python.org? & pause & exit /b 1)
)
start "" pyw -3 "%~dp0promptbox.py"
