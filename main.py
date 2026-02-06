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
import gspread

app = Flask(__name__)

# ==========================================
# ⚙️ AYARLAR VE YETKİLENDİRME
# ==========================================

try:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    TYPEFORM_TOKEN = os.environ.get("TYPEFORM_TOKEN")
    gcp_info = json.loads(os.environ.get("GCP_SERVICE_ACCOUNT"))
    ROOT_FOLDER_ID = os.environ.get("ROOT_FOLDER_ID", "")

    genai.configure(api_key=GEMINI_API_KEY)

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(gcp_info, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)

except Exception as e:
    print(f"⚠️ Yapılandırma Hatası: {e}")

ALLOWED_CATEGORIES = ["Engineering", "Marketing", "HR", "Finance", "Sales", "IT", "Design"]
FONT_PATH = os.path.join(os.getcwd(), "DejaVuSans.ttf")


# ==========================================
# 🧠 PDF VE GEMINI SINIFLARI
# ==========================================

class StandardPDF(FPDF):
    def __init__(self):
        super().__init__()
        if os.path.exists(FONT_PATH):
            # Fontun tüm stillerini aynı dosyadan kaydediyoruz (Hata almamak için)
            self.add_font('DejaVu', '', FONT_PATH)
            self.add_font('DejaVu', 'B', FONT_PATH)
            self.add_font('DejaVu', 'I', FONT_PATH)  # İtalik hatasını çözer
            self.font_family_name = 'DejaVu'
        else:
            self.font_family_name = 'Arial'

    def section_title(self, label):
        self.set_font(self.font_family_name, 'B', 12)
        self.set_text_color(0, 51, 102)
        self.cell(0, 10, label, 0, 1, 'L')
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def section_body(self, text):
        self.set_font(self.font_family_name, '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 5, str(text))
        self.ln()


def extract_and_categorize_with_gemini(text_content):
    # Model ismini en stabil versiyon olan flash yapıyoruz
    model = genai.GenerativeModel('gemini-3-flash-preview')
    categories_str = ", ".join(ALLOWED_CATEGORIES)
    prompt = f"Act as an HR expert. Extract CV data into JSON. Suggest categories: {categories_str}. CV: {text_content}"

    try:
        response = model.generate_content(prompt)
        json_str = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_str)
    except:
        return None


def create_standard_pdf_bytes(json_data):
    pdf = StandardPDF()
    pdf.add_page()
    c = json_data.get('candidate_data', {})
    f = pdf.font_family_name

    pdf.set_font(f, 'B', 16)
    pdf.cell(0, 10, str(c.get('name', '')), 0, 1, 'C')
    pdf.set_font(f, 'I', 12)  # Artık hata vermeyecek
    pdf.cell(0, 8, str(c.get('title', '')), 0, 1, 'C')
    pdf.ln(5)

    if c.get('summary'):
        pdf.section_title('PROFESSIONAL SUMMARY')
        pdf.section_body(c['summary'])

    # ... Diğer bölümler (Education, Experience vb.)

    return pdf.output()  # fpdf2'de bytes döner


# ==========================================
# 🚀 İŞLEME VE ENDPOINTLER
# ==========================================

def process_cv(candidate_name, pdf_url):
    doc = None
    try:
        print(f"İşlem kontrol ediliyor: {candidate_name}")
        headers = {"Authorization": f"Bearer {TYPEFORM_TOKEN}"}
        resp = requests.get(pdf_url, headers=headers)

        if resp.status_code == 200:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            full_text = "".join([p.get_text() for p in doc])
            doc.close()  # Belleği hemen boşalt

            analysis = extract_and_categorize_with_gemini(full_text)
            if analysis:
                new_pdf_bytes = create_standard_pdf_bytes(analysis)
                # Drive yükleme işlemleri...
                print(f"✅ Başarılı: {candidate_name}")
                return True
    except Exception as e:
        if doc: doc.close()
        print(f"❌ Hata: {e}")
    return False


@app.route('/process_old_submissions', methods=['GET'])
def process_old_submissions():
    try:
        gc_sheet = gspread.authorize(creds)
        spreadsheet_name = "İZMİR CV Form"
        sheet = gc_sheet.open(spreadsheet_name).get_worksheet(0)
        all_rows = sheet.get_all_values()
        header = all_rows[0]
        try:
            name_idx = header.index("Ad ve Soyad")
        except:
            name_idx = 0

        process_count = 0
        for row in all_rows[1:]:
            name = row[name_idx];
            url = None
            for cell in row:
                if str(cell).startswith("http") and ("typeform.com" in str(cell) or "storage" in str(cell)):
                    url = str(cell);
                    break
            if url:
                if process_cv(name, url): process_count += 1

        return f"<h1>İşlem Tamamlandı</h1><p>{process_count} adet başvuru işlendi.</p>", 200
    except Exception as e:
        return f"<h1>Hata</h1><p>{str(e)}</p>", 500

# Webhook endpoint'ini de buraya ekleyin...

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))