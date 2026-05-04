import os
from xhtml2pdf import pisa
import markdown

# Paths
md_path = r"C:\Users\HP\Desktop\telegram bot\euee-bot\euee_notes\chemistry\notes.md"
pdf_path = r"C:\Users\HP\Desktop\telegram bot\euee-bot\Dr_Abebe_Chemistry_Ultimate_Guide.pdf"

with open(md_path, "r", encoding="utf-8") as f:
    md_text = f.read()

# Add a CSS block for a "Premium Chemistry" feel
css = """
body { font-family: 'Helvetica', 'Arial', sans-serif; font-size: 12pt; line-height: 1.6; color: #333; }
h1 { color: #00695C; text-align: center; border-bottom: 3px solid #004D40; padding-bottom: 15px; text-transform: uppercase; }
h2 { color: #2E7D32; border-bottom: 2px solid #81C784; margin-top: 35px; padding-bottom: 5px; }
h3 { color: #1B5E20; margin-top: 25px; font-style: italic; }
p { margin-bottom: 15px; text-align: justify; }
li { margin-bottom: 10px; }
table { width: 100%; border-collapse: collapse; margin-top: 20px; margin-bottom: 20px; }
th, td { border: 1px solid #A5D6A7; padding: 12px; text-align: left; }
th { background-color: #E8F5E9; color: #1B5E20; font-weight: bold; }
strong { color: #D32F2F; } /* Highlight for traps and formulas */
hr { border: 0; border-top: 1px solid #CCC; margin: 40px 0; }
.must-know { background-color: #FFF9C4; padding: 10px; border-left: 5px solid #FBC02D; }
"""

# Convert markdown to HTML
html_body = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'codehilite'])

# Wrap in full HTML structure
full_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>{css}</style>
</head>
<body>
    {html_body}
</body>
</html>
"""

# Generate PDF
with open(pdf_path, "w+b") as out:
    pisa_status = pisa.CreatePDF(full_html, dest=out)
    
if not pisa_status.err:
    print(f"PDF generated successfully as {pdf_path}")
else:
    print(f"Error generating PDF: {pisa_status.err}")
