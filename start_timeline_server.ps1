# Start local web server for Bitcoin OP_RETURN Timeline
# This serves the timeline on http://localhost:8000

Write-Host "`n=== Bitcoin OP_RETURN Timeline Server ===" -ForegroundColor Cyan
Write-Host "Starting local web server on http://localhost:8000`n" -ForegroundColor Gray

# Activate virtual environment
.\env\Scripts\Activate.ps1

Write-Host "Server is running!" -ForegroundColor Green
Write-Host "Open your browser to: " -NoNewline -ForegroundColor Yellow
Write-Host "http://localhost:8000/op_return_timeline_visjs.html`n" -ForegroundColor Cyan

Write-Host "Press Ctrl+C to stop the server`n" -ForegroundColor Gray

# Start Python's built-in HTTP server
python -m http.server 8000

