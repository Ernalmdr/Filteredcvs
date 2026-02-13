import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import fitz  # PyMuPDF
import re
import os
import json
import google.generativeai as genai
from fpdf import FPDF
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import PIL.Image  # Görsel işleme için

# ==========================================
# ⚙️ AYARLAR
# ==========================================

CREDENTIALS_FILE = 'credentials.json'
SHEET_NAME = 'İZMİR CV Form'
ALLOWED_CATEGORIES = ["Engineering", "Marketing", "HR", "Finance", "Sales", "IT", "Design"]

if "processing" not in st.session_state:
    st.session_state.processing = False

def set_processing(state):
    st.session_state.processing = state

try:
    TYPEFORM_ACCESS_TOKEN = st.secrets["general"]["typeform_token"]
    ADMIN_PASSWORD = st.secrets["general"]["admin_password"]
    GEMINI_API_KEY = st.secrets["general"]["gemini_api_key"]

    # Gemini Ayarları
    genai.configure(api_key=GEMINI_API_KEY)

except Exception as e:
    st.error(f"⚠️ HATA: secrets.toml ayarları eksik: {e}")
    st.stop()

# Sütun İsimleri
COLUMN_PDF_URL_BASE = "Global Talent Programı için CV'nizi ingilizce olacak şekilde PDF formatında buraya yükleyebilirsiniz."
COLUMN_TOKEN_ID = "Token"
COLUMN_NAME = "Ad ve Soyad"
COLUMN_DEPARTMENT = "Hangi alanda staja başvurmak istiyorsunuz ?"


def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return build('drive', 'v3', credentials=creds)


def get_or_create_drive_folder(service, folder_name, parent_id):
    # Klasör ismindeki gereksiz boşlukları temizle
    folder_name = folder_name.strip()

    # Mevcut klasörü aramak için daha sağlam bir sorgu
    query = (f"name = '{folder_name}' and "
             f"mimeType = 'application/vnd.google-apps.folder' and "
             f"trashed = false and "
             f"'{parent_id}' in parents")

    try:
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute().get('files', [])

        if results:
            # Eğer birden fazla bulunduysa, ilkini (en eskisini) döndür
            return results[0]['id']

        # Bulunamadıysa yeni oluştur
        meta = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_id]
        }
        folder = service.files().create(
            body=meta,
            fields='id',
            supportsAllDrives=True
        ).execute()

        return folder.get('id')

    except Exception as e:
        st.error(f"Klasör işlemi sırasında hata: {e}")
        return parent_id  # Hata olursa ana klasöre yükle


def upload_to_drive(service, file_bytes, file_name, categories):
    root_id = st.secrets["general"].get("root_folder_id")
    final_categories = categories if categories else ["Others"]

    for cat in final_categories:
        folder_id = get_or_create_drive_folder(service, cat, root_id)

        # --- YENİ: Dosya Var mı Kontrolü ---
        check_query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
        existing_files = service.files().list(q=check_query, supportsAllDrives=True).execute().get('files', [])

        if existing_files:
            # Dosya zaten varsa üstüne yazmak yerine atla veya güncelle
            continue

        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype='application/pdf')
        file_meta = {'name': file_name, 'parents': [folder_id]}
        service.files().create(body=file_meta, media_body=media, supportsAllDrives=True).execute()
    return True

# ==========================================
# 🧠 YAPAY ZEKA & PDF OLUŞTURUCU
# ==========================================

@st.cache_data(show_spinner=False)
def extract_data_with_gemini(text_content):
    """Dağınık CV metnini standart JSON formatına çevirir."""

    # 'flash' modeli en hızlısıdır.
    model = genai.GenerativeModel('gemini-3-flash-preview')

    # ALLOWED_CATEGORIES ve text_content değişkenlerinin tanımlı olduğunu varsayıyorum.

    prompt = f"""
        Act as a professional HR expert and Resume Writer. 
        Your goal is to extract data from the provided CV and ENHANCE it to make the candidate stand out.

        STRICT RULES FOR ENHANCEMENT:
        1. PROFESSIONAL TONE: Use strong action verbs (e.g., "Spearheaded", "Optimized", "Engineered").
        2. QUANTIFIABLE IMPACT: Where possible, transform descriptions into achievement-based statements using numerical data (percentages, time saved, budget managed). If specific numbers aren't present, use placeholders or professional phrasing that implies scale.
        3. SUMMARY: Rewrite the 'summary' to be a powerful elevator pitch.
        4. EXPERIENCE: Rewrite job descriptions to focus on results rather than just duties.

        Pick one or more categories for 'suggested_categories' ONLY from this list: {ALLOWED_CATEGORIES}.
        Return ONLY JSON. No markdown formatting. If missing, leave empty. 

        JSON Schema:
        {{
            "name": "Full Name",
            "suggested_categories": ["Category from the list"],
            "title": "Professional Title",
            "location": "City",
            "summary": "Enhanced professional summary with a focus on value proposition",
            "education": [{{ "degree": "", "school": "", "year": "" }}],
            "experience": [{{ 
                "role": "", 
                "company": "", 
                "description": "Enhanced description with numerical achievements and action verbs" 
            }}],
            "skills": {{ "tech": "List of technical skills" }},
            "spoken_languages": "List"
        }}

        CV TEXT:
        {text_content}
        """

    try:
        response = model.generate_content(prompt)
        json_str = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(json_str)
    except Exception as e:
        return None


class PDF(FPDF):
    def __init__(self, font_family='Arial'):
        super().__init__()
        self.font_family = font_family

    def header(self):
        pass

    def section_title(self, label):
        # 'B' (Bold) için font ailesi desteği gerekir.
        # Eğer özel font (DejaVu) kullanıyorsan ve Bold dosyasını yüklemediysen
        # standart Arial'a düşebilir veya hata verebilir.
        # Güvenlik için burada font_family değişkenini kullanıyoruz.
        self.set_font(self.font_family, 'B', 12)
        self.set_text_color(0, 51, 102)
        self.cell(0, 10, label, 0, 1, 'L')
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(2)

    def section_body(self, text):
        self.set_font(self.font_family, '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 5, text)
        self.ln()


def create_standardized_pdf(json_data):
    """JSON verisinden PDF üretir (Özet ve Sertifikalar Eklendi)."""

    # 1. Font Kontrolü
    font_path = "DejaVuSans.ttf"
    if not os.path.exists(font_path):
        font_path = "Arial.ttf"

    has_custom_font = os.path.exists(font_path)

    # 2. PDF Başlatma
    if has_custom_font:
        pdf = PDF(font_family='TrFont')
        # Normal, Bold, Italic, BoldItalic hepsi için aynı fontu tanımlıyoruz (Hata almamak için)
        pdf.add_font('TrFont', '', font_path, uni=True)
        pdf.add_font('TrFont', 'B', font_path, uni=True)
        pdf.add_font('TrFont', 'I', font_path, uni=True)
        pdf.add_font('TrFont', 'BI', font_path, uni=True)
    else:
        st.warning("⚠️ Türkçe font dosyası bulunamadı. Karakterler dönüştürülüyor.")
        json_data = sanitize_json_recursively(json_data)
        pdf = PDF(font_family='Arial')

    pdf.add_page()
    main_font = pdf.font_family

    # --- ÜST BİLGİ (HEADER) ---
    pdf.set_font(main_font, 'B', 16)
    pdf.cell(0, 10, json_data.get('name', ''), 0, 1, 'C')

    pdf.set_font(main_font, 'I', 12)
    pdf.cell(0, 8, json_data.get('title', ''), 0, 1, 'C')

    pdf.set_font(main_font, '', 10)
    pdf.cell(0, 6, json_data.get('location', ''), 0, 1, 'C')

    pdf.set_font(main_font, '', 9)
    pdf.cell(0, 6, json_data.get('contact', ''), 0, 1, 'C')
    pdf.ln(5)

    # --- 🆕 SUMMARY (HAKKIMDA) ---
    if json_data.get('summary'):
        pdf.ln(5)  # Biraz boşluk
        pdf.section_title('PROFESSIONAL SUMMARY')
        pdf.section_body(json_data['summary'])

    # --- EDUCATION ---
    if json_data.get('education'):
        pdf.section_title('EDUCATION')
        for edu in json_data['education']:
            pdf.set_font(main_font, 'B', 10)
            pdf.cell(0, 5, f"{edu['degree']}", 0, 1)
            pdf.set_font(main_font, '', 10)
            pdf.cell(0, 5, f"{edu['school']} | {edu['year']}", 0, 1)
            pdf.ln(2)

    # --- EXPERIENCE ---
    if json_data.get('experience'):
        pdf.section_title('EXPERIENCE')
        for exp in json_data['experience']:
            pdf.set_font(main_font, 'B', 10)
            pdf.write(5, f"{exp['role']} | ")
            pdf.set_font(main_font, 'I', 10)
            pdf.write(5, f"{exp['company']}")
            pdf.ln(6)
            pdf.set_font(main_font, '', 9)
            pdf.multi_cell(0, 5, f"- {exp['description']}")
            pdf.ln(3)

    # --- PROJECTS ---
    if json_data.get('projects'):
        pdf.section_title('PROJECTS')
        for proj in json_data['projects']:
            pdf.set_font(main_font, 'B', 10)
            pdf.write(5, f"{proj['name']}")
            if proj.get('tech'):
                pdf.set_font(main_font, 'I', 9)
                pdf.write(5, f" ({proj['tech']})")
            pdf.ln(6)
            pdf.set_font(main_font, '', 9)
            pdf.multi_cell(0, 5, f"{proj['details']}")
            pdf.ln(3)

    # --- 🆕 CERTIFICATES (SERTİFİKALAR) ---
    if json_data.get('certificates'):
        pdf.section_title('CERTIFICATES')
        for cert in json_data['certificates']:
            pdf.set_font(main_font, 'B', 10)
            pdf.write(5, f"• {cert.get('name', '')}")

            # Kurum ve Yıl bilgisi varsa parantez içinde ekleyelim
            extras = []
            if cert.get('issuer'): extras.append(cert['issuer'])
            if cert.get('year'): extras.append(cert['year'])

            if extras:
                pdf.set_font(main_font, '', 10)
                pdf.write(5, f" ({' - '.join(extras)})")

            pdf.ln(5)
        pdf.ln(2)

    # --- SKILLS ---
    if json_data.get('skills'):
        pdf.section_title('TECHNICAL SKILLS')
        skills = json_data['skills']
        pdf.set_font(main_font, '', 10)
        if isinstance(skills, dict):
            for k, v in skills.items():
                pdf.set_font(main_font, 'B', 10)
                pdf.write(5, f"{k.capitalize()}: ")
                pdf.set_font(main_font, '', 10)
                pdf.write(5, v)
                pdf.ln(5)
        else:
            pdf.multi_cell(0, 5, str(skills))
        pdf.ln(2)

    # --- LANGUAGES ---
    if json_data.get('spoken_languages'):
        pdf.section_title('LANGUAGES')
        pdf.section_body(json_data['spoken_languages'])

    # --- INTERESTS ---
    if json_data.get('interests'):
        pdf.section_title('INTERESTS')
        pdf.section_body(json_data['interests'])

    return pdf.output()
# ==========================================
# 🛠️ YARDIMCI FONKSİYONLAR
# ==========================================
def process_and_upload_single(name, row, service, cv_cols, silent=False):
    token = str(row.get(COLUMN_TOKEN_ID, "NoToken"))
    if token in get_processed_tokens():
        if not silent: st.warning(f"⚠️ {name} zaten işlenmiş.")
        return False

    pdf_url = ""
    for col in cv_cols:
        val = str(row.get(col, "")).strip()
        if "http" in val:
            pdf_url = val
            break

    if not pdf_url:
        if not silent: st.error(f"{name} için CV Linki bulunamadı.")
        return False

    # --- YENİLENEN KISIM: Bağlantı Yönetimi ---
    session = requests.Session()
    # 3 kez deneme yap, hatalar arasında bekleme süresini artır
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    headers = {"Authorization": f"Bearer {st.secrets['general']['typeform_token']}"}
    try:
        resp = requests.get(pdf_url, headers=headers, timeout=60)
        if resp.status_code == 200:
            doc = fitz.open(stream=resp.content, filetype="pdf")
            full_text = "".join([page.get_text() for page in doc])

            # --- GELİŞMİŞ VERİ ÇIKARMA MANTIĞI ---
            cv_json = None

            # Eğer metin varsa standart metin analizi yap
            if len(full_text.strip()) > 50:
                cv_json = extract_data_with_gemini(full_text)

            # Eğer metin yoksa veya AI başarısız olduysa GÖRSEL ANALİZİ (Vision) yap
            if not cv_json or len(full_text.strip()) <= 50:
                if not silent: st.info(f"🔍 {name} için metin okunamadı, görsel taraması (OCR) başlatılıyor...")

                # İlk sayfayı yüksek çözünürlüklü resme dönüştür
                page = doc[0]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # Çözünürlüğü 2 kat artır (Daha iyi okuma için)
                img = PIL.Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                #
                vision_model = genai.GenerativeModel('gemini-3-flash-preview')

                prompt = f"""
                    Analyze this CV image. Extract the information and format it as JSON.
                    Categories must be from: {ALLOWED_CATEGORIES}

                    JSON Schema:
                    {{
                        "name": "Full Name",
                        "suggested_categories": ["Category"],
                        "title": "Title",
                        "location": "City",
                        "summary": "Professional summary",
                        "education": [],
                        "experience": [],
                        "skills": {{ "tech": "" }},
                        "spoken_languages": ""
                    }}
                    """

                response = vision_model.generate_content([prompt, img])

                # JSON temizleme ve yükleme
                try:
                    json_str = response.text.replace("```json", "").replace("```", "").strip()
                    cv_json = json.loads(json_str)
                except:
                    cv_json = None

            # --- YÜKLEME ADIMI ---
            if cv_json:
                new_pdf_bytes = create_standardized_pdf(cv_json)
                cats = cv_json.get("suggested_categories", ["Others"])
                success = upload_to_drive(service, new_pdf_bytes, f"{name}_Standart.pdf", cats)
                if success:
                    save_token(token)
                    if not silent: st.success(f"✅ {name} (Vision desteğiyle) yüklendi!")
                    return True

    except Exception as e:
        if not silent: st.error(f"❌ {name} işlenirken hata: {e}")
    except requests.exceptions.ConnectionError:
        if not silent: st.error(
            f"🌐 Bağlantı hatası: İnternetinizi kontrol edin veya DNS kaynaklı bir sorun var ({name}).")
    except requests.exceptions.Timeout:
        if not silent: st.error(f"⏳ Zaman aşımı: Typeform sunucusu yanıt vermedi ({name}).")
    except Exception as e:
        if not silent: st.error(f"❌ Beklenmedik bir hata oluştu ({name}): {e}")

    return False
def sanitize_text(text):
    """Türkçe karakterleri İngilizce karşılıklarına çevirir (Font yoksa kullanılır)."""
    if not isinstance(text, str):
        return str(text)

    replacements = {
        'Ş': 'S', 'ş': 's',
        'Ğ': 'G', 'ğ': 'g',
        'İ': 'I', 'ı': 'i',
        'Ö': 'O', 'ö': 'o',
        'Ü': 'U', 'ü': 'u',
        'Ç': 'C', 'ç': 'c'
    }
    for tr, eng in replacements.items():
        text = text.replace(tr, eng)
    return text.encode('latin-1', 'replace').decode('latin-1')


def sanitize_json_recursively(data):
    """JSON içindeki tüm metinleri temizler."""
    if isinstance(data, dict):
        return {k: sanitize_json_recursively(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_json_recursively(i) for i in data]
    elif isinstance(data, str):
        return sanitize_text(data)
    else:
        return data

@st.cache_data(ttl=600, show_spinner=False)
def load_data():
    # 3 Kez deneme hakkı veriyoruz
    max_retries = 3

    for attempt in range(max_retries):
        try:
            scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

            # Credential Yükleme
            if "gcp_service_account" in st.secrets:
                creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
            else:
                creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

            client = gspread.authorize(creds)

            # Dosyayı Açma
            spreadsheet = client.open(SHEET_NAME)
            sheet = spreadsheet.worksheet("İZMİR CV Form")

            # Veriyi Çekme
            data = sheet.get_all_values()

            if not data: return pd.DataFrame()

            # Başlıkları İşleme (Duplicate Fix)
            headers = data[0]
            rows = data[1:]
            seen = {}
            unique_headers = []
            for col in headers:
                if col in seen:
                    seen[col] += 1
                    unique_headers.append(f"{col}_{seen[col]}")
                else:
                    seen[col] = 0
                    unique_headers.append(col)

            # Başarılı olduysa DataFrame'i döndür ve döngüden çık
            return pd.DataFrame(rows, columns=unique_headers)

        except Exception as e:
            # Hata verirse (İnternet kesilirse)
            if attempt < max_retries - 1:  # Son deneme değilse
                time.sleep(2)  # 2 saniye bekle ve tekrar dene
                continue
            else:
                # Son denemede de hata verirse ekrana yaz
                st.error(f"Google Sheets Bağlantı Hatası (3 kez denendi): {e}")
                return pd.DataFrame()

def get_processed_tokens():
    if os.path.exists("processed_tokens.txt"):
        with open("processed_tokens.txt", "r") as f: return f.read().splitlines()
    return []


def save_token(token):
    with open("processed_tokens.txt", "a") as f: f.write(f"{token}\n")


# ==========================================
# 🖥️ ARAYÜZ
# ==========================================

st.set_page_config(page_title="CV Master & Standardizer", layout="wide")
st.title("🛡️ İzmir CV Form - Standardize Edici")
st.markdown("---")

df = load_data()

if not df.empty:
    st.sidebar.header("🔐 Yönetici")
    input_pass = st.sidebar.text_input("Şifre", type="password")
    is_admin = (input_pass == ADMIN_PASSWORD)

    if is_admin: st.sidebar.success("Admin Modu")

    dept_col = next((col for col in df.columns if col.startswith(COLUMN_DEPARTMENT)), None)
    name_col = next((col for col in df.columns if col.startswith(COLUMN_NAME)), None)
    all_cv_cols = [col for col in df.columns if col.startswith(COLUMN_PDF_URL_BASE)]

    if dept_col:
        depts = df[df[dept_col] != ""][dept_col].unique()
        sel_depts = st.sidebar.multiselect("Filtrele", depts, default=depts)
        filtered_df = df[df[dept_col].isin(sel_depts)]
    else:
        filtered_df = df

    st.sidebar.info(f"Aday: {len(filtered_df)}")

    # Tablo Gösterimi
    display_df = filtered_df.copy()
    if not is_admin:
        cols_hide = [c for c in display_df.columns if
                     c.startswith(COLUMN_TOKEN_ID) or c.startswith(COLUMN_PDF_URL_BASE)]
        display_df = display_df.drop(columns=cols_hide, errors='ignore')

    st.dataframe(display_df, use_container_width=True)

    # --- İŞLEM PANELİ ---
    st.markdown("---")
    st.subheader("📄 Standart Formatlı CV & Drive Entegrasyonu")

    c1, c2, c3 = st.columns([1, 1, 1])

    with c1:
        sel_name = st.selectbox("Aday Seç:", filtered_df[name_col].tolist()) if name_col else None

    # Drive servisini hazırlayalım
    drive_service = get_drive_service()

    with c2:
        st.write("**Bireysel İşlem**")
        # İşlem sürüyorsa butonu disabled yap
        btn_single = st.button(
            "Seçiliyi Drive'a Gönder",
            disabled=st.session_state.processing,
            on_click=set_processing,
            args=(True,)
        )

        if btn_single:
            try:
                row = filtered_df[filtered_df[name_col] == sel_name].iloc[0]
                process_and_upload_single(sel_name, row, drive_service, all_cv_cols)
            finally:
                # İşlem bittiğinde (hata alsa bile) butonu tekrar aç
                st.session_state.processing = False
                st.rerun()
    with c3:
        st.write("**Toplu İşlem**")
        if st.button(f"Filtreli {len(filtered_df)} Kişiyi Drive'a Gönder"):
            # Güncel işlenmiş token listesini al
            processed_tokens = get_processed_tokens()

            # Sadece henüz işlenmemiş olanları filtrele
            to_process_df = filtered_df[~filtered_df[COLUMN_TOKEN_ID].isin(processed_tokens)]

            if to_process_df.empty:
                st.info("Seçili listedeki tüm adaylar zaten daha önce gönderilmiş.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(to_process_df)

                for i, (idx, row) in enumerate(to_process_df.iterrows()):
                    c_name = row[name_col]
                    status_text.text(f"İşleniyor ({i + 1}/{total}): {c_name}")

                    process_and_upload_single(c_name, row, drive_service, all_cv_cols, silent=True)

                    progress_bar.progress((i + 1) / total)
                    time.sleep(1)  # Kota koruması için kısa mola

                st.success(f"✅ Yeni {total} aday Drive'a yüklendi!")
                status_text.empty()