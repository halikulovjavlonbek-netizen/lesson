import re
import requests
from django.conf import settings

def normalize_kz_phone(phone_input: str) -> str:
    """
    Қозоғистон телефон рақамларини ягона E.164 форматига келтириш: 77XXXXXXXXX
    Агар @lid ёки @c.us бўлса, уни ўзгаришсиз сақлаш
    Мисоллар:
    - '+7 701 234 56 78' -> '77012345678'
    - '8 701 234 56 78'  -> '77012345678'
    - '+229613867384980@lid' -> '229613867384980@lid'
    """
    if not phone_input:
        return ""
    s = str(phone_input).strip()
    if '@lid' in s or '@c.us' in s:
        return s.lstrip('+')

    digits = re.sub(r'\D', '', s)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits

    if len(digits) == 11 and digits.startswith('77'):
        return digits
    return digits

def format_kzt(amount) -> str:
    """
    Суммани Қозоғистон теңгеси форматига ўтказиш: 15 000 ₸
    """
    try:
        val = int(amount)
        # 15000 -> 15 000 ₸
        formatted = f"{val:,}".replace(",", " ") + " ₸"
        return formatted
    except (ValueError, TypeError):
        return f"{amount} ₸"

def send_whatsapp_message(phone: str, message: str, amount: int = None, timeout: int = 5) -> dict:
    """
    wa-platform Node.js сервисига POST /whatsapp/send сўровини юбориш.
    """
    wa_url = getattr(settings, 'WHATSAPP_API_URL', 'http://localhost:3000')
    api_key = getattr(settings, 'WHATSAPP_API_KEY', 'kz_secret_wa_token_7708')

    clean_phone = normalize_kz_phone(phone)
    if not clean_phone:
        return {'success': False, 'error': f'Нотўғри телефон рақами: {phone}'}

    payload = {
        'phone': clean_phone,
        'message': message,
    }
    if amount is not None:
        payload['amount'] = amount

    try:
        resp = requests.post(
            f"{wa_url.rstrip('/')}/whatsapp/send",
            json=payload,
            headers={'x-api-key': api_key, 'Content-Type': 'application/json'},
            timeout=timeout
        )
        data = resp.json()
        if resp.status_code == 200 and data.get('ok'):
            return {'success': True, 'data': data}
        return {'success': False, 'error': data.get('error', 'Номаълум хатолик')}
    except requests.exceptions.ConnectionError:
        start_whatsapp_background_service()
        return {
            'success': False,
            'error': 'WhatsApp сервиси ишга туширилди. 10 сониядан сўнг қайта уриниб кўринг.'
        }
    except requests.exceptions.ReadTimeout:
        return {
            'success': False,
            'error': 'WhatsApp сервиси жавоб бермаяпти. Сервис ишга туширилмаган бўлиши мумкин.'
        }
    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': 'WhatsApp сервисига уланиш вақти тугади. Қайта уриниб кўринг.'
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

_last_start_attempt = 0

def start_whatsapp_background_service() -> bool:
    """
    Агар WhatsApp Node.js (wa-platform) сервиси ўчиб қолган бўлса,
    уни фон режимида автоматик тарзда ишга тушириш.
    """
    global _last_start_attempt
    import time
    import os
    import sys
    import socket
    import subprocess

    # Ҳар 10 сонияда кўпи билан 1 марта ишга тушириш уриниши
    now = time.time()
    if now - _last_start_attempt < 10:
        return True
    _last_start_attempt = now

    # Порт 3000 текшириш
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            if s.connect_ex(('127.0.0.1', 3000)) == 0:
                return True  # Аллақачон ишламоқда
    except Exception:
        pass

    base_dir = getattr(settings, 'BASE_DIR', None)
    if not base_dir:
        return False

    wa_dir = os.path.join(str(base_dir), 'wa-platform')
    server_js = os.path.join(wa_dir, 'server.js')
    if not os.path.exists(server_js):
        return False

    try:
        flags = 0
        if sys.platform == 'win32':
            # Ойнасиз (hidden) ва detached фон жараёни қилиб юргизиш
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

        subprocess.Popen(
            ['node', 'server.js'],
            cwd=wa_dir,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False
        )
        return True
    except Exception as e:
        print(f"[WhatsApp Auto-Start Error]: {e}")
        return False


def get_whatsapp_status(timeout: int = 5, auto_start: bool = True) -> dict:
    """
    WhatsApp сервиси ҳолатини текшириш (status, qr, info).
    Агар сервис ўчиқ бўлса, уни автоматик ишга туширади.
    """
    wa_url = getattr(settings, 'WHATSAPP_API_URL', 'http://localhost:3000')
    api_key = getattr(settings, 'WHATSAPP_API_KEY', 'kz_secret_wa_token_7708')

    try:
        resp = requests.get(
            f"{wa_url.rstrip('/')}/whatsapp/status",
            headers={'x-api-key': api_key},
            timeout=timeout
        )
        if resp.status_code == 200:
            return resp.json()
        return {'ok': False, 'status': 'unauthorized', 'error': 'API калит мос келмади'}
    except Exception:
        if auto_start:
            started = start_whatsapp_background_service()
            if started:
                return {
                    'ok': True,
                    'status': 'starting',
                    'message': 'WhatsApp сервиси автоматик ишга туширилмоқда... Илтимос, бир неча сония кутинг.'
                }
        return {'ok': False, 'status': 'offline', 'error': 'Сервис фаол эмас'}

