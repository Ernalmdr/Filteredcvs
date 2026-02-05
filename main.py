import os
import json
import io
import requests
import fitz  # PyMuPDF
import google.generativeai as genai
from flask import Flask, request
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from fpdf import FPDF

app = Flask(__name__)

# ==========================================
# ⚙️ AYARLAR VE YETKİLENDİRME
# ==========================================

try:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    TYPEFORM_TOKEN = os.environ.get("TYPEFORM_TOKEN")
    # Render'da "GCP_SERVICE_ACCOUNT" adıyla kaydettiğiniz JSON metni
    gcp_info = json.loads(os.environ.get("GCP_SERVICE_ACCOUNT"))

    genai.configure(api_key=GEMINI_API_KEY)

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(gcp_info, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)

    # Drive Ana Arşiv Klasör ID'si (Bunu da Render'a ekleyebilirsiniz)
    ROOT_FOLDER_ID = os.environ.get("ROOT_FOLDER_ID", "")

except Exception as e:
    print(f"⚠️ Yapılandırma Hatası: {e}")

# İzin verilen ana kategoriler
ALLOWED_CATEGORIES = ["Engineering", "Marketing", "HR", "Finance", "Sales", "IT", "Design"]


# ==========================================
# 🧠 GEMINI & PDF FONKSİYONLARI (app.py'dan)
# ==========================================

def extract_and_categorize_with_gemini(text_content):
    """CV verisini çıkarır ve kategorileri belirler."""
    model = genai.GenerativeModel('gemini-1.5-flash')
    categories_str = ", ".join(ALLOWED_CATEGORIES)

    prompt = f"""
    Act as an HR expert. Extract data from this CV into JSON and suggest categories from [{categories_str}].
    Return ONLY JSON.
    JSON Schema:
    {{
        "candidate_data": {{
            "name": "Full Name", "title": "Title", "location": "City", "summary": "About me",
            "education": [{{ "degree": "", "school": "", "year": "" }}],
            "experience": [{{ "role": "", "company": "", "description": "" }}],
            "skills": {{ "tech": "List" }},
            "spoken_languages": "List"
        }},
        "suggested_categories": ["Category1"]
    }}
    CV TEXT:
    {text_content}
    """
    try:
        response = model.generate_content(prompt)
        json_str = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_str)
    except:
        return None


class StandardPDF(FPDF):
    def section_title(self, label):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 51, 102)
        self.cell(0, 10, label, 0, 1, 'L')
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def section_body(self, text):
        self.set_font('Arial', '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 5, str(text))
        self.ln()


def create_standard_pdf_bytes(json_data):
    """JSON verisinden PDF üretir (Latin-1 uyumlu)."""
    pdf = StandardPDF()
    pdf.add_page()
    c = json_data.get('candidate_data', {})

    # Header
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, c.get('name', ''), 0, 1, 'C')
    pdf.set_font('Arial', 'I', 12)
    pdf.cell(0, 8, c.get('title', ''), 0, 1, 'C')
    pdf.ln(5)

    if c.get('summary'):
        pdf.section_title('PROFESSIONAL SUMMARY')
        pdf.section_body(c['summary'])

    if c.get('education'):
        pdf.section_title('EDUCATION')
        for edu in c['education']:
            pdf.section_body(f"{edu.get('degree')} - {edu.get('school')} ({edu.get('year')})")

    if c.get('experience'):
        pdf.section_title('EXPERIENCE')
        for exp in c['experience']:
            pdf.section_body(f"{exp.get('role')} at {exp.get('company')}\n{exp.get('description')}")

    if c.get('skills'):
        pdf.section_title('SKILLS')
        pdf.section_body(str(c['skills']))

    return pdf.output(dest='S').encode('latin-1', 'replace')


# ==========================================
# 🛠️ YARDIMCI ARAÇLAR
# ==========================================

def get_or_create_folder(folder_name, parent_id):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false and '{parent_id}' in parents"
    results = drive_service.files().list(q=query).execute().get('files', [])
    if results:
        return results[0]['id']

    meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    return drive_service.files().create(body=meta, fields='id').execute().get('id')


# ==========================================
# 🚀 WEBHOOK VE İŞLEME
# ==========================================

@app.route('/webhook', methods=['POST'])
def handle_typeform():
    payload = request.json
    answers = payload.get('form_response', {}).get('answers', [])

    candidate_name = "Aday"
    pdf_url = ""

    for ans in answers:
        if ans.get('type') == 'text' or ans.get('type') == 'email':
            # İlk metin alanını isim olarak varsayalım veya form yapınıza göre özelleştirin
            if candidate_name == "Aday": candidate_name = ans.get('text', 'Aday')
        if ans.get('type') == 'file_url':
            pdf_url = ans.get('file_url')

    if pdf_url:
        try:
            # 1. Orijinal PDF'i indir
            headers = {"Authorization": f"Bearer {TYPEFORM_TOKEN}"}
            resp = requests.get(pdf_url, headers=headers)

            # 2. Metni Oku
            doc = fitz.open(stream=resp.content, filetype="pdf")
            full_text = "".join([p.get_text() for p in doc])

            # 3. Gemini Analizi (Veri + Kategori)
            analysis = extract_and_categorize_with_gemini(full_text)

            if analysis:
                # 4. Standart PDF Oluştur
                new_pdf_bytes = create_standard_pdf_bytes(analysis)

                # 5. Kategorilere Göre Drive'a Yükle
                categories = analysis.get("suggested_categories", ["Others"])
                for cat in categories:
                    folder_id = get_or_create_folder(cat, ROOT_FOLDER_ID)

                    media = MediaIoBaseUpload(io.BytesIO(new_pdf_bytes), mimetype='application/pdf')
                    file_meta = {'name': f"{candidate_name}_Standard.pdf", 'parents': [folder_id]}
                    drive_service.files().create(body=file_meta, media_body=media).execute()

                print(f"✅ Başarılı: {candidate_name} -> {categories}")
        except Exception as e:
            print(f"❌ Hata: {e}")

    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)