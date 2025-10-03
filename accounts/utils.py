
import jwt
import random
import re
from datetime import datetime, timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from rest_framework.exceptions import AuthenticationFailed
from cryptography.fernet import Fernet
from django.contrib.auth.hashers import make_password, check_password

from django.contrib.auth.hashers import make_password, check_password
from cryptography.fernet import Fernet
from django.conf import settings
import jwt
from datetime import datetime, timedelta
# utils/encryption.py
from cryptography.fernet import Fernet
from django.conf import settings


from cryptography.fernet import Fernet
from django.conf import settings

def get_fernet():
    key = settings.FERNET_KEY
    if not key:
        raise ValueError("FERNET_KEY is not set in Django settings")
    return Fernet(key.encode())

def encrypt_token(token: str) -> bytes:
    fernet = get_fernet()
    return fernet.encrypt(token.encode())       # <--- تُرجع bytes


def decrypt_token(encrypted: bytes) -> str:
    fernet = get_fernet()
    return fernet.decrypt(encrypted).decode()   # bytes → str


# دوال التشفير والتحقق

def verify_encrypted_token(raw_code: str, encrypted_code: str) -> bool:
    """مقارنة الرمز المدخل مع المشفر."""
    return check_password(raw_code, encrypted_code)

def create_jwt_token(payload: dict, expires_minutes: int = 60) -> str:
    """إنشاء JWT Token مع صلاحية محددة"""
    payload.update({
        'exp': datetime.utcnow() + timedelta(minutes=expires_minutes),
        'iat': datetime.utcnow()
    })
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

def decode_jwt_token(token: str) -> dict:
    """فك تشفير JWT Token"""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
# ------------------ JWT Utilities ------------------


def create_monthly_token(payload: dict) -> str:
    """إنشاء توكن صالح لمدة شهر."""
    return create_jwt_token(payload, expires_minutes=60 * 24 * 30)

# ------------------ Token Encryption ------------------




# ------------------ Email Operations ------------------

def send_verification_email(email: str, code: str) -> None:
    """إرسال رمز التحقق إلى البريد الإلكتروني."""
    subject = "رمز التحقق الخاص بك"
    message = f"رمز التحقق الخاص بك هو: {code}"
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)



# ------------------ توليد رمز التحقق ------------------
def generate_verification_code(length: int = 6) -> str:
    """توليد رمز تحقق رقمي عشوائي"""
    return ''.join(random.choices('0123456789', k=length))

