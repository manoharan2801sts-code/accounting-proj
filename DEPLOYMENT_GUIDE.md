# 🚀 Render & TiDB Cloud Deployment Guide
# கணக்கியல் மென்பொருளை Render & TiDB Cloud-ல் Deploy செய்யும் முழு வழிகாட்டி

---

## 📋 கண்ணோட்டம் (Overview)

இந்த பயன்பாடு (Accounting Software) **Render** (Python Web Service) மற்றும் **TiDB Cloud Serverless** (MySQL-compatible Cloud Database) இரண்டிலும் எளிதாக deploy செய்ய முழுமையாக தயார் செய்யப்பட்டுள்ளது.

- **Frontend + Backend**: Render-ல் ஒரே unified service-ஆக இயங்கும் (WhiteNoise மூலம் static files வேகமாக load ஆகும்).
- **Database**: TiDB Cloud Serverless (இலவச 5GB Storage, High Availability, Automatic SSL).

---

## 🌟 STEP 1: TiDB Cloud Serverless Database உருவாக்குதல்

1. [https://tidbcloud.com](https://tidbcloud.com) தளத்திற்கு செல்லவும்.
2. Sign Up / Log In செய்யவும் (Google அல்லது GitHub கொண்டு நுழையலாம்).
3. **"Create Cluster"** கிளிக் செய்யவும்.
4. **"Serverless"** (Free plan) என்பதை தேர்ந்தெடுக்கவும்:
   - **Cluster Name**: `accounting-cluster` (அல்லது நீங்கள் விரும்பும் பெயர்)
   - **Region**: உங்கள் இருப்பிடத்திற்கு அருகிலுள்ள region (எ.கா: `AWS - Singapore / ap-southeast-1` அல்லது `Mumbai`)
   - **Create** கிளிக் செய்யவும்.
5. கிளஸ்டர் உருவானதும், திரையில் **Connect** popup தோன்றும்:
   - **Root Password**-ஐ Generate செய்து குறித்து வைத்துக் கொள்ளவும் (Save your password!).
   - **Connection Type**: **General** அல்லது **Python** தேர்ந்தெடுக்கவும்.
   - அங்கிருந்து பின்வரும் விவரங்களை குறித்துக் கொள்ளவும்:
     - **Host**: (எ.கா: `gateway01.ap-southeast-1.prod.aws.tidbcloud.com`)
     - **Port**: `4000`
     - **User**: (எ.கா: `xxxxxx.root`)
     - **Password**: உங்கள் TiDB கடவுச்சொல்
     - **Database**: `test` அல்லது `accounting_dep_db`

---

## 🗄️ STEP 2: Database Schema & Seed Data ஏற்றுதல் (2 வழிகள் உள்ளன)

### வழி A: TiDB Cloud Web SQL Editor மூலம் (மிகவும் எளிதானது)
1. TiDB Cloud Dashboard-ல் இடதுபுற மெனுவில் **"SQL Editor"** அல்லது **"Chat2Query"** கிளிக் செய்யவும்.
2. இந்த ப்ராஜெக்ட்டில் உள்ள `backend/Schema_mysql.sql` கோப்பை திறந்து, அதில் உள்ள அனைத்து வரிகளையும் Copy செய்யவும்.
3. SQL Editor-ல் Paste செய்து **Run** பட்டனை கிளிக் செய்யவும்.
4. அனைத்து Tables (`CompanyMaster`, `Ledger_Groups`, `Ledgers`, `Tickets`, `Vouchers`, etc.) மற்றும் Initial Seed Data உருவாக்கப்பட்டுவிடும்.

### வழி B: Automated Python Script மூலம் (`init_tidb.py`)
உங்கள் கணினியில் இருந்தே TiDB-க்கு நேரடியாக schema ஏற்றலாம்:
```bash
python backend/init_tidb.py --url="mysql://<USER>:<PASSWORD>@<HOST>:4000/accounting_dep_db?ssl-mode=REQUIRED"
```
அல்லது `backend/.env`-ல் TiDB விவரங்களை கொடுத்துவிட்டு:
```bash
cd backend
python init_tidb.py
```
இதை இயக்கினால், script தானாகவே SSL உடன் TiDB-ல் connect ஆகி, அனைத்து tables மற்றும் seed data-வை ஏற்றி verification table-ஐ காண்பிக்கும்!

---

## 🐙 STEP 3: GitHub-ல் Code-ஐ Push செய்தல்

Render GitHub repository-லிருந்து deploy செய்யும் என்பதால், இந்த code-ஐ GitHub-ல் push செய்ய வேண்டும்:

1. VS Code / Terminal-ல் இந்த project folder-ல் வைத்து இயக்கவும்:
   ```bash
   git init
   git add .
   git commit -m "Deploy: Prepare Voyager ERP for Render and TiDB Cloud"
   ```
2. [https://github.com/new](https://github.com/new) சென்று புதிய repository ஒன்றை உருவாக்கவும் (எ.கா: `accounting-software`).
3. GitHub காட்டும் commands-ஐ இயக்கவும்:
   ```bash
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/accounting-software.git
   git push -u origin main
   ```

---

## 🌐 STEP 4: Render-ல் Deploy செய்தல்

1. [https://render.com](https://render.com) சென்று Log In செய்யவும்.
2. Dashboard-ல் **"New +"** பட்டனை கிளிக் செய்து **"Web Service"** என்பதைத் தேர்ந்தெடுக்கவும்.
3. உங்கள் GitHub repository-ஐ தேர்ந்தெடுக்கவும் (Connect GitHub account).
4. அமைப்புகளை பின்வருமாறு உள்ளிடவும்:
   - **Name**: `voyager-accounting` (அல்லது நீங்கள் விரும்பும் பெயர்)
   - **Region**: Singapore அல்லது Frankfurt (TiDB Cloud region-க்கு அருகாமையில்)
   - **Branch**: `main`
   - **Root Directory**: காலியாக விடவும் (Leave blank or `.`)
   - **Runtime**: `Python 3`
   - **Build Command**: `./build.sh`
   - **Start Command**: `gunicorn --chdir backend config.wsgi:application --bind 0.0.0.0:$PORT`
   - **Instance Type**: `Free`

5. **Environment Variables** (முக்கியமானது!):
   கீழே **"Add Environment Variable"** கிளிக் செய்து பின்வருவனவற்றை உள்ளிடவும்:

   | Key | Value | விளக்கம் |
   |---|---|---|
   | `PYTHON_VERSION` | `3.12.0` | Python version |
   | `DJANGO_DEBUG` | `False` | Production mode |
   | `DJANGO_SECRET_KEY` | *(Render-ல் Generate பட்டன் அழுத்தலாம் அல்லது ஒரு நீண்ட string)* | Django Security Key |
   | `DB_HOST` | `<உங்கள் TiDB Cloud Host>` | எ.கா: `gateway01.ap-southeast-1.prod.aws.tidbcloud.com` |
   | `DB_PORT` | `4000` | TiDB Port (4000) |
   | `DB_NAME` | `accounting_dep_db` | Database Name |
   | `DB_USER` | `<உங்கள் TiDB Cloud User>` | எ.கா: `xxxxxx.root` |
   | `DB_PASSWORD` | `<உங்கள் TiDB Password>` | TiDB Password |
   | `DB_SSL` | `True` | SSL கட்டாயம் |

   *(குறிப்பு: நீங்கள் `DATABASE_URL` பயன்படுத்த விரும்பினால், மேலே உள்ள `DB_*` மாறிகளுக்கு பதிலாக `DATABASE_URL=mysql://user:pass@host:4000/accounting_dep_db?sslMode=VERIFY_IDENTITY` என்று ஒரே variable-ஆகவும் கொடுக்கலாம்).*

6. **"Deploy Web Service"** கிளிக் செய்யவும்!

---

## ✅ STEP 5: Verification & பயன்பாட்டை சரிபார்த்தல்

1. Render build logs-ல்:
   - `Installing backend dependencies...`
   - `Collecting static files (WhiteNoise)...`
   - `Checking and applying database migrations...`
   - `Build Completed Successfully!`
   என்று வரும்.
2. Deploy முடிந்ததும், Render வழங்கும் URL-ஐ கிளிக் செய்யவும் (எ.கா: `https://voyager-accounting.onrender.com`).
3. முகப்புப் பக்கம் (`index.html`) மற்றும் Dashboard (`/dashboard` அல்லது `/dashboard.html`) உடனடியாக load ஆகும்.
4. Accounts, Vouchers, Company Master, Day Book போன்ற பக்கங்களில் உங்கள் TiDB Cloud database-ல் இருந்து நேரடி தரவுகள் வரும்!

---

## 🛠️ ஏதேனும் சிக்கல் ஏற்பட்டால் (Troubleshooting)

- **Database Connection Error**:
  - TiDB Cloud-ல் cluster Active-ல் உள்ளதா என்று சரிபார்க்கவும்.
  - `DB_PORT` கண்டிப்பாக `4000` ஆக இருக்க வேண்டும்.
  - `DB_SSL` என்பது `True` ஆக இருக்க வேண்டும்.
- **Static Files (CSS/Images) Not Loading**:
  - WhiteNoise தானாகவே `/assets/` URL-ல் இருந்து static files-ஐ serve செய்யும். `build.sh`-ல் `collectstatic` சரியாக முடிந்ததா என்பதை Render Logs-ல் கவனிக்கவும்.
