import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
username = 'admin'
password = 'admin123password'

if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email='admin@studycenter.kz', password=password)
    print(f"Суперпользователь '{username}' создан! Пароль: {password}")
else:
    u = User.objects.get(username=username)
    u.set_password(password)
    u.save()
    print(f"Пароль для '{username}' обновлен на: {password}")
