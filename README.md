
🛡️ CV SafePool & Sanitizer
Bu proje, Typeform üzerinden toplanan aday başvurularını ve CV'leri tek bir havuzda toplar, filtreler ve KVKK (GDPR) uyumluluğu için kişisel iletişim bilgilerini (Telefon, E-posta) otomatik olarak sansürler.

Python ve Streamlit kullanılarak geliştirilmiştir; Google Sheets API ile entegre çalışır.

🌟 Özellikler
Google Sheets Entegrasyonu: Typeform'dan Google Sheets'e düşen verileri anlık olarak çeker.

Gelişmiş Filtreleme: Adayları departman, okul veya diğer kriterlere göre arayüzden filtreleyebilirsiniz.

Otomatik Sansür (Redaction): PDF üzerindeki telefon ve e-posta bilgilerini Regex algoritmalarıyla bulur.

Güvenli Temizleme: Sadece üzerini siyah bantla kapatmaz; PyMuPDF kullanarak metni katmanlardan tamamen siler (Seçilemez/Kopyalanamaz hale getirir).

Web Arayüzü: Kurulum gerektirmeyen, tarayıcı tabanlı kullanıcı dostu arayüz.

🛠️ Gereksinimler
Projenin çalışması için bilgisayarınızda Python 3.x yüklü olmalıdır.

Kullanılan kütüphaneler:

streamlit (Arayüz)

pandas (Veri İşleme)

gspread & oauth2client (Google API Bağlantısı)

pymupdf (fitz) (PDF Manipülasyonu)

🚀 Kurulum
Projeyi bilgisayarınıza klonlayın veya indirin:

Bash
git clone https://github.com/kullaniciadi/cv-safepool.git
cd cv-safepool
Gerekli kütüphaneleri yükleyin:

Bash
pip install streamlit pandas gspread oauth2client PyMuPDF requests
🔑 Google API Yapılandırması (Önemli!)
Projenin Google Sheets'e erişebilmesi için bir "Servis Hesabı" (Service Account) oluşturmanız gerekir.

Google Cloud Console'a gidin.

Yeni bir proje oluşturun.

"APIs & Services" > "Library" menüsünden şu iki API'yi etkinleştirin:

Google Sheets API

Google Drive API

"Credentials" sekmesine gidin, "Create Credentials" > "Service Account" seçeneğini seçin.

Hesap oluştuktan sonra, oluşturulan hesaba tıklayın ve "Keys" sekmesine gidin.

"Add Key" > "Create New Key" > "JSON" seçeneğini seçin.

İnen dosyanın adını credentials.json olarak değiştirin ve proje klasörünün içine atın.

credentials.json dosyasını not defteriyle açın, "client_email" kısmındaki mail adresini kopyalayın (Örn: bot@proje.iam.gserviceaccount.com).

Typeform verilerinin olduğu Google Sheet dosyanızı açın, "Paylaş" (Share) butonuna basın ve kopyaladığınız mail adresini "Editör" olarak ekleyin.

⚙️ Uygulama Ayarları
app.py dosyasını açın ve aşağıdaki alanları kendi projenize göre güncelleyin:

Python
# Google Sheet dosyanızın tam adı
SHEET_NAME = 'Typeform Cevaplari' 

# Excel'deki PDF linkinin olduğu sütun adı (Harfiyen aynı olmalı)
# Örn: "Lütfen CV'nizi yükleyiniz"
pdf_url_column = "CV Linki Sütun Adı" 
▶️ Çalıştırma
Terminal veya komut satırında proje klasöründeyken şu komutu yazın:

Bash
streamlit run app.py
Tarayıcınızda otomatik olarak http://localhost:8501 adresinde uygulama açılacaktır.

⚠️ Bilinen Sınırlar ve Uyarılar
PDF Formatı: Sadece metin tabanlı (Text-based) PDF'lerde %100 çalışır. Resim olarak taranmış (Scanned) CV'lerdeki metinleri tanımaz (OCR gerektirir).

Regex Hassasiyeti: Telefon numaraları ve e-postalar standart formatlarda ise yakalanır. Çok karmaşık veya hatalı yazılmış formatlar gözden kaçabilir.

API Kotası: Google Sheets API'nin günlük okuma kotası vardır, çok sık yenileme yapılırsa kısa süreli engel yiyebilirsiniz. (Uygulama içinde 10 dk önbellek (cache) mevcuttur).

📝 Yapılacaklar Listesi (Roadmap)
[ ] OCR Desteği eklenmesi (Taranmış PDF'ler için).

[ ] LLM (OpenAI/Ollama) ile yetenek bazlı anlamsal arama.

[ ] Toplu indirme (Zip olarak) özelliği.

Geliştirici: Eren Alemdar Lisans: MIT
