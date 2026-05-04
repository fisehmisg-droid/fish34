import fitz
import os

def extract_pdf_start(pdf_path, output_path):
    doc = fitz.open(pdf_path)
    text = ""
    for i in range(min(20, len(doc))):
        page = doc.load_page(i)
        text += f"--- Page {i+1} ---\n"
        text += page.get_text() + "\n"
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)

base_dir = r"C:\Users\HP\Desktop\telegram bot\euee-bot\textbooks"
extract_pdf_start(os.path.join(base_dir, "G12-IT-STB-2023-web.pdf"), "it_toc.txt")
extract_pdf_start(os.path.join(base_dir, "G12-Agriculture-STB-2023-web.pdf"), "agri_toc.txt")
print("Done extracting TOCs.")
