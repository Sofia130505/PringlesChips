@echo off
rem Stop every running llama-server on this laptop (frees port 8081). Double-click to run.
taskkill /IM llama-server.exe /F
echo.
echo Done. Now double-click start_ft_server.cmd to start the fine-tuned model.
pause
