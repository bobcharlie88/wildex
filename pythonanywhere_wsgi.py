# PythonAnywhere WSGI configuration for WildEx
# Copy the contents of this file into your PythonAnywhere WSGI config file at:
#   /var/www/<yourusername>_pythonanywhere_com_wsgi.py
#
# Replace /home/YOURUSERNAME/wildex with your actual path throughout.

import sys
import os

# ── 1. Add project to Python path ─────────────────────────────────────────
project_home = '/home/YOURUSERNAME/wildex'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# ── 2. Set working directory so relative paths (app/static, uploads) work ──
os.chdir(project_home)

# ── 3. Load environment variables from .env file ───────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))

# ── 4. Create uploads directory if it doesn't exist ───────────────────────
os.makedirs(os.path.join(project_home, 'uploads'), exist_ok=True)

# ── 5. Import FastAPI app and wrap for WSGI ────────────────────────────────
from main import app
from a2wsgi import ASGIMiddleware

application = ASGIMiddleware(app)
