@echo off
cd /d "%~dp0"
echo Starting dashboard...
echo Open your browser at: http://localhost:8501
echo Press Ctrl+C here to stop the server.
echo.
python -m streamlit run app.py
pause
