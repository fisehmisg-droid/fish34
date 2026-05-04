import os
from xhtml2pdf import pisa
import markdown

with open(r"euee_notes\biology\notes.md", "r", encoding="utf-8") as f:
    md_text = f.read()

# Add a CSS block to make it look beautiful and readable
css = """
body { font-family: Helvetica, Arial, sans-serif; font-size: 12pt; line-height: 1.6; }
h1 { color: #27AE60; text-align: center; border-bottom: 2px solid #2ECC71; padding-bottom: 10px; }
h2 { color: #2980B9; border-bottom: 1px solid #BDC3C7; margin-top: 30px; }
h3 { color: #8E44AD; margin-top: 20px; }
p { margin-bottom: 15px; }
li { margin-bottom: 8px; }
table { width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 15px; }
th, td { border: 1px solid #BDC3C7; padding: 10px; text-align: left; }
th { background-color: #ECF0F1; }
strong { color: #C0392B; }
blockquote { background-color: #FDEDEC; border-left: 5px solid #E74C3C; padding: 10px; margin: 15px 0; font-style: italic; }
"""

html_body = markdown.markdown(md_text, extensions=['tables', 'fenced_code'])

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

with open("Dr_Abebe_Biology_Ultimate_Guide.pdf", "w+b") as out:
    pisa.CreatePDF(full_html, dest=out)
    
print("PDF generated successfully as Dr_Abebe_Biology_Ultimate_Guide.pdf")
