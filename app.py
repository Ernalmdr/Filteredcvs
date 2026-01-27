import time

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

# ==========================================
# ⚙️ AYARLAR
# ==========================================

CREDENTIALS_FILE = 'credentials.json'
SHEET_NAME = 'İZMİR CV Form'

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


# ==========================================
# 🧠 YAPAY ZEKA & PDF OLUŞTURUCU
# ==========================================

@st.cache_data(show_spinner=False)
def extract_data_with_gemini(text_content):
    """Dağınık CV metnini standart JSON formatına çevirir."""

    # 'flash' modeli en hızlısıdır.
    model = genai.GenerativeModel('gemini-1.5-flash')

    # Prompt'u biraz kısalttık ki AI daha hızlı okusun
    prompt = f"""
    Act as an HR expert. Extract data from this CV into the JSON format below.
    Return ONLY JSON. No markdown formatting. If missing, leave empty.

    JSON Schema:
    {{
        "name": "Full Name",
        "title": "Title",
        "location": "City",
        "contact": "Email | Phone | Links",
        "education": [{{ "degree": "", "school": "", "year": "" }}],
        "experience": [{{ "role": "", "company": "", "description": "Brief summary" }}],
        "projects": [{{ "name": "", "tech": "", "details": "Brief summary" }}],
        "skills": {{ "tech": "List of skills" }},
        "spoken_languages": "List",
        "interests": "List"
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
    def header(self):
        pass  # Header istemiyoruz, manuel çizeceğiz

    def section_title(self, label):
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 51, 102)  # Koyu Mavi Ton
        self.cell(0, 10, label, 0, 1, 'L')
        self.line(10, self.get_y(), 200, self.get_y())  # Alt çizgi
        self.ln(2)

    def section_body(self, text):
        self.set_font('Arial', '', 10)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 5, text)
        self.ln()


def create_standardized_pdf(json_data):
    """JSON verisinden 'Büşra Alaka' formatında PDF üretir."""
    pdf = PDF()
    pdf.add_page()

    # --- ÜST BİLGİ (HEADER) ---
    pdf.set_font('Arial', 'B', 16)
    pdf.cell(0, 10, json_data.get('name', ''), 0, 1, 'C')

    pdf.set_font('Arial', 'I', 12)
    pdf.cell(0, 8, json_data.get('title', ''), 0, 1, 'C')

    pdf.set_font('Arial', '', 10)
    pdf.cell(0, 6, json_data.get('location', ''), 0, 1, 'C')

    # İletişim (Sansürlü ise sansürlü gelir)
    pdf.set_font('Arial', '', 9)
    pdf.cell(0, 6, json_data.get('contact', ''), 0, 1, 'C')
    pdf.ln(10)

    # --- EDUCATION ---
    if json_data.get('education'):
        pdf.section_title('EDUCATION')
        for edu in json_data['education']:
            pdf.set_font('Arial', 'B', 10)
            pdf.cell(0, 5, f"{edu['degree']}", 0, 1)
            pdf.set_font('Arial', '', 10)
            pdf.cell(0, 5, f"{edu['school']} | {edu['year']}", 0, 1)
            pdf.ln(2)

    # --- EXPERIENCE ---
    if json_data.get('experience'):
        pdf.section_title('EXPERIENCE')
        for exp in json_data['experience']:
            pdf.set_font('Arial', 'B', 10)
            pdf.write(5, f"{exp['role']} | ")
            pdf.set_font('Arial', 'I', 10)
            pdf.write(5, f"{exp['company']}")
            pdf.ln(6)
            pdf.set_font('Arial', '', 9)
            pdf.multi_cell(0, 5, f"- {exp['description']}")
            pdf.ln(3)

    # --- PROJECTS ---
    if json_data.get('projects'):
        pdf.section_title('PROJECTS')
        for proj in json_data['projects']:
            pdf.set_font('Arial', 'B', 10)
            pdf.write(5, f"{proj['name']}")
            if proj.get('tech'):
                pdf.set_font('Arial', 'I', 9)
                pdf.write(5, f" ({proj['tech']})")
            pdf.ln(6)
            pdf.set_font('Arial', '', 9)
            pdf.multi_cell(0, 5, f"{proj['details']}")
            pdf.ln(3)

    # --- SKILLS ---
    if json_data.get('skills'):
        pdf.section_title('TECHNICAL SKILLS')
        skills = json_data['skills']
        pdf.set_font('Arial', '', 10)
        if isinstance(skills, dict):
            for k, v in skills.items():
                pdf.set_font('Arial', 'B', 10)
                pdf.write(5, f"{k.capitalize()}: ")
                pdf.set_font('Arial', '', 10)
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

    return pdf.output(dest='S').encode('latin-1', 'replace')  # Byte olarak döndür


# ==========================================
# 🛠️ YARDIMCI FONKSİYONLAR
# ==========================================

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
    st.subheader("📄 Standart Formatlı CV Oluştur")

    c1, c2 = st.columns([1, 2])
    with c1:
        sel_name = st.selectbox("Aday Seç:", filtered_df[name_col].tolist()) if name_col else None

    with c2:
        if sel_name and st.button("Tek Tipe Çevir ve İndir"):
            row = filtered_df[filtered_df[name_col] == sel_name].iloc[0]
            token = str(row.get(COLUMN_TOKEN_ID, "NoToken"))

            pdf_url = ""
            for col in all_cv_cols:
                val = str(row.get(col, "")).strip()
                if "http" in val:
                    pdf_url = val
                    break

            if not pdf_url:
                st.error("CV Linki bulunamadı.")
            else:
                with st.spinner("1. PDF İndiriliyor..."):
                    headers = {"Authorization": f"Bearer {TYPEFORM_ACCESS_TOKEN}"}
                    resp = None
                    for attempt in range(3):  # 3 kere deneme hakkı veriyoruz
                        try:
                            # timeout=60 diyerek "hemen pes etme, 60 saniye bekle" diyoruz
                            resp = requests.get(pdf_url, headers=headers, timeout=60)

                            if resp.status_code == 200:
                                break  # Başarılı olduysa döngüden çık
                        except requests.exceptions.RequestException:
                            time.sleep(2)  # Hata olursa 2 saniye dinlenip tekrar dene

                    # Eğer 3 denemede de olmadıysa hata ver
                    if resp is None or resp.status_code != 200:
                        st.error("İnternet bağlantısı çok yavaş veya kesildi. 3 kez denendi ama PDF indirilemedi.")
                        st.stop()
                    if resp.status_code == 200:
                        # 1. Metni Çıkar
                        with st.spinner("2. Yapay Zeka CV'yi okuyor..."):
                            doc = fitz.open(stream=resp.content, filetype="pdf")
                            full_text = ""
                            for page in doc: full_text += page.get_text()

                            # 2. Gemini ile JSON'a çevir
                            cv_json = extract_data_with_gemini(full_text)

                            if cv_json:
                                # 3. Yeni PDF'i bas
                                with st.spinner("3. Standart Format Oluşturuluyor..."):
                                    new_pdf_bytes = create_standardized_pdf(cv_json)

                                    st.success("✅ Dönüştürme Başarılı!")
                                    st.download_button(
                                        label="📥 Standart CV'yi İndir",
                                        data=new_pdf_bytes,
                                        file_name=f"{sel_name}_Standart.pdf",
                                        mime="application/pdf"
                                    )
                    else:
                        st.error("PDF indirilemedi.")