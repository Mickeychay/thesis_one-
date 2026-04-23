import re

with open("../stitch_downloads/09_Interactive_Case_Analysis_Dashboard.html", "r") as f:
    html = f.read()

# Extract body content
body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL)
if body_match:
    content = body_match.group(1)
    
    # Simple HTML to JSX conversions
    content = content.replace('class=', 'className=')
    content = re.sub(r'style="[^"]*"', '', content) # Remove empty or simple string styles
    
    content = re.sub(r'<!--(.*?)-->', r'{/* \1 */}', content, flags=re.DOTALL)
    
    # Close self-closing tags
    content = re.sub(r'(<img[^>]*)>', r'\1 />', content)
    content = re.sub(r'(<input[^>]*)>', r'\1 />', content)
    content = re.sub(r'(<hr[^>]*)>', r'\1 />', content)
    content = re.sub(r'(<br[^>]*)>', r'\1 />', content)
    
    # Fix the duplicate closure if any
    content = content.replace('/> />', '/>')
    content = content.replace('/>/>', '/>')
    
    jsx = f"""import React from 'react';

export default function App() {{
  return (
    <div className="bg-background text-on-background min-h-screen">
      {{/* Navbar */}}
      {content}
    </div>
  );
}}
"""
    with open("src/App.jsx", "w") as out:
        out.write(jsx)
    print("Conversion complete!")
else:
    print("Body not found.")
