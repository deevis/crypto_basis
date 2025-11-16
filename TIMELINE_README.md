# Bitcoin OP_RETURN Timeline - Vis.js Edition

## Overview

This is a modern, interactive timeline visualization of large OP_RETURN data found on the Bitcoin blockchain, built with Vis.js Timeline library.

## Features

✨ **Interactive Timeline**
- Zoom and pan through time with smooth animations
- Group items by file type (text, images, video, documents, etc.)
- Professional data visualization with Vis.js library

🎨 **Beautiful Dark Theme**
- Neon cyan/magenta/yellow color scheme
- Color-coded by file type
- Smooth animations and transitions

🔍 **Powerful Filtering**
- Filter by file type with one click
- Show/hide specific types
- Real-time statistics updates

📊 **Detailed Information**
- Click any item to see full details
- View text content, images, and metadata
- Transaction fees, miners, timestamps, and more

## Files

- **`op_return_timeline_visjs.html`** - Main timeline visualization (Vis.js powered)
- **`generate_timeline_data.py`** - Python script to scan and generate data
- **`bitcoin_large_op_returns/op_return_data/timeline_data.json`** - Generated data file (253 items currently)
- **`op_return_timeline.html`** - Original custom timeline (minimap version)

## Usage

### 1. Generate/Update Timeline Data

Whenever you scan new blocks with `op_return_scanner.py`, regenerate the timeline data:

```powershell
.\env\Scripts\Activate.ps1
python generate_timeline_data.py
```

This will:
- Scan all directories in `bitcoin_large_op_returns/op_return_data/`
- Read all `*_metadata.json` files
- Generate `bitcoin_large_op_returns/op_return_data/timeline_data.json` with all OP_RETURN data

### 2. View the Timeline

Simply open the HTML file in your browser:

```powershell
start op_return_timeline_visjs.html
```

Or drag and drop `op_return_timeline_visjs.html` into any modern browser.

### 3. Interact with the Timeline

**Navigation:**
- **Scroll** to zoom in/out
- **Drag** to pan left/right
- **Click** items to see details
- **"Fit All"** button to see entire timeline

**Filtering:**
- Click type chips to toggle filters
- **"Show All"** to enable all types
- **"Clear All"** to hide all types
- Filters update in real-time

**Item Details:**
- Click any timeline item to open modal
- View transaction details, fees, miners
- Preview text content or images
- See file paths for external access

## Data Flow

```
Bitcoin Blocks
    ↓
op_return_scanner.py (scan blocks)
    ↓
bitcoin_large_op_returns/op_return_data/ (metadata JSON files)
    ↓
generate_timeline_data.py (aggregate data)
    ↓
bitcoin_large_op_returns/op_return_data/timeline_data.json (single data file)
    ↓
op_return_timeline_visjs.html (visualization)
```

## Current Statistics

**Total Items:** 253 OP_RETURNs
**Date Range:** November 2024 - November 2025
**File Types:**
- Text: 145 items
- JSON: 67 items
- Binary: 17 items
- Images (JPG/PNG): 11 items
- Executables (EXE/ELF): 9 items
- Archives (ZIP/7z): 3 items
- Video (MP4): 1 item

## Automation

To keep the timeline up-to-date, you can create a simple update script:

**`update_timeline.ps1`:**
```powershell
# Activate environment
.\env\Scripts\Activate.ps1

# Scan for new blocks (example: continue from last scanned)
python op_return_scanner.py --continue

# Regenerate timeline data
python generate_timeline_data.py

# Done! Refresh browser to see updates
Write-Host "Timeline data updated! Refresh your browser." -ForegroundColor Green
```

Then simply run:
```powershell
.\update_timeline.ps1
```

## Vis.js Features Used

- **Timeline component** - Main visualization
- **DataSet** - Efficient data management
- **Groups** - File type grouping
- **Custom styling** - Dark theme integration
- **Events** - Click handlers for interactivity
- **Templates** - Custom item rendering

## Browser Compatibility

Works in all modern browsers:
- ✅ Chrome/Edge (Recommended)
- ✅ Firefox
- ✅ Safari
- ✅ Opera

## Performance

- Handles 250+ items smoothly
- Lazy loading of modal content
- Efficient filtering and updates
- Smooth zoom/pan animations

## Future Enhancements

Potential improvements:
- [ ] Add search functionality
- [ ] Export filtered data to CSV
- [ ] Time range picker
- [ ] Miner-based grouping option
- [ ] Size-based visual encoding
- [ ] Transaction network visualization
- [ ] Auto-refresh when new data available

## Troubleshooting

**"Error loading data"**
- Make sure `bitcoin_large_op_returns/op_return_data/timeline_data.json` exists
- Run `python generate_timeline_data.py`

**Images not showing**
- Check file paths in `bitcoin_large_op_returns/op_return_data/`
- Ensure browser can access local files
- Try using a local web server if needed

**Empty timeline**
- Check that filters aren't all disabled
- Click "Show All" button
- Verify data exists in `bitcoin_large_op_returns/op_return_data/timeline_data.json`

---

Built with ❤️ for Bitcoin OP_RETURN analysis

