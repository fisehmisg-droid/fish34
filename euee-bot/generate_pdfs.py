import markdown
from xhtml2pdf import pisa
import os

def convert_md_to_pdf(md_file, pdf_file):
    with open(md_file, 'r', encoding='utf-8') as f:
        md_text = f.read()
    
    html = markdown.markdown(md_text, extensions=['extra', 'tables'])
    
    styled_html = f"""
    <html>
    <head>
    <style>
        @page {{
            size: A4 portrait;
            margin: 2cm;
            @frame footer_frame {{
                -pdf-frame-content: footer_content;
                left: 50pt; width: 512pt; top: 772pt; height: 20pt;
            }}
        }}
        body {{
            font-family: Helvetica, Arial, sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #333333;
        }}
        h1 {{
            color: #2c3e50;
            text-align: center;
            font-size: 22pt;
            margin-bottom: 20px;
            font-weight: bold;
        }}
        h2 {{
            color: #2980b9;
            border-bottom: 2px solid #3498db;
            padding-bottom: 5px;
            font-size: 16pt;
            margin-top: 25px;
        }}
        h3 {{
            color: #16a085;
            font-size: 13pt;
            margin-top: 15px;
        }}
        p {{
            margin-bottom: 12px;
            text-align: justify;
        }}
        ul, ol {{
            margin-bottom: 15px;
            padding-left: 20px;
        }}
        li {{
            margin-bottom: 6px;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 4px;
            border-radius: 4px;
            font-family: "Courier New", Courier, monospace;
            font-size: 10pt;
            color: #c0392b;
        }}
        pre {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #e9ecef;
            margin-bottom: 15px;
            font-family: "Courier New", Courier, monospace;
        }}
        pre code {{
            background-color: transparent;
            padding: 0;
            color: #2c3e50;
        }}
        hr {{
            border: none;
            border-top: 1px dashed #bdc3c7;
            margin: 20px 0;
        }}
        strong {{
            color: #2c3e50;
        }}
    </style>
    </head>
    <body>
        <div id="footer_content" style="text-align: center; font-size: 9pt; color: #7f8c8d;">
            Page <pdf:pagenumber> of <pdf:pagecount>
        </div>
        {html}
    </body>
    </html>
    """
    
    with open(pdf_file, "w+b") as result_file:
        pisa_status = pisa.CreatePDF(styled_html.encode('utf-8'), dest=result_file, encoding='utf-8')
        
    if pisa_status.err:
        print(f"Error creating {pdf_file}")
    else:
        print(f"Successfully created {pdf_file}")

base_dir = r"C:\Users\HP\Desktop\telegram bot\euee-bot"

it_md = os.path.join(base_dir, "euee_notes", "it", "notes.md")
it_pdf = os.path.join(base_dir, "Dr_Abebe_IT_Ultimate_Guide.pdf")

agri_md = os.path.join(base_dir, "euee_notes", "agriculture", "notes.md")
agri_pdf = os.path.join(base_dir, "Dr_Abebe_Agriculture_Ultimate_Guide.pdf")

convert_md_to_pdf(it_md, it_pdf)
convert_md_to_pdf(agri_md, agri_pdf)
