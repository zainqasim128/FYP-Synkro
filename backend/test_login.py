"""Test login endpoint"""
import requests
import json

url = "http://127.0.0.1:8000/api/auth/login"
data = {
    "username": "zain@gmail.com",
    "password": "11223344"
}

print("[*] Testing login endpoint...")
print(f"[*] URL: {url}")
print(f"[*] Credentials: {data}")

try:
    response = requests.post(url, data=data, timeout=5)
    print(f"\n[*] Status Code: {response.status_code}")
    print(f"[*] Response:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"[!] Error: {e}")
