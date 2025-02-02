import pdfplumber


async def extract_data_from_pdf(pdf_path):
    """
    Extrae texto de un archivo PDF, incluyendo todas las páginas.
    """
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text
