from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, HTMLResponse
from pathlib import Path
from pydantic import BaseModel, Field, validator
from typing import Optional
import json
import os
import pickle
import datetime
import re
from urllib.parse import urlencode
from google.oauth2.credentials import Credentials
import google.auth.transport.requests
import requests

app = FastAPI(title="YouTube OAuth Manager", description="Manage YouTube OAuth tokens with user identifiers")

def validate_user_id(user_id: str) -> bool:
    """
    Validate user identifier format.
    - Only alphanumeric characters (A-Z, a-z, 0-9)
    - Length between 3 and 50 characters
    - No spaces, special characters, or unicode
    """
    if not user_id:
        return False
    
    # Check length
    if len(user_id) < 3 or len(user_id) > 50:
        return False
    
    # Check if only alphanumeric characters (ASCII only)
    if not re.match(r'^[a-zA-Z0-9]+$', user_id):
        return False
    
    return True

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
    user_id: str = Field(..., min_length=3, max_length=50, description="User identifier (3-50 alphanumeric characters only)")
    
    @validator('user_id')
    def validate_user_id_format(cls, v):
        if not validate_user_id(v.strip()):
            raise ValueError('User ID must be 3-50 characters long and contain only letters and numbers (no spaces or special characters)')
        return v.strip()

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

@app.get("/api/validate-user-id/{user_id}")
def validate_user_id_endpoint(user_id: str):
    """Validate a user identifier format."""
    try:
        # Decode any URL encoding first
        from urllib.parse import unquote
        decoded_user_id = unquote(user_id)
        
        is_valid = validate_user_id(decoded_user_id)
        if is_valid:
            return {
                "valid": True,
                "message": "User ID format is valid",
                "user_id": decoded_user_id
            }
        else:
            return {
                "valid": False,
                "message": "User ID must be 3-50 characters long and contain only letters and numbers (no spaces or special characters)",
                "user_id": decoded_user_id
            }
    except Exception as e:
        return {
            "valid": False,
            "message": f"Error validating user ID: {str(e)}",
            "user_id": user_id
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
        
        # Validate user_id format - only alphanumeric characters
        if not validate_user_id(user_id):
            raise HTTPException(
                status_code=400, 
                detail="User ID must be 3-50 characters long and contain only letters and numbers (no spaces or special characters)"
            )
        
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
        
        # Validate user_id from state parameter for security
        if user_id != "unknown" and not validate_user_id(user_id):
            print(f"❌ Invalid user_id format in OAuth callback: {user_id}")
            from urllib.parse import quote
            encoded_message = quote("Invalid user identifier format")
            return RedirectResponse(
                url=f"/?error=true&message={encoded_message}",
                status_code=302
            )
        
        # Exchange authorization code for tokens
        success = exchange_code_for_tokens(user_id, code)
        print(f"🔄 Token exchange result: {success}")
        
        if success:
            print(f"✅ OAuth completed successfully for {user_id}")
            # Redirect back to the main page with success message (URL encode parameters)
            from urllib.parse import quote
            encoded_user_id = quote(user_id)
            encoded_message = quote(f"OAuth authorization completed successfully for {user_id}")
            return RedirectResponse(
                url=f"/?success=true&user_id={encoded_user_id}&message={encoded_message}",
                status_code=302
            )
        else:
            print(f"❌ Token exchange failed for {user_id}")
            from urllib.parse import quote
            encoded_message = quote("Failed to exchange authorization code for tokens")
            return RedirectResponse(
                url=f"/?error=true&message={encoded_message}",
                status_code=302
            )
    except Exception as e:
        print(f"❌ OAuth callback error: {e}")
        import traceback
        traceback.print_exc()
        # Redirect back with error message
        from urllib.parse import quote
        encoded_message = quote(f"OAuth authorization failed: {str(e)}")
        return RedirectResponse(
            url=f"/?error=true&message={encoded_message}",
            status_code=302
        )

@app.get("/privacy")
def privacy_policy():
    """Serve privacy policy with environment variable substitution."""
    try:
        # Read the privacy policy template
        privacy_path = Path(__file__).parent.parent / "frontend" / "privacy.html"
        if not privacy_path.exists():
            raise HTTPException(status_code=404, detail="Privacy policy template not found")
        
        with open(privacy_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace template variables with environment values
        replacements = {
            '{{APP_TITLE}}': os.getenv('APP_TITLE', 'YouTube OAuth Manager'),
            '{{COMPANY_NAME}}': os.getenv('COMPANY_NAME', 'Your Company Name'),
            '{{PRIVACY_CONTACT_EMAIL}}': os.getenv('PRIVACY_CONTACT_EMAIL', 'privacy@example.com'),
        }
        
        # Apply all replacements
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        
        return HTMLResponse(content=content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to serve privacy policy: {str(e)}")

@app.get("/")
def serve_index():
    """Serve index page with environment variable substitution."""
    try:
        # Read the index HTML template
        index_path = Path(__file__).parent.parent / "frontend" / "index.html"
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="Index template not found")
        
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Get configuration values
        app_title = os.getenv('APP_TITLE', '🎥 YouTube OAuth Manager')
        logo_path = os.getenv('LOGO_PATH', '/logo.svg')
        theme_color = os.getenv('THEME_COLOR', '#667eea')
        
        # Generate lighter color for gradient
        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        def generate_lighter_color(hex_color, factor=0.3):
            try:
                r, g, b = hex_to_rgb(hex_color)
                # Blend with white to make lighter
                r = int(r + (255 - r) * factor)
                g = int(g + (255 - g) * factor)
                b = int(b + (255 - b) * factor)
                return f"#{r:02x}{g:02x}{b:02x}"
            except:
                return "#764ba2"  # fallback
        
        theme_color_light = generate_lighter_color(theme_color, 0.4)
        
        # Replace template variables with environment values
        replacements = {
            '{{APP_TITLE}}': app_title,
            '{{LOGO_PATH}}': logo_path,
            '{{THEME_COLOR}}': theme_color,
            '{{THEME_COLOR_LIGHT}}': theme_color_light,
        }
        
        # Apply all replacements
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        
        return HTMLResponse(content=content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to serve index page: {str(e)}")

# Mount other static files (excluding index.html which we serve dynamically)
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend"), name="static") 