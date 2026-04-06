from app.security import verify_password
from app.db import SessionLocal
from model.models import User

db = SessionLocal()
user = db.query(User).filter(User.username == "admin").first()

if user:
    print("Found admin user.")
    print(f"Stored hash: {user.password_hash}")
    match = verify_password("admin", user.password_hash)
    print(f"Does 'admin' match stored hash? {match}")
    
    match2 = verify_password("password", user.password_hash)
    print(f"Does 'password' match stored hash? {match2}")
