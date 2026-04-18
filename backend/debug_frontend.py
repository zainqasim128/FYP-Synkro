"""Test what the frontend sends to backend"""
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

@app.route('/api/auth/login', methods=['POST'])
def login():
    print("\n" + "="*50)
    print("FRONTEND REQUEST RECEIVED!")
    print("="*50)
    print(f"Method: {request.method}")
    print(f"URL: {request.url}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Data: {request.get_data(as_text=True)}")
    print(f"Form: {dict(request.form)}")
    print(f"Args: {dict(request.args)}")
    print("="*50)

    # Return the same response as the real backend
    return jsonify({
        "access_token": "test_token_123",
        "refresh_token": "test_refresh_123",
        "token_type": "bearer"
    })

if __name__ == '__main__':
    print("Starting test server on port 8001...")
    print("Configure frontend to use http://localhost:8001")
    print("Then try logging in and see what gets sent!")
    app.run(host='127.0.0.1', port=8001, debug=True)
