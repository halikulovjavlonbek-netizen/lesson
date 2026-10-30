"""
Instagram токенларини муддатидан олдин автомат тарзда янгиловчи Django Management Command.
Cron ёки Schedule орқали ҳар куни бир марта ишга туширилиши мумкин:
  python manage.py refresh_instagram_tokens
"""

import sys
from django.core.management.base import BaseCommand
from django.utils import timezone
from courses.models import InstagramSettings
from courses.instagram import refresh_long_lived_token


class Command(BaseCommand):
    help = "Instagram token refresh command"

    def handle(self, *args, **options):
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except Exception:
                pass
        self.stdout.write("Instagram токенлари текширилмоқда...")

        settings_objs = InstagramSettings.objects.filter(is_connected=True)
        if not settings_objs.exists():
            self.stdout.write(self.style.WARNING("Ҳеч қандай уланган Instagram ҳисоб топилмади."))
            return

        for obj in settings_objs:
            if not obj.access_token:
                continue

            days_left = 999
            if obj.expires_at:
                days_left = (obj.expires_at - timezone.now()).days

            self.stdout.write(f"Аккаунт: @{obj.ig_username} | Қолган кунлар: {days_left}")

            # Агар қолган кунлар 15 кундан кам бўлса ёки токен муддати кўрсатилмаган бўлса
            if days_left <= 15:
                self.stdout.write(f"Токен янгиланмоқда (@{obj.ig_username})...")
                res = refresh_long_lived_token(obj)
                if res.get("success"):
                    new_days = res.get("expires_in", 0) // 86400
                    self.stdout.write(self.style.SUCCESS(f"✅ Токен муваффақиятли янгиланди! Янги муддат: {new_days} кун."))
                else:
                    self.stdout.write(self.style.ERROR(f"❌ Токенни янгилашда хатолик: {res.get('error')}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Токен ҳали фаол ({days_left} кун қолди), янгилаш шарт эмас."))
