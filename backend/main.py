from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
import json
import os
import pickle
import datetime
from urllib.parse import urlencode
from google.oauth2.credentials import Credentials
import google.auth.transport.requests
import requests

app = FastAPI(title="YouTube OAuth Manager", description="Manage YouTube OAuth tokens with user identifiers")

def get_domain():
    """Get domain from environment variable, fallback to localhost."""
    return os.getenv('DOMAIN', 'localhost')

def get_redirect_uri():
    """Get the proper redirect URI based on domain."""
    domain = get_domain()
    if domain == 'localhost':
        return f"http://{domain}:8000/api/oauth/callback"
    else:
        return f"https://{domain}/api/oauth/callback"

class AuthRequest(BaseModel):
    user_id: str

# YouTube API scopes
SCOPES = [
    'https://www.googleapis.com/auth/yt-analytics.readonly',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/yt-analytics-monetary.readonly'
]

def get_client_secrets():
    """Load client secrets directly."""
    secrets_path = Path(__file__).parent / "secrets" / "client_secret.json"
    if not secrets_path.exists():
        return None
    
    with open(secrets_path, 'r') as f:
        secrets_data = json.load(f)
    
    if 'web' in secrets_data:
        return secrets_data['web']
    elif 'installed' in secrets_data:
        return secrets_data['installed']
    else:
        return None

@app.get("/api/status")
def status():
    return {
        "status": "ok", 
        "service": "YouTube OAuth Manager",
        "domain": get_domain(),
        "redirect_uri": get_redirect_uri()
    }

@app.get("/api/config")
def get_config():
    """Get application configuration for frontend."""
    return {
        "app_title": os.getenv('APP_TITLE', '🎥 YouTube OAuth Manager'),
        "logo_path": os.getenv('LOGO_PATH', '/logo.svg'),
        "theme_color": os.getenv('THEME_COLOR', '#667eea')
    }

@app.get("/api/oauth/check-setup")
def check_oauth_setup():
    """Check if Google OAuth is properly configured."""
    client_secrets = get_client_secrets()
    has_secrets = client_secrets is not None
    return {
        "configured": has_secrets,
        "message": "Google OAuth client secrets found" if has_secrets else "Please configure Google OAuth client secrets"
    }

@app.post("/api/oauth/start")
def start_oauth_flow(request: AuthRequest):
    """Start OAuth flow for a specific user identifier."""
    try:
        if not request.user_id or not request.user_id.strip():
            raise HTTPException(status_code=400, detail="User ID is required")
        
        user_id = request.user_id.strip()
        
        # Load client secrets
        client_secrets = get_client_secrets()
        if not client_secrets:
            raise HTTPException(status_code=500, detail="Google OAuth client secrets not found")
        
        client_id = client_secrets['client_id']
        redirect_uri = get_redirect_uri()
        
        # Build OAuth URL manually
        auth_params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'scope': ' '.join(SCOPES),
            'response_type': 'code',
            'state': user_id,
            'access_type': 'offline',
            'prompt': 'consent'
        }
        
        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
        
        return {
            "user_id": user_id,
            "auth_url": auth_url,
            "message": "Visit the auth_url to complete OAuth authorization"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start OAuth flow: {str(e)}")



def exchange_code_for_tokens(user_id: str, authorization_code: str) -> bool:
    """Exchange authorization code for access and refresh tokens."""
    try:
        
        print(f"🔄 Starting token exchange for user: {user_id}")
        
        # Load client secrets
        client_secrets = get_client_secrets()
        if not client_secrets:
            print("❌ No client secrets found")
            return False
        
        print(f"✅ Client secrets loaded successfully")
        
        # Exchange code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            'client_id': client_secrets['client_id'],
            'client_secret': client_secrets['client_secret'],
            'code': authorization_code,
            'grant_type': 'authorization_code',
            'redirect_uri': get_redirect_uri()
        }
        
        print(f"🔄 Making token exchange request to Google...")
        response = requests.post(token_url, data=token_data)
        print(f"🔄 Token exchange response status: {response.status_code}")
        
        if response.status_code == 200:
            tokens = response.json()
            print(f"✅ Token exchange successful, received tokens")
            print(f"🔄 Access token starts with: {tokens.get('access_token', '')[:20]}...")
            
            # Create credentials directory if it doesn't exist
            credentials_dir = Path(__file__).parent / "secrets" / "credentials"
            credentials_dir.mkdir(parents=True, exist_ok=True)
            print(f"✅ Credentials directory created/exists: {credentials_dir}")
            
            # Save tokens to file
            creds_path = credentials_dir / f"creds_{user_id}.pkl"
            print(f"🔄 Saving credentials to: {creds_path}")
            
            # Create proper Google credentials object (same format as example.py)
            expiry = None
            if 'expires_in' in tokens:
                expiry = datetime.datetime.utcnow() + datetime.timedelta(seconds=int(tokens['expires_in']))
            
            creds = Credentials(
                token=tokens.get('access_token'),
                refresh_token=tokens.get('refresh_token'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_secrets['client_id'],
                client_secret=client_secrets['client_secret'],
                scopes=SCOPES,
                expiry=expiry
            )
            
            with open(creds_path, 'wb') as f:
                pickle.dump(creds, f)
            
            print(f"✅ Credentials saved successfully to {creds_path}")
            print(f"🔄 File exists after save: {creds_path.exists()}")
            return True
        else:
            print(f"❌ Token exchange failed: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error exchanging code for tokens: {e}")
        import traceback
        traceback.print_exc()
        return False

@app.get("/api/oauth/callback")  
def oauth_callback(code: str = Query(...), state: Optional[str] = Query(None)):
    """Handle OAuth callback and automatically complete the flow."""
    try:
        user_id = state if state else "unknown"
        print(f"🔄 OAuth callback received for user_id: {user_id}")
        print(f"🔄 Authorization code: {code[:20]}...")
        
        # Exchange authorization code for tokens
        success = exchange_code_for_tokens(user_id, code)
        print(f"🔄 Token exchange result: {success}")
        
        if success:
            print(f"✅ OAuth completed successfully for {user_id}")
            # Redirect back to the main page with success message
            return RedirectResponse(
                url=f"/?success=true&user_id={user_id}&message=OAuth authorization completed successfully for {user_id}",
                status_code=302
            )
        else:
            print(f"❌ Token exchange failed for {user_id}")
            return RedirectResponse(
                url=f"/?error=true&message=Failed to exchange authorization code for tokens",
                status_code=302
            )
    except Exception as e:
        print(f"❌ OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        # Redirect back with error message
        return RedirectResponse(
            url=f"/?error=true&message=OAuth authorization failed: {str(e)}",
            status_code=302
        )


# Mount static files AFTER API routes to prevent conflicts
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="static") 