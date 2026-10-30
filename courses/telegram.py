import io
import base64
import uuid
import requests
import qrcode
from PIL import Image
from django.utils import timezone
from .models import TelegramSettings, LeadApplication, TelegramMessage, Teacher, Student

def fetch_bot_info(token: str) -> dict:
    """
    Telegram getMe API орқали бот username ва маълумотларини аниқлаш ва @ белгисини олиб ташлаш.
    """
    token = (token or '').strip()
    if not token:
        return {'success': False, 'error': 'Bot token киритилмаган'}
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        resp = requests.get(url, timeout=7)
        data = resp.json()
        if data.get('ok'):
            res = data.get('result', {})
            raw_username = (res.get('username') or '').strip().lstrip('@')
            return {
                'success': True,
                'username': raw_username,
                'first_name': res.get('first_name', ''),
                'id': res.get('id'),
                'raw': res
            }
        return {'success': False, 'error': data.get('description', 'Telegram API хатолиги')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_telegram_webhook_info(token: str = None) -> dict:
    """Telegram getWebhookInfo API орқали жорий вебхук ҳолатини текшириш"""
    settings_obj = get_or_create_telegram_settings()
    token = (token or settings_obj.bot_token or '').strip()
    if not token:
        return {'success': False, 'error': 'Bot token топилмади'}
    try:
        url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
        resp = requests.get(url, timeout=8)
        data = resp.json()
        if data.get('ok'):
            return {'success': True, 'data': data.get('result', {})}
        return {'success': False, 'error': data.get('description', 'Ҳолатни олиб бўлмади')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def setup_telegram_webhook(webhook_url: str, token: str = None) -> dict:
    """Telegram setWebhook API орқали вебхукни фаоллаштириш (HTTPS талаб этилади)"""
    settings_obj = get_or_create_telegram_settings()
    token = (token or settings_obj.bot_token or '').strip()
    webhook_url = str(webhook_url or '').strip()
    if not token:
        return {'success': False, 'error': 'Bot token топилмади'}
    if not webhook_url:
        return {'success': False, 'error': 'Webhook URL манзилини киритинг'}
    if not webhook_url.startswith('https://'):
        return {'success': False, 'error': 'Telegram Webhook фақат HTTPS протоколини қабул қилади (масалан: https://domain.uz/api/telegram/webhook/)'}

    try:
        url = f"https://api.telegram.org/bot{token}/setWebhook"
        payload = {
            'url': webhook_url,
            'allowed_updates': [
                'message', 'edited_message', 'channel_post', 
                'edited_channel_post', 'business_message', 
                'edited_business_message', 'callback_query'
            ],
            'drop_pending_updates': False
        }
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get('ok'):
            settings_obj.webhook_url = webhook_url
            settings_obj.is_webhook_active = True
            settings_obj.save(update_fields=['webhook_url', 'is_webhook_active'])
            print(f"[Telegram Webhook Setup] Муваффақиятли ўрнатилди: {webhook_url}")
            return {'success': True, 'description': data.get('description', 'Webhook фаоллаштирилди'), 'webhook_url': webhook_url}
        return {'success': False, 'error': data.get('description', 'Webhook ўрнатиб бўлмади')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def delete_telegram_webhook(token: str = None) -> dict:
    """Telegram deleteWebhook API орқали вебхукни ўчириш (ва getUpdates polling'га қайтиш)"""
    settings_obj = get_or_create_telegram_settings()
    token = (token or settings_obj.bot_token or '').strip()
    if not token:
        return {'success': False, 'error': 'Bot token топилмади'}
    try:
        url = f"https://api.telegram.org/bot{token}/deleteWebhook"
        resp = requests.post(url, json={'drop_pending_updates': False}, timeout=10)
        data = resp.json()
        if data.get('ok'):
            settings_obj.is_webhook_active = False
            settings_obj.save(update_fields=['is_webhook_active'])
            print("[Telegram Webhook Delete] Вебхук ўчирилди, getUpdates polling режими фаоллашди.")
            return {'success': True, 'description': data.get('description', 'Webhook бекор қилинди')}
        return {'success': False, 'error': data.get('description', 'Вебхукни ўчириб бўлмади')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

class TelegramConnectResult:
    """Иккилик тупл (connect_url, qr_base64) ва атрибут/луғат сифатида ишлайдиган класс"""
    def __init__(self, connect_url: str, qr_base64: str, app_url: str, has_username: bool, bot_username: str, message: str):
        self.connect_url = connect_url
        self.qr_base64 = qr_base64
        self.app_url = app_url
        self.has_username = has_username
        self.bot_username = bot_username
        self.message = message

    def __iter__(self):
        return iter([self.connect_url, self.qr_base64])

    def __getitem__(self, key):
        return getattr(self, key)

    def to_dict(self):
        return {
            'connect_url': self.connect_url,
            'qr_base64': self.qr_base64,
            'app_url': self.app_url,
            'has_username': self.has_username,
            'bot_username': self.bot_username,
            'message': self.message,
        }

def get_or_create_telegram_settings() -> TelegramSettings:
    """Telegram созламалари объектини олиш ёки яратиш"""
    obj, created = TelegramSettings.objects.get_or_create(id=1)
    if not obj.auth_secret:
        obj.auth_secret = uuid.uuid4().hex[:12]
        obj.save(update_fields=['auth_secret'])
    return obj

def generate_qr_base64(data_text: str) -> str:
    """QR кодни Base64 Data URL сурат кўринишида ҳосил қилиш"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data_text)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0088cc", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
    return f"data:image/png;base64,{b64_str}"

def get_telegram_connect_url(settings_obj: TelegramSettings = None, code_override: str = None):
    """
    Telegram бот орқали уланиш ҳаволаси ва QR-код base64 қайтаради.
    Юзернейм @ белгисисиз тозаланади.
    Бот юзернейми бўлмаса тугма фаол бўлмайди ва "Please enter the bot username first" хабари берилади.
    """
    if not settings_obj:
        settings_obj = get_or_create_telegram_settings()

    bot_username = (settings_obj.bot_username or '').strip().lstrip('@')
    secret = code_override or settings_obj.auth_secret or uuid.uuid4().hex[:12]
    unique_code = f"crm_{secret}" if not code_override else code_override

    if not bot_username:
        return TelegramConnectResult(
            connect_url="",
            qr_base64="",
            app_url="",
            has_username=False,
            bot_username="",
            message="Please enter the bot username first"
        )

    # 1. Web link: https://t.me/<bot_username>?start=<unique_code>
    connect_url = f"https://t.me/{bot_username}?start={unique_code}"
    # 2. Mobile link: tg://resolve?domain=<bot_username>&start=<unique_code>
    app_url = f"tg://resolve?domain={bot_username}&start={unique_code}"
    # 3. QR-код айнан шу deep link ни кодлайди
    qr_base64 = generate_qr_base64(connect_url)

    return TelegramConnectResult(
        connect_url=connect_url,
        qr_base64=qr_base64,
        app_url=app_url,
        has_username=True,
        bot_username=bot_username,
        message=""
    )

def check_telegram_updates(settings_obj: TelegramSettings = None) -> dict:
    """
    Telegram getUpdates орқали ботга келган сўнгги хабарларни текшириш.
    Агар фойдаланувчи /start crm_<secret> ёки /start юборган бўлса, унинг chat_id сини улайди.
    """
    if not settings_obj:
        settings_obj = get_or_create_telegram_settings()

    token = (settings_obj.bot_token or '').strip()
    if not token:
        return {
            'success': False, 
            'is_connected': settings_obj.is_connected,
            'error': 'Telegram Bot Token ҳали киритилмаган. Илтимос, @BotFather токенини киритинг ёки тест уланишдан фойдаланинг.'
        }

    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        resp = requests.get(url, timeout=5)
        data = resp.json()

        if not data.get('ok'):
            return {
                'success': False, 
                'is_connected': settings_obj.is_connected,
                'error': data.get('description', 'Telegram API хатолиги')
            }

        updates = data.get('result', [])
        secret = settings_obj.auth_secret

        for upd in reversed(updates):
            msg = upd.get('message') or upd.get('channel_post') or {}
            text = (msg.get('text') or '').strip()
            chat = msg.get('chat') or {}
            chat_id = str(chat.get('id') or '')
            user = msg.get('from') or {}
            user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
            if not user_name:
                user_name = user.get('username') or f"ID: {chat_id}"

            # /start crm_<secret> ёки умумий /start
            if f"crm_{secret}" in text or text.startswith('/start'):
                # Муваффақиятли уланди!
                settings_obj.admin_chat_id = chat_id
                settings_obj.admin_name = f"@{user.get('username', '')} ({user_name})".strip()
                settings_obj.is_connected = True
                settings_obj.connected_at = timezone.now()
                settings_obj.save()

                # Табриклаш хабарини Telegram'га юбориш
                welcome_text = (
                    "🎉 <b>Табриклаймиз!</b>\n\n"
                    "Сизнинг Telegram ҳисобингиз <b>Ўқув Маркази CRM</b> тизимига муваффақиятли уланди!\n\n"
                    "⚡ <i>Энди сайтдан янги мижозлар ва лидлар келиб тушганда сизга шу ерда хабарнома келади.</i>"
                )
                send_telegram_message(token, chat_id, welcome_text)

                return {
                    'success': True,
                    'is_connected': True,
                    'admin_chat_id': chat_id,
                    'admin_name': settings_obj.admin_name,
                    'message': f"Муваффақиятли уланди: {settings_obj.admin_name}"
                }

        return {
            'success': True,
            'is_connected': settings_obj.is_connected,
            'admin_chat_id': settings_obj.admin_chat_id,
            'admin_name': settings_obj.admin_name,
        }
    except Exception as e:
        return {
            'success': False,
            'is_connected': settings_obj.is_connected,
            'error': str(e)
        }

def send_telegram_message(token: str, chat_id: str, text: str, parse_mode: str = 'HTML') -> dict:
    """Telegram бот орқали хабар юбориш"""
    if not token or not chat_id:
        return {'success': False, 'error': 'Bot Token ёки Chat ID мавжуд эмас'}

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }
        resp = requests.post(url, json=payload, timeout=8)
        data = resp.json()
        if data.get('ok'):
            return {'success': True, 'data': data}
        return {'success': False, 'error': data.get('description', 'Telegram хатолиги')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def notify_telegram_new_lead(lead: LeadApplication) -> dict:
    """Янги лид (ариза) тушганда уланган Telegram'га хабарнома юбориш"""
    settings_obj = get_or_create_telegram_settings()
    if not settings_obj.is_connected or not settings_obj.notify_on_new_lead:
        return {'success': False, 'error': 'Telegram хабарнома ўчирилган ёки уланмаган'}

    token = settings_obj.bot_token.strip()
    chat_id = settings_obj.admin_chat_id.strip()

    if not token or not chat_id:
        return {'success': False, 'error': 'Token ёки Chat ID йўқ'}

    course_title = lead.course.title if lead.course else (lead.course_name_custom or 'Умумий курс')
    price = f"{lead.course.price_kzt:,} ₸" if lead.course else "35 000 ₸"
    time_str = lead.created_at.strftime('%d.%m.%Y, %H:%M') if lead.created_at else timezone.now().strftime('%d.%m.%Y, %H:%M')

    msg = (
        "🚀 <b>ЯНГИ АРИЗА КЕЛИБ ТУШДИ!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Мижоз:</b> {lead.name}\n"
        f"📞 <b>Телефон:</b> <code>{lead.phone}</code>\n"
        f"📚 <b>Йўналиш:</b> {course_title}\n"
        f"💰 <b>Нархи:</b> {price}\n"
        f"💬 <b>Изоҳ:</b> {lead.message or 'Изоҳ қолдирилмаган'}\n"
        f"⏰ <b>Вақт (Asia/Almaty):</b> {time_str}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 <a href=\"https://t.me/{lead.phone.replace(' ', '').replace('+', '')}\">Мижоз Telegram'ини очиш</a> | "
        f"<a href=\"https://wa.me/{lead.phone.replace(' ', '').replace('+', '')}\">WhatsApp очиш</a>"
    )

    return send_telegram_message(token, chat_id, msg)


def process_incoming_telegram_message(chat_id: str, text: str, user_name: str = '', username: str = '', phone: str = '') -> LeadApplication:
    """
    Telegram'дан келган мижоз хабарини LeadApplication (Канбан доска)га ёзиш ёки янгилаш.
    Канбан "Новое обращение" колоннасида дарҳол пайдо бўлади!
    """
    chat_id = str(chat_id or '').strip()
    text = str(text or '').strip()
    if not chat_id:
        return None

    # Мавжуд лидни қидириш (telegram_chat_id ёки телефон бўйича)
    lead = LeadApplication.objects.filter(telegram_chat_id=chat_id).first()
    if not lead and phone:
        import re
        clean_p = re.sub(r'\D', '', phone)
        if len(clean_p) >= 9:
            lead = LeadApplication.objects.filter(phone__icontains=clean_p[-9:]).first()
    if not lead and username:
        lead = LeadApplication.objects.filter(phone__iexact=f"@{username}").first()
        if not lead:
            lead = LeadApplication.objects.filter(name__icontains=username).first()

    if lead:
        # Мавжуд лид — хабарни чат лентасига қўшиш ва "Новое обращение"га чиқариш
        prev = lead.message or ''
        lead.message = (prev + '\n\n[TG] ' + text).strip() if prev else f'[TG] {text}'
        lead.status = 'new'
        lead.created_at = timezone.now()
        if not lead.telegram_chat_id:
            lead.telegram_chat_id = chat_id
        if user_name and (lead.name.startswith('+TG') or lead.name.startswith('ID:')):
            lead.name = user_name
        lead.save(update_fields=['message', 'status', 'created_at', 'telegram_chat_id', 'name'])
        print(f"[Telegram Lead Updated] Lead #{lead.id} ({lead.name}) янгиланди: {text[:40]}")
        return lead

    # Янги лид яратиш
    disp_name = user_name.strip() if user_name else (f"@{username}" if username else f"TG: {chat_id}")
    disp_phone = phone if phone else (f"@{username}" if username else f"+TG {chat_id}")

    lead = LeadApplication.objects.create(
        name=disp_name,
        phone=disp_phone,
        telegram_chat_id=chat_id,
        source='telegram',
        status='new',
        message=f"[TG] {text}" if text else "[Telegram орқали янги мурожаат]",
        course_name_custom="",
        manager_name="",
    )
    print(f"[Telegram Lead Created] Янги Lead #{lead.id} яратилди: {disp_name} ({chat_id})")

    # Админга хабарнома юбориш (агар хабар админнинг ўз аккаунтидан келмаган бўлса)
    settings_obj = get_or_create_telegram_settings()
    if settings_obj.admin_chat_id != chat_id:
        try:
            notify_telegram_new_lead(lead)
        except Exception as notify_err:
            print("[Telegram Notify Error]:", notify_err)

    return lead


def process_incoming_telegram_update(upd: dict, settings_obj: TelegramSettings = None) -> dict:
    """
    Битта Telegram Update объектини тўлиқ таҳлил қилиб, лид ва хабарлар тарихига ёзиш.
    Барча турдаги хабарлар: message, edited_message, channel_post, business_message, callback_query
    ва медиалар: расм, овоз, видео, ҳужжат, контакт, стикер, локация қўллаб-қувватланади.
    """
    if not settings_obj:
        settings_obj = get_or_create_telegram_settings()

    # Барча Telegram Update турларини олиш
    msg = (
        upd.get('message') or
        upd.get('edited_message') or
        upd.get('channel_post') or
        upd.get('edited_channel_post') or
        upd.get('business_message') or
        upd.get('edited_business_message') or
        {}
    )
    cb = upd.get('callback_query')
    if not msg and cb:
        msg = cb.get('message') or {}

    if not msg and not cb:
        return {'processed': False, 'reason': 'No recognized message or callback in update'}

    # Юборувчи маълумотлари
    user = (cb.get('from') if cb else None) or msg.get('from') or {}
    user_name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    username = user.get('username') or ''

    # Chat ID аниқлаш
    chat = msg.get('chat') or {}
    chat_id = str(chat.get('id') or (user.get('id') if user else '') or '')

    if not chat_id:
        return {'processed': False, 'reason': 'Chat ID not found'}

    # Матн ва контакт
    text = (msg.get('text') or msg.get('caption') or '').strip()
    if cb and not text:
        text = str(cb.get('data') or '').strip()

    contact = msg.get('contact') or {}
    phone = contact.get('phone_number') or ''

    # Медиа турларини аниқлаш
    media_label = ""
    if msg.get('photo'):
        media_label = "📷 [Расм / Фото]"
    elif msg.get('voice'):
        dur = msg.get('voice', {}).get('duration')
        media_label = f"🎤 [Овозли хабар{f' ({dur}с)' if dur else ''}]"
    elif msg.get('audio'):
        f_name = msg.get('audio', {}).get('file_name', '')
        media_label = f"🎵 [Аудио{f': {f_name}' if f_name else ''}]"
    elif msg.get('document'):
        f_name = msg.get('document', {}).get('file_name', '')
        media_label = f"📄 [Ҳужжат{f': {f_name}' if f_name else ''}]"
    elif msg.get('video'):
        media_label = "🎥 [Видео]"
    elif msg.get('video_note'):
        media_label = "⭕ [Видео хабар (Кружочек)]"
    elif msg.get('sticker'):
        emoji = msg.get('sticker', {}).get('emoji', '')
        media_label = f"🎭 [Стикер{f' {emoji}' if emoji else ''}]"
    elif msg.get('location'):
        loc = msg.get('location', {})
        media_label = f"📍 [Геолокация: {loc.get('latitude')}, {loc.get('longitude')}]"
    elif contact:
        c_name = contact.get('first_name', '')
        media_label = f"📞 [Контакт: {c_name} {phone}]".strip()

    # Кўрсатиладиган умумий матн
    if media_label:
        display_text = f"{media_label} {text}".strip() if text else media_label
    elif phone and not text:
        display_text = f"📞 [Телефон рақам: {phone}]"
    elif text:
        display_text = text
    else:
        display_text = "[Хабар]"

    secret = settings_obj.auth_secret or ''
    teacher_obj = None
    student_obj = None

    # Deep link orqali bog'lash tekshiruvi (/start <param>)
    if text.startswith('/start'):
        parts = text.split()
        param = parts[1] if len(parts) > 1 else ''

        # 1. Ўқитувчини боғлаш (/start teacher_<id>)
        if param.startswith('teacher_'):
            try:
                t_id = int(param.replace('teacher_', ''))
                teacher_obj = Teacher.objects.filter(id=t_id).first()
                if teacher_obj:
                    teacher_obj.telegram_chat_id = chat_id
                    teacher_obj.telegram_username = username
                    teacher_obj.save(update_fields=['telegram_chat_id', 'telegram_username'])
                    if settings_obj.bot_token:
                        send_telegram_message(
                            settings_obj.bot_token, 
                            chat_id, 
                            f"✅ Ҳурматли <b>{teacher_obj.full_name}</b>, сизнинг Telegram ҳисобингиз тизимга ўқитувчи сифатида муваффақиятли уланди!"
                        )
            except Exception as e:
                print("[Telegram Teacher Link Error]:", e)

        # 2. Ўқувчини боғлаш (/start student_<id>)
        elif param.startswith('student_'):
            try:
                s_id = int(param.replace('student_', ''))
                student_obj = Student.objects.filter(id=s_id).first()
                if student_obj:
                    student_obj.telegram_chat_id = chat_id
                    student_obj.telegram_username = username
                    student_obj.save(update_fields=['telegram_chat_id', 'telegram_username'])
                    if settings_obj.bot_token:
                        send_telegram_message(
                            settings_obj.bot_token, 
                            chat_id, 
                            f"✅ Салом <b>{student_obj.full_name}</b>! Сизнинг Telegram ҳисобингиз ўқувчи профилига муваффақиятли уланди."
                        )
            except Exception as e:
                print("[Telegram Student Link Error]:", e)

        # 3. CRM Админ уланиши (/start crm_<secret>)
        elif secret and (f"crm_{secret}" in text or param == f"crm_{secret}"):
            settings_obj.admin_chat_id = chat_id
            settings_obj.admin_name = f"@{username} ({user_name})".strip() if username else user_name
            settings_obj.is_connected = True
            settings_obj.connected_at = timezone.now()
            settings_obj.save()

            welcome_text = (
                "🎉 <b>Табриклаймиз!</b>\n\n"
                "Сизнинг Telegram ҳисобингиз <b>Ўқув Маркази CRM</b> тизимига муваффақиятли уланди!\n\n"
                "⚡ <i>Энди янги лидлар тушганда ёки мижоз ёзганда сизга шу ерда хабар келади.</i>"
            )
            if settings_obj.bot_token:
                send_telegram_message(settings_obj.bot_token, chat_id, welcome_text)

        # 4. Канбан Лидини тўғридан-тўғри боғлаш (/start lead_<id>)
        elif param.startswith('lead_'):
            try:
                l_id = int(param.replace('lead_', ''))
                lead_obj = LeadApplication.objects.filter(id=l_id).first()
                if lead_obj:
                    lead_obj.telegram_chat_id = chat_id
                    if user_name and (lead_obj.name.startswith('+') or lead_obj.name.startswith('TG:')):
                        lead_obj.name = user_name
                    lead_obj.save(update_fields=['telegram_chat_id', 'name'])
                    print(f"[Telegram Lead Linked] Lead #{lead_obj.id} chat_id={chat_id} га муваффақиятли боғланди!")
                    if settings_obj.bot_token:
                        send_telegram_message(
                            settings_obj.bot_token,
                            chat_id,
                            f"👋 Ассалому алайкум <b>{lead_obj.name}</b>!\n\nЎқув марказимизга хуш келибсиз! 🎓 Мурожаатингиз қабул қилинди. Тез орада менежеримиз шу ерда сизга жавоб беради."
                        )
            except Exception as e:
                print("[Telegram Lead Link Error]:", e)

    # Агар мижоз контакт ёки телефон юборган бўлса, шу телефонли барча лидларни chat_id га автоматик боғлаш
    if phone and chat_id:
        import re
        c_digits = re.sub(r'\D', '', phone)
        if len(c_digits) >= 9:
            LeadApplication.objects.filter(
                phone__icontains=c_digits[-9:], 
                telegram_chat_id__in=['', None]
            ).update(telegram_chat_id=chat_id)
            print(f"[Telegram Contact Auto-Link] Phone={phone} -> chat_id={chat_id} га боғланди!")

    # Агар deep link бўлмаса, мавжуд Teacher ёки Student ни chat_id орқали топамиз
    if not teacher_obj:
        teacher_obj = Teacher.objects.filter(telegram_chat_id=chat_id).first()
    if not student_obj:
        student_obj = Student.objects.filter(telegram_chat_id=chat_id).first()

    # ХАБАРНИ telegram_messages ЖАДВАЛИГА САҚЛАШ (Incoming)
    msg_id = msg.get('message_id')
    if msg_id:
        tg_msg, _ = TelegramMessage.objects.get_or_create(
            chat_id=chat_id,
            message_id=msg_id,
            direction='in',
            defaults={
                'sender_name': user_name or (f"@{username}" if username else f"ID: {chat_id}"),
                'sender_username': username,
                'text': display_text,
                'teacher': teacher_obj,
                'student': student_obj,
                'raw_payload': upd,
                'is_read': False,
            }
        )
    else:
        tg_msg = TelegramMessage.objects.create(
            chat_id=chat_id,
            message_id=None,
            sender_name=user_name or (f"@{username}" if username else f"ID: {chat_id}"),
            sender_username=username,
            direction='in',
            text=display_text,
            teacher=teacher_obj,
            student=student_obj,
            raw_payload=upd,
            is_read=False,
        )

    # 4. Агар мижоз оддий /start босган бўлса
    if text == '/start':
        welcome_client = (
            "👋 <b>Ассалому алайкум!</b>\n\n"
            "Ўқув марказимизга хуш келибсиз! 🎓\n"
            "Қайси йўналиш ёки курс сизни қизиқтиради? Саволингизни ёзиб қолдиринг, "
            "менежеримиз тез орада сизга жавоб беради."
        )
        if settings_obj.bot_token:
            send_telegram_message(settings_obj.bot_token, chat_id, welcome_client)

        lead = process_incoming_telegram_message(
            chat_id=chat_id,
            text="/start (Ботга кирди ва суҳбат бошлади)",
            user_name=user_name,
            username=username,
            phone=phone
        )
        return {'processed': True, 'action': 'lead_created', 'lead_id': lead.id if lead else None, 'message_id': tg_msg.id}

    # 5. Барча кирувчи хабарларни (матн, медиа, расм, овоз, контакт) Канбан доскага лид ёзишмаси сифатида узатиш!
    lead = process_incoming_telegram_message(
        chat_id=chat_id,
        text=display_text,
        user_name=user_name,
        username=username,
        phone=phone
    )
    return {
        'processed': True,
        'action': 'lead_updated_or_created',
        'lead_id': lead.id if lead else None,
        'message_id': tg_msg.id,
        'chat_id': chat_id,
        'text': display_text
    }


def fetch_and_process_telegram_updates(settings_obj: TelegramSettings = None) -> int:
    """
    Telegram getUpdates API орқали ботга келган янги хабарларни олиб (Long-polling fallback),
    автоматик тарзда telegram_messages жадвалига ва Канбан доскага (LeadApplication) ёзиш.
    """
    if not settings_obj:
        settings_obj = get_or_create_telegram_settings()

    token = (settings_obj.bot_token or '').strip()
    if not token:
        return 0

    try:
        offset = (settings_obj.last_update_id or 0) + 1
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params = {
            'offset': offset,
            'timeout': 1,
            'limit': 25,
            'allowed_updates': '["message","edited_message","channel_post","edited_channel_post","business_message","edited_business_message","callback_query"]'
        }
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()

        if not data.get('ok'):
            # Агар вебхук фаол бўлганлиги учун 409 Conflict берса, хато чиқармаймиз
            return 0

        updates = data.get('result', [])
        if not updates:
            return 0

        processed_count = 0
        max_update_id = settings_obj.last_update_id or 0

        for upd in updates:
            upd_id = upd.get('update_id', 0)
            if upd_id > max_update_id:
                max_update_id = upd_id

            try:
                res = process_incoming_telegram_update(upd, settings_obj)
                if res.get('processed'):
                    processed_count += 1
            except Exception as upd_err:
                print(f"[Telegram Update {upd_id} Processing Error]:", upd_err)

        if max_update_id > (settings_obj.last_update_id or 0):
            settings_obj.last_update_id = max_update_id
            settings_obj.save(update_fields=['last_update_id'])

        if processed_count > 0:
            print(f"[Telegram Polling] {processed_count} та янги хабар қабул қилиниб базага ёзилди.")

        return processed_count
    except Exception as e:
        print("[Telegram getUpdates Polling Error]:", e)
        return 0


def send_telegram_reply(chat_id: str, text: str) -> dict:
    """
    Админ чат панелидан Telegram фойдаланувчисига тўғридан-тўғри хабар юбориш
    ва telegram_messages жадвалига чиқувчи хабар (direction='out') сифатида ёзиш.
    """
    settings_obj = get_or_create_telegram_settings()
    token = (settings_obj.bot_token or '').strip()
    chat_id = str(chat_id or '').strip()
    text = str(text or '').strip()

    if not chat_id or not text:
        return {'success': False, 'error': 'Chat ID ёки хабар матни киритилмаган'}

    teacher_obj = Teacher.objects.filter(telegram_chat_id=chat_id).first()
    student_obj = Student.objects.filter(telegram_chat_id=chat_id).first()

    sent_msg_id = None
    warning_msg = None
    if token:
        send_res = send_telegram_message(token, chat_id, text, parse_mode='HTML')
        if send_res.get('success'):
            sent_msg_id = (send_res.get('data') or {}).get('result', {}).get('message_id')
        else:
            warning_msg = f"Хабар тизимга сақланди, аммо Telegram API хато қайтарди: {send_res.get('error')}"
    else:
        send_res = {'success': True, 'simulated': True}

    out_msg = TelegramMessage.objects.create(
        chat_id=chat_id,
        message_id=sent_msg_id,
        sender_name="Администратор",
        sender_username="admin",
        direction='out',
        text=text,
        teacher=teacher_obj,
        student=student_obj,
        is_read=True
    )

    # Агар Kanban лид бўлса, унинг лид ёзишмасини ҳам янгилаш
    lead = LeadApplication.objects.filter(telegram_chat_id=chat_id).first()
    if lead:
        prev = lead.message or ''
        lead.message = (prev + '\n\n[TG Вы ответили]: ' + text).strip() if prev else f'[TG Вы ответили]: {text}'
        if lead.status == 'new':
            lead.status = 'contacted'
        lead.save(update_fields=['message', 'status'])

    return {
        'success': True,
        'message_id': out_msg.id,
        'chat_id': chat_id,
        'text': text,
        'timestamp': out_msg.timestamp.strftime('%H:%M'),
        'warning': warning_msg,
        'telegram_status': send_res
    }


def find_chat_id_by_phone(phone: str) -> str:
    """Телефон рақами ёки username бўйича мижознинг мавжуд Telegram Chat ID сини базадан излаш"""
    if not phone:
        return ''
    import re
    from .models import TelegramMessage

    # 0. Агар username берилган бўлса (@username ёки username)
    clean_u = phone.lstrip('@').strip().lower()
    if clean_u:
        msg_u = TelegramMessage.objects.filter(sender_username__iexact=clean_u).exclude(chat_id__in=['', None]).first()
        if msg_u and msg_u.chat_id and not msg_u.chat_id.startswith('+'):
            return msg_u.chat_id

    clean = re.sub(r'\D', '', phone)
    if len(clean) < 9:
        return ''
    last9 = clean[-9:]

    # 1. LeadApplication жадвалидан
    lead = LeadApplication.objects.filter(phone__icontains=last9).exclude(telegram_chat_id__in=['', None]).first()
    if lead and lead.telegram_chat_id and not lead.telegram_chat_id.startswith('+'):
        return lead.telegram_chat_id

    # 2. Student жадвалидан
    st = Student.objects.filter(phone__icontains=last9).exclude(telegram_chat_id__in=['', None]).first()
    if st and st.telegram_chat_id:
        return st.telegram_chat_id

    # 3. Teacher жадвалидан
    tc = Teacher.objects.filter(phone__icontains=last9).exclude(telegram_chat_id__in=['', None]).first()
    if tc and tc.telegram_chat_id:
        return tc.telegram_chat_id

    # 4. TelegramMessage хом payload контактларидан
    try:
        from .models import TelegramMessage
        tg_msgs = TelegramMessage.objects.filter(direction='in').order_by('-timestamp')[:80]
        for m in tg_msgs:
            payload = m.raw_payload or {}
            c_info = (payload.get('message') or {}).get('contact') or {}
            c_num = re.sub(r'\D', '', c_info.get('phone_number') or '')
            if c_num and last9 in c_num and m.chat_id and not m.chat_id.startswith('+'):
                return m.chat_id
    except Exception:
        pass

    return ''


def send_telegram_to_client(phone: str, text: str, lead_id: int = None, chat_id: str = None) -> dict:
    """
    Канбан доскадан мижозга Telegram орқали хабар юбориш:
    1. Агар telegram_chat_id бўлса ёки телефон бўйича базадан топилса — Telegram Bot орқали ТЎҒРИДАН-ТЎҒРИ мижоз чатига етказилади!
    2. Агар мижоз ботга ҳали кирмаган бўлса — хабар CRM тарихига сақланиб, мижознинг шахсий Telegram'ига хабар матни тайёр ҳолда (1-кликда юбориш учун) очилади.
    """
    import re
    import urllib.parse
    settings_obj = get_or_create_telegram_settings()
    token = (settings_obj.bot_token or '').strip()
    bot_username = (settings_obj.bot_username or 'EduCenterKzBot').lstrip('@')

    lead = None
    if lead_id:
        lead = LeadApplication.objects.filter(id=lead_id).first()
    if not lead and phone:
        lead = LeadApplication.objects.filter(phone=phone).first()
        if not lead:
            lead = LeadApplication.objects.filter(telegram_chat_id=phone).first()

    # Chat ID ни аниқлаш
    target_chat_id = (chat_id or (lead.telegram_chat_id if lead else '') or '').strip()

    # Агар chat_id бўлмаса ёки телефон рақами кўринишида бўлса, телефон орқали базадан излаймиз
    effective_phone = phone or (lead.phone if lead else '')
    clean_digits = re.sub(r'\D', '', effective_phone or '')

    if (not target_chat_id or target_chat_id.startswith('+') or target_chat_id == effective_phone) and effective_phone:
        found_id = find_chat_id_by_phone(effective_phone)
        if found_id:
            target_chat_id = found_id
            if lead and not lead.telegram_chat_id:
                lead.telegram_chat_id = found_id
                lead.save(update_fields=['telegram_chat_id'])
                print(f"[Telegram Auto-Link] Лид #{lead.id} учун chat_id={found_id} телефон ({effective_phone}) орқали топилди ва боғланди!")

    # Шахсий Telegram чатига тўғридан-тўғри очиш ва матнни тайёр киритиш ҳаволалари:
    encoded_text = urllib.parse.quote(text)
    direct_telegram_url = f"https://t.me/+{clean_digits}?text={encoded_text}" if clean_digits else ""
    app_telegram_url = f"tg://msg?to=+{clean_digits}&text={encoded_text}" if clean_digits else ""
    bot_invite_url = f"https://t.me/{bot_username}?start=lead_{lead.id}" if lead and bot_username else (f"https://t.me/{bot_username}" if bot_username else "")

    # Агар аниқ Chat ID (ёки @username) мавжуд бўлса — БОТ ОРҚАЛИ ТЎҒРИДАН-ТЎҒРИ ЖЎНАТАМИЗ!
    is_valid_chat_id = target_chat_id and (
        target_chat_id.isdigit() or 
        (target_chat_id.startswith('-') and target_chat_id[1:].isdigit()) or 
        target_chat_id.startswith('@')
    )

    if is_valid_chat_id:
        res = send_telegram_reply(target_chat_id, text)
        telegram_status = res.get('telegram_status') or {}
        api_sent = telegram_status.get('success', False)

        if lead:
            lead.refresh_from_db()
            if lead.status == 'new':
                lead.status = 'contacted'
                lead.save(update_fields=['status'])
            expected_prefix = '[TG Вы ответили]: ' + text
            if expected_prefix not in (lead.message or ''):
                prev = lead.message or ''
                lead.message = (prev + '\n\n' + expected_prefix).strip() if prev else expected_prefix
                lead.save(update_fields=['message'])

        if api_sent:
            return {
                'success': True,
                'ok': True,
                'delivered_via_bot': True,
                'message': '✅ Сообщение успешно отправлено клиенту через Telegram бот!',
                'telegram_url': direct_telegram_url,
                'app_url': app_telegram_url,
                'lead_status_updated': 'contacted',
                'new_message': lead.message if lead else text,
                'chat_id': target_chat_id
            }
        else:
            # Telegram API хато берди (масалан, мижоз ботни ҳали бошламаган бўлса)
            return {
                'success': True,
                'ok': True,
                'delivered_via_bot': False,
                'needs_direct_open': True,
                'message': "Сообщение сохранено в CRM истории диалога.",
                'telegram_url': direct_telegram_url,
                'app_url': app_telegram_url,
                'bot_invite_url': bot_invite_url,
                'lead_status_updated': 'contacted',
                'new_message': lead.message if lead else text,
                'chat_id': target_chat_id
            }

    # Агар мижозда Telegram Chat ID ҳали бўлмаса (сайтдан тушган оддий телефон рақам бўлса):
    if lead:
        prev = lead.message or ''
        expected_prefix = '[TG Вы ответили]: ' + text
        if expected_prefix not in (lead.message or ''):
            lead.message = (prev + '\n\n' + expected_prefix).strip() if prev else expected_prefix
        if lead.status == 'new':
            lead.status = 'contacted'
        lead.save(update_fields=['message', 'status'])

    # telegram_messages жадвалига чиқувчи хабар сифатида сақлаш
    try:
        TelegramMessage.objects.create(
            chat_id=effective_phone or str(lead.id if lead else 'unknown'),
            sender_name="Администратор",
            sender_username="admin",
            direction='out',
            text=text,
            is_read=True
        )
    except Exception:
        pass

    return {
        'success': True,
        'ok': True,
        'delivered_via_bot': False,
        'needs_direct_open': False,
        'message': "Хабар тарихда сақланди. Мижоз Telegram ботга уланганида кўради.",
        'lead_status_updated': 'contacted',
        'new_message': lead.message if lead else text,
        'phone': effective_phone
    }


