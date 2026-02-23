import os
import psycopg2

# 서버(Railway)가 들고 있는 DATABASE_URL이라는 열쇠를 빌려옵니다.
db_url = os.environ.get('DATABASE_URL')

# 빌려온 열쇠로 금고(Supabase)에 접속합니다.
conn = psycopg2.connect(db_url)

print("연결 성공!")