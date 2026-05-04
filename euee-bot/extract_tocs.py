import fitz
import os

pdf_files = [
    r"C:\Users\HP\Desktop\telegram bot\euee-bot\textbooks\G12-English-STB-2023-web.pdf",
    r"C:\Users\HP\Desktop\telegram bot\euee-bot\textbooks\G12-Economics-STB-2023-web.pdf"
]

with open("toc_output.txt", "w", encoding="utf-8") as out_file:
    for pdf in pdf_files:
        out_file.write(f"--- TOC for {os.path.basename(pdf)} ---\n")
        if not os.path.exists(pdf):
            out_file.write("File not found.\n")
            continue
        try:
            doc = fitz.open(pdf)
            toc = doc.get_toc()
            if toc:
                for item in toc:
                    out_file.write(f"{item}\n")
            else:
                out_file.write("No embedded TOC, extracting text of first 15 pages...\n")
                for i in range(min(15, doc.page_count)):
                    page = doc.load_page(i)
                    out_file.write(page.get_text())
        except Exception as e:
            out_file.write(f"Error: {e}\n")
        out_file.write("\n\n")
