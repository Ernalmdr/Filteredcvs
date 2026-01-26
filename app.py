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
SHEET_NAME = 'İZMİR CV Form'

# GÜVENLİK VE ŞİFRE AYARLARI
try:
    TYPEFORM_ACCESS_TOKEN = st.secrets["general"]["typeform_token"]
    ADMIN_PASSWORD = st.secrets["general"]["admin_password"]  # Şifreyi buradan okuyor
except FileNotFoundError:
    st.error("⚠️ HATA: .streamlit/secrets.toml dosyası bulunamadı!")
    st.stop()
except KeyError as e:
    st.error(f"⚠️ HATA: secrets.toml dosyasında eksik alan: {e}")
    st.stop()

# Sütun İsimleri
COLUMN_PDF_URL_BASE = "Global Talent Programı için CV'nizi ingilizce olacak şekilde PDF formatında buraya yükleyebilirsiniz."
COLUMN_TOKEN_ID = "Token"
COLUMN_NAME = "Ad ve Soyad"
COLUMN_DEPARTMENT = "Hangi alanda staja başvurmak istiyorsunuz ?"


# ==========================================
# 🛠️ YARDIMCI FONKSİYONLAR
# ==========================================

# --- 1. Google Sheets Bağlantısı ---
@st.cache_data(ttl=600)
def load_data():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

        # Streamlit Cloud veya Local ayrımı
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)

        client = gspread.authorize(creds)

        try:
            spreadsheet = client.open(SHEET_NAME)
            sheet = spreadsheet.worksheet("İZMİR CV Form")
        except Exception as e:
            st.error(f"❌ Dosya veya sekme bulunamadı: {e}")
            return pd.DataFrame()

        data = sheet.get_all_values()
        if not data: return pd.DataFrame()

        # Sütun isimlerini benzersiz yap
        original_headers = data[0]
        rows = data[1:]
        seen_headers = {}
        unique_headers = []
        for col in original_headers:
            if col in seen_headers:
                seen_headers[col] += 1
                unique_headers.append(f"{col}_{seen_headers[col]}")
            else:
                seen_headers[col] = 0
                unique_headers.append(col)

        return pd.DataFrame(rows, columns=unique_headers)

    except Exception as e:
        st.error(f"Veri Yükleme Hatası: {e}")
        return pd.DataFrame()


# --- 2. Token Yönetimi ---
def get_processed_tokens():
    if os.path.exists("processed_tokens.txt"):
        with open("processed_tokens.txt", "r") as f:
            return f.read().splitlines()
    return []


def save_token(token):
    with open("processed_tokens.txt", "a") as f:
        f.write(f"{token}\n")


# --- 3. PDF Motoru ---
def sanitize_pdf(pdf_url):
    try:
        headers = {"Authorization": f"Bearer {TYPEFORM_ACCESS_TOKEN}", "User-Agent": "Mozilla/5.0"}
        response = requests.get(pdf_url, headers=headers)
        if response.status_code != 200:
            st.error(f"İndirme hatası! Kod: {response.status_code}")
            return None

        pdf_data = response.content
        try:
            doc = fitz.open(stream=pdf_data, filetype="pdf")
        except:
            st.error("Dosya PDF değil.")
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

        st.info(f"Temizlendi: {redaction_count} veri.")
        return doc.tobytes()
    except Exception as e:
        st.error(f"Hata: {e}")
        return None


# ==========================================
# 🖥️ ARAYÜZ (GÜNCELLENDİ)
# ==========================================

st.set_page_config(page_title="İzmir CV Form Havuzu", layout="wide")
st.title("🛡️ İzmir CV Form - Güvenli Havuz")
st.markdown("---")

df = load_data()

if not df.empty:
    # --- 1. SOL MENÜ VE YÖNETİCİ KONTROLÜ ---
    st.sidebar.header("🔐 Yönetici Girişi")
    input_pass = st.sidebar.text_input("Şifre", type="password", placeholder="Admin şifresi...")

    # Şifre doğru mu kontrol et
    is_admin = (input_pass == ADMIN_PASSWORD)

    if is_admin:
        st.sidebar.success("✅ Yönetici Modu Aktif")
    else:
        st.sidebar.info("👀 Misafir Modu (Hassas veriler gizli)")

    st.sidebar.markdown("---")
    st.sidebar.header("🎛️ Filtreleme")

    # --- 2. VERİYİ HAZIRLA ---
    dept_col = next((col for col in df.columns if col.startswith(COLUMN_DEPARTMENT)), None)
    name_col = next((col for col in df.columns if col.startswith(COLUMN_NAME)), None)
    all_cv_cols = [col for col in df.columns if col.startswith(COLUMN_PDF_URL_BASE)]

    # Filtreleme
    if dept_col:
        dept_list = df[df[dept_col] != ""][dept_col].unique()
        selected_depts = st.sidebar.multiselect("Departman Seç", dept_list, default=dept_list)
        filtered_df = df[df[dept_col].isin(selected_depts)]
    else:
        filtered_df = df

    st.sidebar.info(f"Aday Sayısı: {len(filtered_df)}")

    # --- 3. TABLOYU GİZLE/GÖSTER MANTIĞI ---
    # Ekrana basılacak tabloyu kopyalıyoruz
    display_df = filtered_df.copy()

    if not is_admin:
        # Yönetici değilse, Token ve Link sütunlarını tablodan uçuruyoruz
        cols_to_hide = [col for col in display_df.columns if
                        col.startswith(COLUMN_TOKEN_ID) or col.startswith(COLUMN_PDF_URL_BASE)]
        display_df = display_df.drop(columns=cols_to_hide, errors='ignore')

    # Temizlenmiş tabloyu göster
    st.subheader("📋 Aday Listesi")
    st.dataframe(display_df, use_container_width=True)

    # --- 4. İŞLEM YAPMA (Herkes yapabilir ama linki göremez) ---
    st.markdown("---")
    st.subheader("⚙️ CV İndir")

    col1, col2 = st.columns([1, 2])

    with col1:
        if name_col:
            # İsim listesi her zaman görünür
            candidate_options = filtered_df[name_col].tolist()
            selected_candidate_name = st.selectbox("Aday Seçiniz:", candidate_options)
        else:
            selected_candidate_name = None

    with col2:
        if selected_candidate_name and st.button("Seçili Adayın CV'sini Hazırla"):
            # Burası önemli: İşlem yaparken gizlenmiş tabloyu (display_df) değil,
            # orijinal veriyi (filtered_df) kullanıyoruz.
            # Böylece kullanıcı linki görmese bile sistem arka planda linki bulup indirebiliyor.

            row = filtered_df[filtered_df[name_col] == selected_candidate_name].iloc[0]
            token = str(row.get(COLUMN_TOKEN_ID, "NoToken"))

            # Linki bul
            pdf_url = ""
            for col in all_cv_cols:
                val = str(row.get(col, "")).strip()
                if val and "http" in val:
                    pdf_url = val
                    break

            processed_list = get_processed_tokens()

            if token in processed_list:
                st.warning(f"⚠️ Bu aday daha önce işlenmiş.")

            if not pdf_url:
                st.error("❌ CV Bulunamadı.")
            else:
                with st.spinner('CV Hazırlanıyor...'):
                    sanitized_bytes = sanitize_pdf(pdf_url)

                    if sanitized_bytes:
                        st.success("Hazır!")
                        st.download_button(
                            label="📥 İndir (Güvenli PDF)",
                            data=sanitized_bytes,
                            file_name=f"{selected_candidate_name}_Cleaned.pdf",
                            mime="application/pdf"
                        )
                        if token not in processed_list:
                            save_token(token)
else:
    st.warning("Veri yüklenemedi. Ayarları kontrol edin.")