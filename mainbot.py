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
from fpdf import FPDF # fpdf2 yüklü olduğunda bu satır doğru çalışacaktır
import gspread
import gc
import time
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# ==========================================
# ⚙️ AYARLAR
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TYPEFORM_TOKEN = os.getenv("TYPEFORM_TOKEN")
ROOT_FOLDER_ID = os.getenv("ROOT_FOLDER_ID")
CREDENTIALS_PATH = "credentials.json"

try:
    genai.configure(api_key=GEMINI_API_KEY)
    creds = Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    drive_service = build('drive', 'v3', credentials=creds)
    gc_sheet_client = gspread.authorize(creds)
except Exception as e:
    print(f"⚠️ Başlatma Hatası: {e}")

ALLOWED_CATEGORIES = ["Engineering", "Marketing", "HR", "Finance", "Sales", "IT", "Design"]
FONT_PATH = "DejaVuSans.ttf"

# ==========================================
# 🧠 YARDIMCI SINIFLAR
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

def extract_and_categorize_with_gemini(text_content):
    # DÜZELTME: gemini-2.5-flash kullanıyoruz
    model = genai.GenerativeModel('gemini-2.5-flash')
    prompt = f"Act as an HR expert. Extract CV data into JSON. Categories: {ALLOWED_CATEGORIES}. CV: {text_content}"
    try:
        time.sleep(2)
        response = model.generate_content(prompt)
        res_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(res_text)
    except Exception as e:
        print(f"Gemini Hatası: {e}")
        return None

def get_or_create_folder(folder_name, parent_id):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false and '{parent_id}' in parents"
    results = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get('files', [])
    if results: return results[0]['id']
    meta = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    return drive_service.files().create(body=meta, fields='id', supportsAllDrives=True).execute().get('id')

# ==========================================
# 🚀 ANA İŞLEM
# ==========================================
def process_cv(candidate_name, pdf_url):
    try:
        print(f"🔍 İşleniyor: {candidate_name}")
        headers = {"Authorization": f"Bearer {TYPEFORM_TOKEN}"}
        resp = requests.get(pdf_url, headers=headers)

        if resp.status_code == 200:
            with fitz.open(stream=resp.content, filetype="pdf") as doc:
                full_text = "".join([page.get_text() for page in doc])

            analysis = extract_and_categorize_with_gemini(full_text)
            if analysis:
                pdf = StandardPDF()
                pdf.add_page()
                pdf.set_font(pdf.font_family_name, 'B', 16)
                # Yeni fpdf2 standardına göre ln=1 yerine bu parametreleri kullanıyoruz
                pdf.cell(0, 10, str(candidate_name), border=0, new_x="LMARGIN", new_y="NEXT", align='C')
                new_pdf_bytes = pdf.output()

                categories = analysis.get("suggested_categories", ["Others"])
                for cat in categories:
                    folder_id = get_or_create_folder(cat, ROOT_FOLDER_ID)
                    media = MediaIoBaseUpload(io.BytesIO(new_pdf_bytes), mimetype='application/pdf')
                    file_meta = {'name': f"{candidate_name}_Standard.pdf", 'parents': [folder_id]}

                    drive_service.files().create(
                        body=file_meta,
                        media_body=media,
                        supportsAllDrives=True
                    ).execute()
                print(f"✅ Başarılı: {candidate_name}")
                return True
        return False
    except Exception as e:
        print(f"❌ Hata ({candidate_name}): {str(e)}")
        return False
    finally:
        gc.collect()

# ==========================================
# 🌐 ENDPOINTLER
# ==========================================

@app.route('/process_old_submissions', methods=['GET'])
def process_old_submissions():
    try:
        sheet = gc_sheet_client.open("İZMİR CV Form").get_worksheet(0)
        all_rows = sheet.get_all_values()
        header = all_rows[0]
        try: name_idx = header.index("Ad ve Soyad")
        except: name_idx = 0

        process_count = 0
        for row in all_rows[1:]:
            name = row[name_idx]
            url = None
            for cell in row:
                if str(cell).startswith("http") and ("typeform.com" in str(cell) or "storage" in str(cell)):
                    url = str(cell)
                    break

            if url:
                if process_cv(name, url):
                    process_count += 1
                    time.sleep(5)

        return f"Tamamlandı: {process_count} adet işlendi.", 200
    except Exception as e:
        return f"Hata: {str(e)}", 500

if __name__ == "__main__":
    # debug=False yaparak Windows'taki watchdog (reloading) hatasını engelledik
    app.run(host='127.0.0.1', port=5000, debug=False)