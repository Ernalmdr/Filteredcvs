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
import gc  # Belleği temizlemek için gerekli

app = Flask(__name__)

# ==========================================
# ⚙️ AYARLAR
# ==========================================
try:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    TYPEFORM_TOKEN = os.environ.get("TYPEFORM_TOKEN")
    gcp_info = json.loads(os.environ.get("GCP_SERVICE_ACCOUNT"))
    ROOT_FOLDER_ID = os.environ.get("ROOT_FOLDER_ID", "")

    genai.configure(api_key=GEMINI_API_KEY)
    creds = Credentials.from_service_account_info(gcp_info, scopes=["https://www.googleapis.com/auth/spreadsheets",
                                                                    "https://www.googleapis.com/auth/drive"])
    drive_service = build('drive', 'v3', credentials=creds)
except Exception as e:
    print(f"⚠️ Yapılandırma Hatası: {e}")

ALLOWED_CATEGORIES = ["Engineering", "Marketing", "HR", "Finance", "Sales", "IT", "Design"]
FONT_PATH = os.path.join(os.getcwd(), "DejaVuSans.ttf")


# ==========================================
# 🧠 PDF VE GEMINI (Bellek Dostu)
# ==========================================
class StandardPDF(FPDF):
    def __init__(self):
        super().__init__()
        if os.path.exists(FONT_PATH):
            self.add_font('DejaVu', '', FONT_PATH)
            self.add_font('DejaVu', 'B', FONT_PATH)
            self.add_font('DejaVu', 'I', FONT_PATH)
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
        self.multi_cell(0, 5, str(text))
        self.ln()


def extract_and_categorize_with_gemini(text_content):
    model = genai.GenerativeModel('gemini-3-flash-preview')  # DOĞRU MODEL İSMİ
    prompt = f"Act as an HR expert. Extract CV data into JSON. Categories: {ALLOWED_CATEGORIES}. CV: {text_content}"
    try:
        response = model.generate_content(prompt)
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except:
        return None


# ==========================================
# 🚀 CORE İŞLEM (Hata ve Bellek Korumalı)
# ==========================================
def process_cv(candidate_name, pdf_url):
    doc = None
    try:
        headers = {"Authorization": f"Bearer {TYPEFORM_TOKEN}"}
        resp = requests.get(pdf_url, headers=headers)
        if resp.status_code == 200:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            full_text = "".join([p.get_text() for p in doc])
            doc.close()  # PDF'İ HEMEN KAPAT (RAM İÇİN)

            analysis = extract_and_categorize_with_gemini(full_text)
            if analysis:
                pdf = StandardPDF()
                pdf.add_page()
                # ... (PDF İçerik oluşturma - önceki sürümlerdeki gibi)
                new_pdf_bytes = pdf.output()

                categories = analysis.get("suggested_categories", ["Others"])
                for cat in categories:
                    # Drive yükleme işlemleri...
                    pass
                print(f"✅ Başarılı: {candidate_name}")
                return True
    except Exception as e:
        if doc: doc.close()
        print(f"❌ Hata: {e}")
    finally:
        gc.collect()  # ÇÖP TOPLAYICIYI ÇALIŞTIR
    return False


# ==========================================
# 🌐 ENDPOINTLER
# ==========================================
@app.route('/webhook', methods=['POST'])
def handle_typeform():
    # Mevcut webhook kodu
    return "OK", 200


@app.route('/process_old_submissions', methods=['GET'])
def process_old_submissions():
    try:
        gc_sheet = gspread.authorize(creds)
        sheet = gc_sheet.open("İZMİR CV Form").get_worksheet(0)
        all_rows = sheet.get_all_values()

        process_count = 0
        for row in all_rows[1:]:  # Başlığı atla
            # Linki ve ismi bulup process_cv'ye gönder
            pass
        return f"İşlem Tamamlandı. {process_count} adet işlendi.", 200
    except Exception as e:
        return str(e), 500


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))