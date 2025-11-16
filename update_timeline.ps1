# Update Timeline - Regenerate timeline data from op_return_data directory
# Run this after scanning new blocks to update the visualization

Write-Host "`n=== Bitcoin OP_RETURN Timeline Updater ===" -ForegroundColor Cyan
Write-Host "Regenerating timeline data from op_return_data directory...`n" -ForegroundColor Gray

# Activate virtual environment
.\env\Scripts\Activate.ps1

# Regenerate timeline data
python generate_timeline_data.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n=== Success! ===" -ForegroundColor Green
    Write-Host "Timeline data has been updated." -ForegroundColor Green
    Write-Host "`nNext steps:" -ForegroundColor Yellow
    Write-Host "  1. Refresh your browser if timeline is already open" -ForegroundColor White
    Write-Host "  2. Or open: op_return_timeline_visjs.html`n" -ForegroundColor White
} else {
    Write-Host "`n=== Error! ===" -ForegroundColor Red
    Write-Host "Failed to generate timeline data. Check the error messages above.`n" -ForegroundColor Red
}

