from google_auth_oauthlib.flow import InstalledAppFlow

client_id = input("Client ID: ").strip()
client_secret = input("Client secret: ").strip()

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    },
    scopes=["https://www.googleapis.com/auth/drive"],
)

creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nYour refresh token:\n")
print(creds.refresh_token)