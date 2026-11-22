# How to log in to FinSentinel

## FinSentinel Operator Console (port 5173)

The console is protected by a bearer token stored in a local file — never hardcoded in the UI.

**Token file location:**
```
%USERPROFILE%\.finsentinel\dev_token.txt
```
*(On Windows this resolves to something like `C:\Users\YourName\.finsentinel\dev_token.txt`)*

**Steps:**
1. Start the backend: `python scripts/start_backend.py` (or the venv equivalent)
2. Start the frontend: `cd frontend && npm run dev`
3. Open `http://localhost:5173` in a browser
4. Open the token file in a text editor and copy its contents
5. Paste the token into the **Operator Token** field and click **Authenticate**

The token is kept in memory only — logging out or reloading the page clears it.

---

## Wazuh Dashboard (port 443 / HTTPS)

The Wazuh stack runs in Docker (WSL2). To access the dashboard:

**URL:** `https://localhost` (self-signed certificate — accept the browser warning)

**Credentials:**
- Username: `admin`
- Password: the value of `INDEXER_PASSWORD` in `~/finsentinel-wazuh/.env`

**Start the Wazuh stack (from WSL2):**
```bash
cd ~/finsentinel-wazuh
docker compose up -d
```

**Bypass the cert warning:**
- Chrome/Edge: click **Advanced → Proceed to localhost (unsafe)**
- Firefox: click **Advanced → Accept the Risk and Continue**

**Verify the stack is healthy:**
```powershell
python scripts/check_stack.py
```
All four containers (`wazuh-manager`, `wazuh-indexer`, `wazuh-dashboard`, `finsentinel-postgres`) should show `healthy`.
