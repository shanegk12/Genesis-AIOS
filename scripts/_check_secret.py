"""Check current ADMIN_API_KEY in Secret Manager via REST."""
import json, base64
from google.auth.transport.requests import Request, AuthorizedSession
from google.oauth2.credentials import Credentials

token_path = "drive-token.json"
t = json.load(open(token_path))
print("Token scopes:", t.get("scopes"))

# Try with cloud-platform scope (may not be in token)
creds = Credentials.from_authorized_user_file(token_path,
    ["https://www.googleapis.com/auth/cloud-platform"])
if not creds.valid:
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as e:
            print(f"Refresh failed: {e}")

session = AuthorizedSession(creds)
resp = session.get(
    "https://secretmanager.googleapis.com/v1/projects/genesis-modularity"
    "/secrets/ADMIN_API_KEY/versions/latest:access"
)
print(f"Secret Manager response: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    val = base64.b64decode(data["payload"]["data"]).decode()
    print(f"ADMIN_API_KEY = {val!r}")
else:
    print(resp.text[:400])
