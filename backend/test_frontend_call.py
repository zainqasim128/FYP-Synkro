"""Test frontend API call"""
import requests
import json

# Test the login endpoint that the frontend would call
url = "http://127.0.0.1:8000/api/auth/login"
headers = {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'http://localhost:3000'
}
data = {
    "username": "zain@gmail.com",
    "password": "11223344"
}

print("[*] Testing frontend-style login call...")
print(f"[*] URL: {url}")
print(f"[*] Headers: {headers}")
print(f"[*] Data: {data}")

try:
    response = requests.post(url, headers=headers, data=data, timeout=5)
    print(f"\n[*] Status Code: {response.status_code}")
    print(f"[*] Response Headers: {dict(response.headers)}")
    print(f"[*] Response:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"[!] Error: {e}")
