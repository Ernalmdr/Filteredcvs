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
import gc  # Bellek yönetimi (RAM) için

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
            # Fontun Bold (B) ve Italic (I) versiyonlarını tanıtıyoruz (Hata almamak için)
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
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 5, str(text))
        self.ln()


def extract_and_categorize_with_gemini(text_content):
    # Model ismini EN STABİL VERSİYON (gemini-3-flash-preview) olarak güncelledik
    model = genai.GenerativeModel('gemini-3-flash-preview')
    categories_str = ", ".join(ALLOWED_CATEGORIES)
    prompt = f"Act as an HR expert. Extract CV data into JSON. Categories: [{categories_str}]. CV: {text_content}"
    try:
        response = model.generate_content(prompt)
        json_str = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_str)
    except Exception as e:
        print(f"Gemini Hatası: {e}")
        return None


def create_standard_pdf_bytes(json_data):
    pdf = StandardPDF()
    pdf.add_page()
    c = json_data.get('candidate_data', {})
    f = pdf.font_family_name

    pdf.set_font(f, 'B', 16)
    pdf.cell(0, 10, str(c.get('name', 'Candidate')), 0, 1, 'C')
    pdf.set_font(f, 'I', 12)
    pdf.cell(0, 8, str(c.get('title', '')), 0, 1, 'C')
    pdf.ln(5)

    if c.get('summary'):
        pdf.section_title('PROFESSIONAL SUMMARY')
        pdf.section_body(c['summary'])

    if c.get('education'):
        pdf.section_title('EDUCATION')
        for edu in c.get('education', []):
            pdf.section_body(f"{edu.get('degree')} - {edu.get('school')} ({edu.get('year')})")

    if c.get('experience'):
        pdf.section_title('EXPERIENCE')
        for exp in c.get('experience', []):
            pdf.section_body(f"{exp.get('role')} at {exp.get('company')}\n{exp.get('description')}")

    return pdf.output()


def get_or_create_folder(folder_name, parent_id):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false and '{parent_id}' in parents"
    results = drive_service.files().list(q=query).execute().get('files', [])
    if results: return results[0]['id']
    meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    return drive_service.files().create(body=meta, fields='id').execute().get('id')


# ==========================================
# 🚀 CORE İŞLEME FONKSİYONU
# ==========================================

def process_cv(candidate_name, pdf_url):
    doc = None
    try:
        target_filename = f"{candidate_name}_Standard.pdf"
        print(f"İşlem kontrol ediliyor: {candidate_name}")

        headers = {"Authorization": f"Bearer {TYPEFORM_TOKEN}"}
        resp = requests.get(pdf_url, headers=headers)

        if resp.status_code == 200:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            full_text = "".join([p.get_text() for p in doc])
            doc.close()  # BELLEĞİ HEMEN BOŞALT

            analysis = extract_and_categorize_with_gemini(full_text)
            if analysis:
                new_pdf_bytes = create_standard_pdf_bytes(analysis)
                categories = analysis.get("suggested_categories", ["Others"])

                for cat in categories:
                    folder_id = get_or_create_folder(cat, ROOT_FOLDER_ID)

                    # Duplicate (Mükerrer) Kontrolü
                    check_query = f"name = '{target_filename}' and '{folder_id}' in parents and trashed = false"
                    existing = drive_service.files().list(q=check_query).execute().get('files', [])
                    if existing:
                        print(f"⚠️ Atlandı (Zaten var): {candidate_name}")
                        continue

                    media = MediaIoBaseUpload(io.BytesIO(new_pdf_bytes), mimetype='application/pdf')
                    file_meta = {'name': target_filename, 'parents': [folder_id]}
                    drive_service.files().create(body=file_meta, media_body=media).execute()

                print(f"✅ Başarılı: {candidate_name}")
                return True
        return False
    except Exception as e:
        if doc: doc.close()
        print(f"❌ Hata: {str(e)}")
        return False
    finally:
        gc.collect()  # RAM TEMİZLİĞİ


# ==========================================
# 🌐 ENDPOINTLER
# ==========================================

@app.route('/webhook', methods=['POST'])
def handle_typeform():
    payload = request.json
    answers = payload.get('form_response', {}).get('answers', [])
    candidate_name = "Aday";
    pdf_url = ""
    for ans in answers:
        if ans.get('type') == 'text' and candidate_name == "Aday": candidate_name = ans.get('text', 'Aday')
        if ans.get('type') == 'file_url': pdf_url = ans.get('file_url')
    if pdf_url: process_cv(candidate_name, pdf_url)
    return "OK", 200


# İŞTE EKSİK OLAN VE ŞİMDİ DOLDURULAN KISIM:
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
        for row in all_rows[1:]:  # Başlık satırını atla
            name = row[name_idx]
            pdf_url = None

            # Dinamik Sütun Tarama: Satırdaki her hücreye bak, linki bul
            for cell in row:
                cell_str = str(cell).strip()
                if cell_str.startswith("http") and ("typeform.com" in cell_str or "storage" in cell_str):
                    pdf_url = cell_str
                    break  # Linki bulduysan taramayı bitir

            if pdf_url:
                if process_cv(name, pdf_url):
                    process_count += 1

        return f"İşlem tamamlandı. {process_count} adet başvuru başarıyla işlendi.", 200
    except Exception as e:
        return f"Hata: {str(e)}", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)