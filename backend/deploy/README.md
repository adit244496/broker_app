# Deploying on the Azure VM (Ubuntu)

Server: `4.224.153.24`, user `srvadmin`, code at `/home/srvadmin/broker_app/broker_app`, virtualenv at
`backend/venv`. If any of these differ, edit `broker-api.service` before installing it.

Azure only lets ports 80, 443 and 8080 in, and other sites already use them, so this app shares 80/443 by
hostname. Until the real domain arrives it uses free sslip.io names (they resolve to the VM's IP) with
Let's Encrypt HTTPS:

| What | Address |
|---|---|
| API (mobile app + admin portal call it) | `https://broker-api.4-224-153-24.sslip.io` (Nginx -> uvicorn on 127.0.0.1:8019) |
| Admin portal | `https://broker-admin.4-224-153-24.sslip.io` |

This VM hosts other apps on ports 80, 8080, 8081 and more. Never remove or edit their files in
`/etc/nginx/sites-enabled/`.

## 0. Azure: open the ports
VM → **Networking** → Network Security Group, inbound rules:
- **80** and **443**: already open on this VM (shared with the other sites)
- **22** (SSH) from your office IP only
- Do **not** open 8019 (uvicorn) or 5432 (PostgreSQL)

Also make sure the VM's public IP is **Static** (Public IP resource → Configuration), so it doesn't change on restart.

## 1. Packages
```bash
sudo apt update
sudo apt install -y nginx postgresql python3-venv
```

## 2. Database
```bash
sudo -u postgres psql
```
```sql
CREATE USER broker_app WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE broker_app OWNER broker_app;
\q
```

## 3. Backend
```bash
cd ~/broker_app/broker_app/backend
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
```
Values to set in `.env` for this server:
```ini
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg://broker_app:choose-a-strong-password@localhost:5432/broker_app
AUTO_CREATE_TABLES=false
SECRET_KEY=            # python -c "import secrets; print(secrets.token_urlsafe(48))"
CORS_ORIGINS=["https://broker-admin.4-224-153-24.sslip.io"]
PUBLIC_BASE_URL=https://broker-api.4-224-153-24.sslip.io
SALESFORCE_MODE=live   # plus SALESFORCE_CLIENT_ID / _SECRET / _TOKEN_URL and SALESFORCE_WEBHOOK_SECRET
# SMS and email accounts can be left empty here and entered in the admin portal instead:
# Settings -> SMS (Gupshup) and Settings -> Email. Portal details take priority over .env.
```
`ENVIRONMENT=production` refuses to start without a strong `SECRET_KEY`, live Salesforce credentials and a
webhook secret: `journalctl -u broker-api` shows which one is missing.

```bash
python -m app.cli init-db
python -m app.cli create-admin you@ambujaneotia.com "Your Name"
mkdir -p media
```

## 4. Run it as a service
```bash
sudo cp deploy/broker-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now broker-api
systemctl status broker-api          # should say active (running)
curl http://127.0.0.1:8019/health    # {"status":"ok"}
```

## 5. Admin portal
Build it on the server (needs Node.js 20+: `sudo apt install -y nodejs npm`, or use nvm), or build on your
laptop and copy `admin/dist` across.
```bash
cd ~/broker_app/broker_app/admin
echo "VITE_API_BASE_URL=https://broker-api.4-224-153-24.sslip.io" > .env
npm ci && npm run build
sudo mkdir -p /var/www/broker-admin
sudo rsync -a --delete dist/ /var/www/broker-admin/
```

## 6. Nginx
```bash
cd ~/broker_app/broker_app/backend
sudo cp deploy/broker-proxy.conf /etc/nginx/snippets/broker-proxy.conf
sudo cp deploy/nginx-broker-app.conf /etc/nginx/sites-available/broker-app
sudo ln -sf /etc/nginx/sites-available/broker-app /etc/nginx/sites-enabled/broker-app
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d broker-api.4-224-153-24.sslip.io -d broker-admin.4-224-153-24.sslip.io
```
Check from your laptop: `https://broker-api.4-224-153-24.sslip.io/health` and `https://broker-admin.4-224-153-24.sslip.io`.

## 7. Firewall on the VM (if ufw is on)
```bash
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp   # already allowed on this VM
```

## Updating after a code change
```bash
cd ~/broker_app/broker_app && git pull
cd backend && source venv/bin/activate && pip install -r requirements.txt
sudo systemctl restart broker-api
# admin changed? repeat step 5
```

## Backups
Nightly database dump (`crontab -e`):
```
0 2 * * * pg_dump -U broker_app -h localhost broker_app | gzip > /home/srvadmin/backups/broker_app_$(date +\%F).sql.gz
```
Create `~/backups` first and add a `~/.pgpass` line (`localhost:5432:broker_app:broker_app:<password>`, mode 600).
Also back up `backend/media/` (admin-uploaded project images).

## When the domain arrives
1. Point DNS A records, e.g. `api.example.com` and `admin.example.com`, at `4.224.153.24`.
2. In `nginx-broker-app.conf`: in both blocks change the `listen` lines to `listen 80;` and set
   `server_name api.example.com;` (API) and `server_name admin.example.com;` (admin). Name-based, so they share
   port 80 with the other sites on this server. Reload Nginx.
3. `sudo apt install -y certbot python3-certbot-nginx && sudo certbot --nginx -d api.example.com -d admin.example.com`
4. `.env`: `PUBLIC_BASE_URL=https://api.example.com`, `CORS_ORIGINS=["https://admin.example.com"]`, restart.
5. Admin: `VITE_API_BASE_URL=https://api.example.com`, rebuild (step 5).
6. Mobile app: set `EXPO_PUBLIC_API_BASE_URL` to `https://api.example.com` in `eas.json` and build again. The
   old HTTP APK stops working once port 80 redirects to HTTPS, so testers must install the new one.
7. Remove the old sslip.io certificate: `sudo certbot delete`.
