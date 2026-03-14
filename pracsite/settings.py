"""
Django settings for pracsite project.
"""

import dj_database_url
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / '.env')

# Security
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-local-dev-only')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'
ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'pracsite-production.up.railway.app',
    'pracsite-dev.up.railway.app',
    'rockofschool.rocks',
    'www.rockofschool.rocks',
]

# Railway 자동 도메인 허용
RAILWAY_PUBLIC_DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'pracapp'
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'pracapp.middleware.DemoSessionCleanupMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'pracsite.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'pracapp.context_processors.demo_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'pracsite.wsgi.application'


# Database
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    # 로컬 개발용 (Railway 변수가 없을 때만 실행)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'pracapp.validators.ModernKoreanPasswordValidator'},
]


# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True


# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/home/'
LOGOUT_REDIRECT_URL = '/'

AUTH_USER_MODEL = 'pracapp.User'

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# 1. CSRF 신뢰 도메인 설정
def _normalized_hosts(hosts):
    out = []
    for h in hosts:
        host = (h or '').strip()
        if not host:
            continue
        if host.startswith('http://') or host.startswith('https://'):
            host = host.split('://', 1)[1]
        host = host.rstrip('/')
        if host and host not in out:
            out.append(host)
    return out


_env_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '')
_host_candidates = list(ALLOWED_HOSTS)
if _env_allowed_hosts:
    _host_candidates.extend([h.strip() for h in _env_allowed_hosts.split(',') if h.strip()])

CSRF_TRUSTED_ORIGINS = []
for host in _normalized_hosts(_host_candidates):
    if host in ('localhost', '127.0.0.1'):
        continue
    CSRF_TRUSTED_ORIGINS.append(f"https://{host}")

# Railway 관련 도메인들 추가
if RAILWAY_PUBLIC_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RAILWAY_PUBLIC_DOMAIN}")

# Railway 서브도메인 전체 허용 (보험용)
CSRF_TRUSTED_ORIGINS.append("https://*.up.railway.app")

# 2. 로컬/배포 환경별 분기 설정
if not DEBUG:
    # [배포 환경] 강력한 보안 적용 (HTTPS 필수)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # 1년
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    # [로컬 환경] 테스트 편의를 위해 보안 완화
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False

    # 로컬에서 로그인이 튕기지 않도록 http 주소 추가
    CSRF_TRUSTED_ORIGINS += [
        "http://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
