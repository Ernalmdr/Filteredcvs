import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import requests
import fitz  # PyMuPDF
import re
import os

# ==========================================
# ⚙️ AYARLAR
# ==========================================

CREDENTIALS_FILE = 'credentials.json'

# Google Sheet Dosya Adı
SHEET_NAME = 'İZMİR CV Form'

# 🔒 GÜVENLİK GÜNCELLEMESİ:
# Token artık kodun içinde değil, .streamlit/secrets.toml dosyasından okunuyor.
try:
    TYPEFORM_ACCESS_TOKEN = st.secrets["general"]["typeform_token"]
except FileNotFoundError:
    st.error("⚠️ HATA: .streamlit/secrets.toml dosyası bulunamadı! Token okunamıyor.")
    st.stop()
except KeyError:
    st.error("⚠️ HATA: secrets.toml dosyasında 'typeform_token' alanı eksik.")
    st.stop()

# Sütun İsimleri
COLUMN_PDF_URL_BASE = "Global Talent Programı için CV'nizi ingilizce olacak şekilde PDF formatında buraya yükleyebilirsiniz."
COLUMN_TOKEN_ID = "Token"
COLUMN_NAME = "Ad ve Soyad"
COLUMN_DEPARTMENT = "Hangi alanda staja başvurmak istiyorsunuz ?"


# ==========================================
# 🛠️ YARDIMCI FONKSİYONLAR
# ==========================================

# --- 1. Google Sheets Bağlantısı ----

@st.cache_data(ttl=600)
def load_data():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        # ÖNCE BULUTTAKİ SECRETS'A BAK, YOKSA YEREL DOSYAYA BAK
        if "gcp_service_account" in st.secrets:
            # Bulut Ortamı (Streamlit Cloud)
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        else:
            # Yerel Ortam (Bilgisayarın)
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

        client = gspread.authorize(creds)

        try:
            spreadsheet = client.open(SHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            st.error(f"❌ '{SHEET_NAME}' dosyası bulunamadı!")
            return pd.DataFrame()

        try:
            sheet = spreadsheet.worksheet("İZMİR CV Form")
        except gspread.exceptions.WorksheetNotFound:
            st.error("❌ 'İZMİR CV Form' sekmesi bulunamadı.")
            return pd.DataFrame()

        data = sheet.get_all_values()

        if not data:
            return pd.DataFrame()

        original_headers = data[0]
        rows = data[1:]

        # Sütun isimlerini düzeltme (Duplicate hatası için)
        seen_headers = {}
        unique_headers = []
        for col in original_headers:
            if col in seen_headers:
                seen_headers[col] += 1
                unique_headers.append(f"{col}_{seen_headers[col]}")
            else:
                seen_headers[col] = 0
                unique_headers.append(col)

        df = pd.DataFrame(rows, columns=unique_headers)
        return df

    except Exception as e:
        st.error(f"Veri Yükleme Hatası: {e}")
        return pd.DataFrame()

    except Exception as e:
        st.error(f"Veri Yükleme Hatası: {e}")
        return pd.DataFrame()


# --- 2. İşlenmiş Token Yönetimi ---
def get_processed_tokens():
    if os.path.exists("processed_tokens.txt"):
        with open("processed_tokens.txt", "r") as f:
            return f.read().splitlines()
    return []


def save_token(token):
    with open("processed_tokens.txt", "a") as f:
        f.write(f"{token}\n")


# --- 3. PDF İndirme ve Sansürleme Motoru ---
def sanitize_pdf(pdf_url):
    try:
        headers = {
            "Authorization": f"Bearer {TYPEFORM_ACCESS_TOKEN}",
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.get(pdf_url, headers=headers)

        if response.status_code != 200:
            st.error(f"İndirme hatası! Kod: {response.status_code}")
            return None

        pdf_data = response.content

        try:
            doc = fitz.open(stream=pdf_data, filetype="pdf")
        except:
            st.error("Dosya indirildi ama PDF değil.")
            return None

        email_pattern = r"[\w\.-]+@[\w\.-]+"
        phone_pattern = r"(\+90|0)?\s*[0-9]{3}\s*[0-9]{3}\s*[0-9]{2}\s*[0-9]{2}"

        redaction_count = 0

        for page in doc:
            text = page.get_text("text")
            sensitive_data = re.findall(email_pattern, text) + re.findall(phone_pattern, text)

            for item in sensitive_data:
                if isinstance(item, tuple): item = item[0]
                if not item: continue
                areas = page.search_for(item)
                for area in areas:
                    page.add_redact_annot(area, fill=(0, 0, 0))
                    redaction_count += 1
            page.apply_redactions()

        st.info(f"Toplam {redaction_count} adet hassas bilgi silindi.")
        return doc.tobytes()

    except Exception as e:
        st.error(f"PDF İşleme Hatası: {e}")
        return None


# ==========================================
# 🖥️ ARAYÜZ
# ==========================================

st.set_page_config(page_title="İzmir CV Form Havuzu", layout="wide")
st.title("🛡️ İzmir CV Form - Güvenli Havuz")
st.markdown("---")

st.sidebar.header("🎛️ Filtreleme Paneli")

df = load_data()

if not df.empty:

    dept_col = next((col for col in df.columns if col.startswith(COLUMN_DEPARTMENT)), None)
    name_col = next((col for col in df.columns if col.startswith(COLUMN_NAME)), None)
    all_cv_cols = [col for col in df.columns if col.startswith(COLUMN_PDF_URL_BASE)]

    if dept_col:
        dept_list = df[df[dept_col] != ""][dept_col].unique()
        selected_depts = st.sidebar.multiselect("Departman Seç", dept_list, default=dept_list)
        filtered_df = df[df[dept_col].isin(selected_depts)]
    else:
        st.sidebar.warning(f"Departman sütunu ({COLUMN_DEPARTMENT}) bulunamadı.")
        filtered_df = df

    st.sidebar.info(f"Listelenen Aday: {len(filtered_df)}")
    st.dataframe(filtered_df, use_container_width=True)

    st.subheader("⚙️ CV İşlemleri")

    col1, col2 = st.columns([1, 2])

    with col1:
        if name_col:
            candidate_options = filtered_df[name_col].tolist()
            selected_candidate_name = st.selectbox("Aday Seçiniz:", candidate_options)
        else:
            st.error("İsim sütunu bulunamadı.")
            selected_candidate_name = None

    with col2:
        if selected_candidate_name and st.button("Seçili Adayı İncele ve Sansürle"):

            row = filtered_df[filtered_df[name_col] == selected_candidate_name].iloc[0]
            token = str(row.get(COLUMN_TOKEN_ID, "NoToken"))

            pdf_url = ""
            for col in all_cv_cols:
                val = str(row.get(col, "")).strip()
                if val and "http" in val:
                    pdf_url = val
                    break

            processed_list = get_processed_tokens()

            if token in processed_list:
                st.warning(f"⚠️ Bu aday ({token}) daha önce işlenmiş.")

            if not pdf_url:
                st.error("❌ Bu kişi için hiçbir sütunda CV linki bulunamadı.")
            else:
                with st.spinner(f'PDF Bulundu, İşleniyor...'):
                    sanitized_bytes = sanitize_pdf(pdf_url)

                    if sanitized_bytes:
                        st.success("✅ İşlem Başarılı!")
                        st.download_button(
                            label="📥 Güvenli CV'yi İndir (PDF)",
                            data=sanitized_bytes,
                            file_name=f"{selected_candidate_name}_Cleaned.pdf",
                            mime="application/pdf"
                        )
                        if token not in processed_list:
                            save_token(token)
else:
    st.warning("Veri yüklenemedi. .streamlit/secrets.toml ve credentials.json dosyalarını kontrol et.")