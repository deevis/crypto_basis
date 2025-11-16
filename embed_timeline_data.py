#!/usr/bin/env python3
"""
Create a standalone HTML timeline with embedded data
No server needed - opens directly in browser
"""

import json

def create_standalone_timeline():
    """Create a single-file HTML with embedded JSON data"""
    
    # Read the timeline data from op_return_data directory
    with open('op_return_data/timeline_data.json', 'r') as f:
        timeline_data = json.load(f)
    
    # Read the HTML template
    with open('op_return_timeline_visjs.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    # Replace the fetch() call with embedded data
    fetch_code = """async function loadTimelineData() {
            try {
                const response = await fetch('op_return_data/timeline_data.json');
                if (!response.ok) {
                    throw new Error('Failed to load timeline data');
                }
                
                allData = await response.json();"""
    
    embedded_code = f"""async function loadTimelineData() {{
            try {{
                // Embedded data - no server needed!
                allData = {json.dumps(timeline_data, indent=2)};"""
    
    html_content = html_content.replace(fetch_code, embedded_code)
    
    # Write standalone version
    output_file = 'op_return_timeline_standalone.html'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n[SUCCESS] Created {output_file}")
    print(f"   Total items: {len(timeline_data)}")
    print(f"\nThis file can be opened directly in your browser without a server!")
    print(f"Just double-click: {output_file}\n")

if __name__ == '__main__':
    create_standalone_timeline()

