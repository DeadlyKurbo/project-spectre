from flask import Flask, request, redirect
import requests
import os

app = Flask(__name__)

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = "https://project-spectre-production.up.railway.app/oauth2callback"

@app.route("/oauth2callback")
def oauth2callback():
    code = request.args.get("code")

    if not code:
        return "No code provided", 400

    token_url = "https://oauth2.googleapis.com/token"

    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    r = requests.post(token_url, data=data, headers=headers)

    if r.status_code != 200:
        return f"Token exchange failed: {r.text}", 400

    tokens = r.json()

    # Save the tokens somewhere (for now just return them)
    return f"Access token: {tokens['access_token']}<br>Refresh token: {tokens.get('refresh_token', 'Not provided')}"
