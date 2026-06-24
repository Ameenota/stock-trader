import json
import urllib.request
import urllib.parse
import secrets
import hashlib
import base64
import http.server
import socketserver
import webbrowser
import sys

PORT = 8082
REDIRECT_URI = f"http://localhost:{PORT}/callback"

# Global state to share between HTTP handler and main loop
auth_code = None

class CallbackHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging request details to keep output clean
        pass

    def do_GET(self):
        global auth_code
        parsed_url = urllib.parse.urlparse(self.path)
        if parsed_url.path == "/callback":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            auth_code = query_params.get("code", [None])[0]
            
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            
            if auth_code:
                html = """
                <html>
                <body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>
                    <h2 style='color: #00c805;'>Authorization Successful!</h2>
                    <p>You can close this tab and return to the terminal.</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
            else:
                html = """
                <html>
                <body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>
                    <h2 style='color: #ff5000;'>Authorization Failed</h2>
                    <p>No code returned. Check the terminal output.</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
            
            # Stop the server after handling callback
            # We do this by raising a custom exception or letting the runner handle it
            raise KeyboardInterrupt

def run_local_server():
    server = socketserver.TCPServer(("", PORT), CallbackHandler)
    try:
        server.handle_request() # Wait for a single request
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()

def main():
    print("Step 1: Performing Dynamic Client Registration with Robinhood...")
    register_url = "https://agent.robinhood.com/oauth/trading/register"
    reg_data = {
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "client_name": "AI Stock Trader Capstone"
    }
    
    req = urllib.request.Request(
        register_url,
        data=json.dumps(reg_data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode("utf-8"))
            client_id = res["client_id"]
            print(f"Dynamic Client Registration successful! Client ID: {client_id}")
    except Exception as e:
        print(f"Error during registration: {e}")
        sys.exit(1)

    print("\nStep 2: Generating PKCE Verifier and Challenge...")
    # Generate PKCE verifier (43-128 chars) and challenge (base64url-encoded SHA-256)
    code_verifier = secrets.token_urlsafe(64)
    sha256_hash = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_hash).decode("utf-8").rstrip("=")

    # Authorization URL
    auth_params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": "internal"
    }
    auth_url = f"https://robinhood.com/oauth?{urllib.parse.urlencode(auth_params)}"
    
    print("\nStep 3: Starting local callback listener and launching browser...")
    print(f"Opening authorization URL:\n{auth_url}\n")
    print("Please authorize the app in the browser tab that opens. Waiting...")
    
    # Launch browser
    webbrowser.open(auth_url)
    
    # Start server to wait for callback
    run_local_server()
    
    if not auth_code:
        print("Error: Did not receive authorization code.")
        sys.exit(1)
        
    print(f"Received authorization code: {auth_code}")
    print("\nStep 4: Exchanging authorization code for OAuth tokens...")
    
    token_url = "https://api.robinhood.com/oauth2/token/"
    token_params = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier
    }
    
    token_req = urllib.request.Request(
        token_url,
        data=urllib.parse.urlencode(token_params).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    try:
        import os
        import time
        with urllib.request.urlopen(token_req) as response:
            token_res = json.loads(response.read().decode("utf-8"))
            print("\n==================================================")
            print("AUTHENTICATION SUCCESSFUL!")
            print("==================================================")
            print(f"Access Token:\n{token_res.get('access_token')}\n")
            print(f"Refresh Token:\n{token_res.get('refresh_token')}\n")
            print(f"Expires In: {token_res.get('expires_in')} seconds")
            print("==================================================")
            
            # Save credentials to robinhood_creds.json in agent/app/ directory
            creds_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "robinhood_creds.json")
            creds = {
                "client_id": client_id,
                "access_token": token_res.get("access_token"),
                "refresh_token": token_res.get("refresh_token"),
                "expires_at": int(time.time()) + int(token_res.get("expires_in", 86400))
            }
            with open(creds_path, "w") as f:
                json.dump(creds, f, indent=2)
            print(f"\nSaved credentials to {creds_path}!")
    except Exception as e:
        print(f"Error exchanging authorization code: {e}")
        if hasattr(e, 'read'):
            print("Details:", e.read().decode("utf-8"))
        sys.exit(1)

if __name__ == "__main__":
    main()
