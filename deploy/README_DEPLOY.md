# Deployment for Hostinger VPS (root@srv1220852)

This document contains commands and notes for deploying `GPTIntermediary` to `/var/www/GPTIntermediary` on your VPS. Domain used in examples: `americanelitebiz.com`.

1) Upload repository and change to project dir:

```bash
cd /var/www
# git clone or upload repo into GPTIntermediary
cd /var/www/GPTIntermediary
```

2) Create virtualenv and install Python deps:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

3) Install Node deps if using Node services:

```bash
npm install
```

4) Create `.env` in `/var/www/GPTIntermediary` with required variables, including:
- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
- `USER_ACCESS_TOKEN` and `USER_REFRESH_TOKEN` (Gmail OAuth)
- `JWT_SECRET`
- `DATABASE_URL` (if using Postgres)

If Gmail OAuth tokens were created on your local machine, run `backend/python/get_gmail_token.py` locally and copy the tokens into the VPS `.env` because headless servers cannot complete the browser-based OAuth flow easily.

5) Install the provided systemd service (customized for `/var/www/GPTIntermediary`):

```bash
cp deploy/systemd/gptintermediary.service /etc/systemd/system/gptintermediary.service
# Edit if necessary, then:
systemctl daemon-reload
systemctl enable --now gptintermediary
journalctl -u gptintermediary -f
```

6) Install nginx site config and enable it (uses `americanelitebiz.com`):

```bash
cp deploy/nginx/gptintermediary.conf /etc/nginx/sites-available/gptintermediary
ln -s /etc/nginx/sites-available/gptintermediary /etc/nginx/sites-enabled/gptintermediary
nginx -t
systemctl reload nginx
```

7) Obtain TLS for `americanelitebiz.com` using Certbot:

```bash
apt update && apt install certbot python3-certbot-nginx -y
certbot --nginx -d americanelitebiz.com
```

8) Notes and troubleshooting
- Office automation (Word/Excel) is Windows-only; disable those endpoints on Linux VPS.
- WhatsApp Node service may require headless Chromium or additional system packages; check `logs/` for Playwright or puppeteer errors.
- To debug directly, run:

```bash
source venv/bin/activate
python app.py
# or run Uvicorn directly for FastAPI
uvicorn backend.python.main:app --host 0.0.0.0 --port 8000
```

- Ensure file ownership/permissions allow the service user to read/write DB and logs:

```bash
chown -R root:root /var/www/GPTIntermediary
chmod -R u+rw /var/www/GPTIntermediary
```

If you'd like, I can generate a small diagnostic script to run on the VPS to collect versions, open ports, and recent logs — should I create that now? 
