@echo off
cd /d "c:\Users\marni\.claude\projects\groundhop"
"C:\Users\marni\AppData\Local\Python\bin\python.exe" download_national_transfer.py >> logs\nightly_update.log 2>&1
"C:\Users\marni\AppData\Local\Python\bin\python.exe" sofascore_tracker.py --export >> logs\nightly_update.log 2>&1

:: Push bijgewerkte data naar GitHub zodat Vercel herdeployt
git add data/dashboard_data.json >> logs\nightly_update.log 2>&1
git diff --cached --quiet || git commit -m "nightly data update %date% %time%" >> logs\nightly_update.log 2>&1
git push >> logs\nightly_update.log 2>&1
