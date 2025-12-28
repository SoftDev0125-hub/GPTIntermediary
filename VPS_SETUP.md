# VPS Setup Guide

This guide explains how to run the application both locally and on your VPS with domain `americanelitebiz.com`.

## 🏠 Local Development

Simply run:
```bash
python app.py
```

The app will:
- Start all servers on `localhost`
- Open `http://localhost:5000/` in your browser automatically
- Use `localhost:8000` for backend API (internal communication)

**No configuration needed for local development!**

## 🌐 VPS Deployment

### Step 1: Upload Project to VPS

Upload your project to your VPS (72.62.162.44) using:
- FTP/SFTP through hPanel
- Git clone
- Or any file transfer method

### Step 2: Install Dependencies

On your VPS, install required packages:
```bash
pip install -r requirements.txt
npm install  # If using Node.js servers
```

### Step 3: Set Environment Variables

On your VPS, set these environment variables before running:

```bash
export VPS=true
export DOMAIN=americanelitebiz.com
export USE_HTTPS=true  # Set to false if not using SSL
```

Or create a `.env` file (if using python-dotenv):
```env
VPS=true
DOMAIN=americanelitebiz.com
USE_HTTPS=true
OPENAI_API_KEY=your_key_here
```

### Step 4: Configure Reverse Proxy (Nginx)

Since you're using hPanel on Hostinger, you can configure Nginx through hPanel or directly.

**Option A: Through hPanel**
1. Go to hPanel → Websites → americanelitebiz.com
2. Configure Nginx/Reverse Proxy settings
3. Set up proxy rules (see below)

**Option B: Direct Nginx Configuration**

Create/edit Nginx config file (usually in `/etc/nginx/sites-available/` or through hPanel):

```nginx
server {
    listen 80;
    server_name americanelitebiz.com www.americanelitebiz.com;

    # Main application (Chat Server on port 5000)
    location / {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API (FastAPI on port 8000)
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**For HTTPS (SSL):**
```nginx
server {
    listen 443 ssl http2;
    server_name americanelitebiz.com www.americanelitebiz.com;

    ssl_certificate /path/to/ssl/certificate.crt;
    ssl_certificate_key /path/to/ssl/private.key;

    # Same location blocks as above
    location / {
        proxy_pass http://localhost:5000;
        # ... proxy settings
    }

    location /api {
        proxy_pass http://localhost:8000;
        # ... proxy settings
    }
}
```

After configuring, reload Nginx:
```bash
sudo nginx -t  # Test configuration
sudo systemctl reload nginx
```

### Step 5: Run Application on VPS

```bash
# Set environment variables
export VPS=true
export DOMAIN=americanelitebiz.com
export USE_HTTPS=true

# Run the application
python app.py
```

**Or use PM2 to keep it running:**
```bash
# Install PM2
npm install -g pm2

# Start with PM2
pm2 start app.py --name gpt-intermediary --interpreter python3 --env VPS=true,DOMAIN=americanelitebiz.com,USE_HTTPS=true

# Save and enable startup
pm2 save
pm2 startup
```

### Step 6: Access from Your Local Browser

Once everything is set up, you can access the application from your local machine at:
- **With SSL:** `https://americanelitebiz.com`
- **Without SSL:** `http://americanelitebiz.com`

The application will be accessible from anywhere, not just the VPS!

## 📋 Environment Variables Summary

| Variable | Local | VPS | Description |
|----------|-------|-----|------------|
| `VPS` | Not needed | `true` | Enables server mode |
| `DOMAIN` | Not needed | `americanelitebiz.com` | Your domain name |
| `USE_HTTPS` | Not needed | `true` or `false` | Use HTTPS protocol |

## 🔧 Important Notes

1. **Ports Used:**
   - `5000`: Chat Server (Flask)
   - `8000`: Backend API (FastAPI)
   - `8001`: Django Server (if used)
   - `3000-3002`: Node.js servers (WhatsApp, Telegram, Slack)

2. **Backend URL:** The backend URL in `chat_server.py` stays as `http://localhost:8000` because the chat server and backend run on the same VPS and communicate internally.

3. **Firewall:** Make sure ports 5000, 8000, etc. are accessible internally (localhost) on your VPS. The reverse proxy handles external access.

4. **SSL Certificate:** Get a free SSL certificate from Let's Encrypt through hPanel or use Hostinger's SSL feature.

5. **Process Management:** Use PM2, systemd, or supervisor to keep the app running after you disconnect from SSH.

## 🐛 Troubleshooting

**Can't access domain:**
- Check DNS is pointing to 72.62.162.44
- Verify Nginx is running: `sudo systemctl status nginx`
- Check Nginx logs: `sudo tail -f /var/log/nginx/error.log`

**Backend not responding:**
- Check if backend is running: `netstat -tulpn | grep 8000`
- Check logs: `cat logs/backend_server.log`

**Application not starting:**
- Verify environment variables are set: `echo $VPS $DOMAIN`
- Check Python dependencies: `pip list`
- Review error messages in terminal

## ✅ Quick Checklist

- [ ] Project uploaded to VPS
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Environment variables set (`VPS=true`, `DOMAIN=americanelitebiz.com`)
- [ ] Nginx reverse proxy configured
- [ ] SSL certificate installed (if using HTTPS)
- [ ] Application running on VPS
- [ ] Domain accessible from local browser

