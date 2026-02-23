web: python manage.py migrate && python manage.py collectstatic --noinput && python manage.py createsuperuser --noinput || true && gunicorn pracsite.wsgi --workers 8 --timeout 120
