"""Create a test user for development"""
import sqlite3
import uuid
from app.utils.security import get_password_hash
from datetime import datetime

conn = sqlite3.connect('dev.db')
c = conn.cursor()

# Create a test team first
team_id = str(uuid.uuid4())
c.execute('''
    INSERT INTO teams (id, name, plan, settings, created_at)
    VALUES (?, ?, ?, ?, ?)
''', (team_id, "Test Team", "free", "{}", datetime.utcnow()))

# Create test user with the credentials they want
email = "zain@gmail.com"
password = "11223344"
full_name = "Zain Test"

hashed_pw = get_password_hash(password)
user_id = str(uuid.uuid4())

c.execute('''
    INSERT INTO users (id, email, password_hash, full_name, team_id, role, is_active, is_verified, created_at, updated_at, timezone)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
''', (user_id, email, hashed_pw, full_name, team_id, "developer", True, False, datetime.utcnow(), datetime.utcnow(), "UTC"))

conn.commit()
print(f"✅ User created successfully!")
print(f"   Email: {email}")
print(f"   Password: {password}")
print(f"   Role: developer")
conn.close()
