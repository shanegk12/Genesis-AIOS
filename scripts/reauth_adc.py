"""
One-time script: OAuth flow with custom client → writes ADC credentials.
Run this whenever the Google ADC token expires.

Usage: python scripts/reauth_adc.py
"""
import json, os
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/gmail.send",
]

CLIENT_FILE = os.path.join(os.path.dirname(__file__), "..", "oauth-client.json")
ADC_PATH = os.path.join(os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json")

flow = InstalledAppFlow.from_client_secrets_file(CLIENT_FILE, SCOPES)
creds = flow.run_local_server(port=0)

adc_data = {
    "account": "",
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "refresh_token": creds.refresh_token,
    "type": "authorized_user",
    "universe_domain": "googleapis.com",
}

os.makedirs(os.path.dirname(ADC_PATH), exist_ok=True)
with open(ADC_PATH, "w") as f:
    json.dump(adc_data, f, indent=2)

print(f"ADC credentials written to:\n  {ADC_PATH}")
print(f"Scopes granted: {creds.scopes}")
print(f"\nGMAIL_REFRESH_TOKEN (add to Secret Manager):\n{creds.refresh_token}")
