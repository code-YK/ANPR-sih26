@echo off
REM Force the Node 24 LTS install onto PATH so Vite 8 gets util.styleText.
REM (winget put Node here; the shell default may still be an older Node.)
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0"
node -v
npm run dev
