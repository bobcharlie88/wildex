# Deploying WildEx to PythonAnywhere

## Prerequisites
- PythonAnywhere account — **Hacker plan ($5/month)** required for external database access
- Your `.env` file with all API keys
- A free PostgreSQL database from [neon.tech](https://neon.tech) (free tier, no card required)

---

## Step 1 — Get a free PostgreSQL database (Neon)

1. Go to **neon.tech** and sign up (free)
2. Create a new project → give it a name (e.g. "wildex")
3. Copy the **Connection string** — it looks like:
   ```
   postgresql://user:password@ep-something.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Set that as `DATABASE_URL` in your `.env` file

---

## Step 2 — Upload your project to PythonAnywhere

### Option A — Git (recommended)
1. Open a **Bash console** on PythonAnywhere (Dashboard → Consoles → Bash)
2. Clone your repo:
   ```bash
   git clone https://github.com/YOURUSER/wildex.git ~/wildex
   ```

### Option B — Manual upload
1. Zip the project: `zip -r wildex.zip . --exclude ".git/*" --exclude "__pycache__/*" --exclude "uploads/*"`
2. Go to PythonAnywhere **Files** tab
3. Upload the zip to `/home/YOURUSERNAME/`
4. In Bash console: `cd ~ && unzip wildex.zip -d wildex`

---

## Step 3 — Install dependencies

In the PythonAnywhere **Bash console**:

```bash
cd ~/wildex
pip3.10 install --user -r requirements_pythonanywhere.txt
```

> If you get OpenCV errors, it should be fine — `opencv-python-headless` is used
> which has no GUI dependencies.

---

## Step 4 — Create your .env file on the server

```bash
nano ~/wildex/.env
```

Paste your environment variables:
```
GEMINI_API_KEY=your_key_here
DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

---

## Step 5 — Create the uploads directory

```bash
mkdir -p ~/wildex/uploads
```

---

## Step 6 — Create the web app

1. Go to PythonAnywhere **Web** tab
2. Click **Add a new web app**
3. Click **Next** → Select **Manual configuration**
4. Select **Python 3.10**
5. Click **Next**

---

## Step 7 — Configure the WSGI file

1. In the Web tab, click on the WSGI configuration file link
   (it will be `/var/www/YOURUSERNAME_pythonanywhere_com_wsgi.py`)
2. **Delete everything** in that file
3. Paste the contents of `pythonanywhere_wsgi.py` from your project
4. **Replace `YOURUSERNAME`** with your actual PythonAnywhere username (appears twice)
5. Click **Save**

---

## Step 8 — Configure static file mappings

In the Web tab, scroll to **Static files** and add two entries:

| URL         | Directory                                    |
|-------------|----------------------------------------------|
| `/static/`  | `/home/YOURUSERNAME/wildex/app/static/`      |
| `/uploads/` | `/home/YOURUSERNAME/wildex/uploads/`         |

Click the tick/save button after each entry.

---

## Step 9 — Initialise the database

In the Bash console:
```bash
cd ~/wildex
python3.10 -c "
import app.models  # registers models
from app.database import create_tables, db_available
print('DB reachable:', db_available())
create_tables()
print('Tables created')
"
```

You should see `DB reachable: True` and `Tables created`.

---

## Step 10 — Reload and test

1. In the Web tab, click the green **Reload** button
2. Visit `https://YOURUSERNAME.pythonanywhere.com` — the capture page should load
3. Visit `https://YOURUSERNAME.pythonanywhere.com/wildex` — the collection page
4. Visit `https://YOURUSERNAME.pythonanywhere.com/health` — should return `{"status":"healthy","database":true}`

---

## Troubleshooting

**500 error on startup**
- Check the **Error log** in the Web tab
- Most common cause: wrong path in WSGI file, or a missing package

**Database not reachable**
- On Neon, make sure "Allow connections from all IP addresses" is enabled (it is by default)
- Check `DATABASE_URL` in `.env` has `?sslmode=require` at the end

**OpenCV import error**
- Make sure you installed `requirements_pythonanywhere.txt` (which uses `opencv-python-headless`)
- NOT `requirements.txt` (which uses `opencv-python` with GUI dependencies that fail on PythonAnywhere)

**Photos not saving**
- Check `~/wildex/uploads/` directory exists and is writable: `ls -la ~/wildex/uploads/`

**API keys not loading**
- The WSGI file loads `.env` via `load_dotenv` — make sure the file exists at `~/wildex/.env`
- You can also hardcode them directly in the WSGI file as `os.environ['KEY'] = 'value'` lines

---

## Keeping it updated

After pushing code changes to Git:
```bash
cd ~/wildex && git pull
```
Then hit **Reload** in the Web tab.
