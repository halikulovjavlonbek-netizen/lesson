"""
Instagram DM Integration — Meta API (Instagram API with Instagram Login)
======================================================================
Официал Meta API орқали Instagram Direct Message интеграцияси.
WhatsApp интеграцияси билан бир хил тузилмадан фойдаланади.

Мавжуд оқим:
  1. OAuth: /instagram/oauth/redirect/ → Meta authorize → callback → tokens
  2. Webhook: /api/instagram/webhook/ (GET verify + POST events)
  3. Yuborish: /api/instagram/send/ → Graph API sendMessage endpoint
  4. Direct Login: username+parol orqali (instagrapi), 2FA qo'llab-quvvatlanadi
"""

import hashlib
import hmac
import logging
import re
import time
import urllib.parse

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Meta API Constants ────────────────────────────────────────────────────────
GRAPH_API_BASE    = "https://graph.instagram.com/v21.0"
OAUTH_AUTHORIZE   = "https://api.instagram.com/oauth/authorize"
OAUTH_TOKEN_URL   = "https://api.instagram.com/oauth/access_token"
LONG_LIVED_URL    = "https://graph.instagram.com/access_token"
REFRESH_TOKEN_URL = "https://graph.instagram.com/refresh_access_token"

# 24-hour messaging window (seconds)
MESSAGING_WINDOW_SECONDS = 86400


# ── Helper: read settings ─────────────────────────────────────────────────────
def get_instagram_settings():
    """DB'дан InstagramSettings объектини олиш (ёки яратиш)."""
    from .models import InstagramSettings
    obj, _ = InstagramSettings.objects.get_or_create(id=1)
    return obj


def get_app_config() -> dict:
    """
    Муҳит ўзгарувчилари (environment variables) ёки Django settings'дан
    Instagram App конфигурациясини олиш.
    """
    return {
        "app_id":      getattr(settings, "INSTAGRAM_APP_ID",     ""),
        "app_secret":  getattr(settings, "INSTAGRAM_APP_SECRET", ""),
        "verify_token": getattr(settings, "INSTAGRAM_VERIFY_TOKEN", "edu_center_ig_verify_2026"),
        "redirect_uri": getattr(settings, "INSTAGRAM_REDIRECT_URI",  ""),
    }


# ── OAuth Flow ────────────────────────────────────────────────────────────────
def build_oauth_url() -> str:
    """
    Instagram OAuth URL яратиш.
    Фойдаланувчи ушбу URL'га йўналтирилади.
    """
    cfg = get_app_config()
    params = {
        "client_id":     cfg["app_id"],
        "redirect_uri":  cfg["redirect_uri"],
        "scope":         "instagram_business_basic,instagram_business_manage_messages",
        "response_type": "code",
    }
    url = f"{OAUTH_AUTHORIZE}?{urllib.parse.urlencode(params)}"
    logger.info("[Instagram OAuth] Redirect URL яратилди: %s", url[:80] + "...")
    return url


def exchange_code_for_token(code: str) -> dict:
    """
    Авторизация коди → Қисқа умрли токенга айлантириш (POST).
    Сўнг → Узоқ умрли токен (60 кун) олиш.
    """
    cfg = get_app_config()
    logger.info("[Instagram OAuth] Токен алмашиш бошланди (code=%s...)", code[:10])

    # 1. Қисқа умрли токен
    try:
        resp = requests.post(OAUTH_TOKEN_URL, data={
            "client_id":     cfg["app_id"],
            "client_secret": cfg["app_secret"],
            "grant_type":    "authorization_code",
            "redirect_uri":  cfg["redirect_uri"],
            "code":          code,
        }, timeout=10)
        data = resp.json()
        logger.info("[Instagram OAuth] Қисқа токен жавоби: %s", data)
    except Exception as exc:
        logger.error("[Instagram OAuth] Қисқа токен сўровида хатолик: %s", exc)
        return {"success": False, "error": str(exc)}

    if "error_message" in data or "error" in data:
        err = data.get("error_message") or data.get("error", {})
        logger.error("[Instagram OAuth] API хатолиги: %s", err)
        return {"success": False, "error": str(err)}

    short_token = data.get("access_token", "")
    user_id     = str(data.get("user_id", ""))

    if not short_token:
        logger.error("[Instagram OAuth] Токен бўш — жавоб: %s", data)
        return {"success": False, "error": "Токен олинмади. API жавоби: " + str(data)}

    # 2. Узоқ умрли токенга айлантириш
    return exchange_short_to_long_lived(short_token, user_id)


def exchange_short_to_long_lived(short_token: str, user_id: str = "") -> dict:
    """
    Қисқа умрли токен → Узоқ умрли токен (60 кун).
    """
    cfg = get_app_config()
    try:
        resp = requests.get(LONG_LIVED_URL, params={
            "grant_type":        "ig_exchange_token",
            "client_secret":     cfg["app_secret"],
            "access_token":      short_token,
        }, timeout=10)
        data = resp.json()
        logger.info("[Instagram OAuth] Узоқ токен жавоби: %s", {k: v for k, v in data.items() if k != "access_token"})
    except Exception as exc:
        logger.error("[Instagram OAuth] Узоқ токен сўровида хатолик: %s", exc)
        return {"success": False, "error": str(exc)}

    if "error" in data:
        return {"success": False, "error": str(data["error"])}

    long_token   = data.get("access_token", "")
    expires_in   = int(data.get("expires_in", 5183944))  # ~60 кун
    token_type   = data.get("token_type", "bearer")

    if not long_token:
        return {"success": False, "error": "Узоқ умрли токен олинмади: " + str(data)}

    # Аккаунт маълумотларини олиш
    me_info = get_instagram_me(long_token)
    ig_user_id = me_info.get("id", user_id)
    ig_username = me_info.get("username", "")

    # DB'га сақлаш
    ig_settings = get_instagram_settings()
    ig_settings.access_token = long_token
    ig_settings.token_type   = token_type
    ig_settings.ig_user_id   = ig_user_id
    ig_settings.ig_username  = ig_username
    ig_settings.expires_at   = timezone.now() + timezone.timedelta(seconds=expires_in)
    ig_settings.is_connected = True
    ig_settings.connected_at = timezone.now()
    ig_settings.save()

    logger.info("[Instagram OAuth] ✅ Аккаунт боғланди: @%s (ID=%s)", ig_username, ig_user_id)

    # MUHIM: 'messages' webhook subscription'ni yoqish
    try:
        sub_result = subscribe_to_messages(ig_settings)
        logger.info("[Instagram OAuth] Subscription natijasi: %s", sub_result)
    except Exception as sub_exc:
        logger.warning("[Instagram OAuth] Subscription xatosi (kritik emas): %s", sub_exc)

    return {
        "success":    True,
        "ig_user_id": ig_user_id,
        "ig_username": ig_username,
        "expires_in": expires_in,
    }


def refresh_long_lived_token(ig_settings=None) -> dict:
    """
    Узоқ умрли токенни янгилаш (срок бошланишидан ≥10 кун ўтган бўлса).
    Cron job учун мўлжалланган.
    """
    if ig_settings is None:
        ig_settings = get_instagram_settings()

    token = ig_settings.access_token
    if not token:
        return {"success": False, "error": "Токен мавжуд эмас"}

    logger.info("[Instagram Token Refresh] Токен янгилаш бошланди...")
    try:
        resp = requests.get(REFRESH_TOKEN_URL, params={
            "grant_type":   "ig_refresh_token",
            "access_token": token,
        }, timeout=10)
        data = resp.json()
    except Exception as exc:
        logger.error("[Instagram Token Refresh] Хатолик: %s", exc)
        return {"success": False, "error": str(exc)}

    if "error" in data:
        return {"success": False, "error": str(data["error"])}

    new_token  = data.get("access_token", "")
    expires_in = int(data.get("expires_in", 5183944))

    if not new_token:
        return {"success": False, "error": "Янги токен олинмади"}

    ig_settings.access_token = new_token
    ig_settings.expires_at   = timezone.now() + timezone.timedelta(seconds=expires_in)
    ig_settings.save(update_fields=["access_token", "expires_at"])
    logger.info("[Instagram Token Refresh] ✅ Токен янгиланди, срок: %s кун", expires_in // 86400)
    return {"success": True, "expires_in": expires_in}


def get_instagram_me(access_token: str) -> dict:
    """Аккаунт маълумотларини Graph API'дан олиш."""
    try:
        resp = requests.get(f"{GRAPH_API_BASE}/me", params={
            "fields":       "id,username,name",
            "access_token": access_token,
        }, timeout=8)
        return resp.json()
    except Exception as exc:
        logger.warning("[Instagram Me] Хатолик: %s", exc)
        return {}


# ── Webhook Signature Verification ───────────────────────────────────────────
def verify_webhook_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    X-Hub-Signature-256 заголовкасини HMAC-SHA256 орқали текшириш.
    MUHIM: raw body (parse qilinmagan) bilan tekshiriladi!
    """
    cfg = get_app_config()
    app_secret = cfg["app_secret"]
    if not app_secret:
        logger.warning("[Instagram Webhook] App Secret ko'rsatilmagan — imzo tekshirilmadi!")
        return True  # Dev mode fallback

    if not signature_header or not signature_header.startswith("sha256="):
        logger.warning("[Instagram Webhook] X-Hub-Signature-256 header yo'q yoki noto'g'ri format")
        return False

    # HMAC-SHA256 hisoblash (raw bytes ustida)
    mac = hmac.new(
        app_secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    )
    expected_sig = "sha256=" + mac.hexdigest()
    result = hmac.compare_digest(expected_sig, signature_header)
    if not result:
        logger.warning("[Instagram Webhook] Imzo mos kelmadi! expected=%s..., got=%s...",
                       expected_sig[:20], signature_header[:20])
    return result


# ── Subscriptions ─────────────────────────────────────────────────────────────
def subscribe_to_messages(ig_settings=None) -> dict:
    """
    POST /{ig-user-id}/subscribed_apps?subscribed_fields=messages
    Bu Instagram'ga: 'Menga DM xabarlarini webhook orqali yubor' deb aytadi.
    OAuth'dan keyin MAJBURIY chaqirilishi kerak!
    """
    if ig_settings is None:
        ig_settings = get_instagram_settings()

    token = ig_settings.access_token or ""
    user_id = ig_settings.ig_user_id or ""

    if not token or not user_id or token.startswith("SESSION:"):
        return {"success": False, "error": "Token yoki user_id yo'q (yoki SESSION token)"}

    url = f"{GRAPH_API_BASE}/{user_id}/subscribed_apps"
    try:
        resp = requests.post(url, params={
            "subscribed_fields": "messages",
            "access_token": token,
        }, timeout=10)
        data = resp.json()
        logger.info("[Instagram Subscribe] subscribed_apps javobi: %s", data)
    except Exception as exc:
        logger.error("[Instagram Subscribe] Tarmoq xatosi: %s", exc)
        return {"success": False, "error": str(exc)}

    if data.get("success") or data.get("id"):
        logger.info("[Instagram Subscribe] ✅ 'messages' ga obuna bo'lindi!")
        return {"success": True, "data": data}
    else:
        err = data.get("error", data)
        logger.error("[Instagram Subscribe] Xatolik: %s", err)
        return {"success": False, "error": str(err), "raw": data}


def check_webhook_subscription(ig_settings=None) -> dict:
    """
    GET /{ig-user-id}/subscribed_apps — webhook obuna holatini tekshirish.
    Dashboard UI uchun 'Webhook ulanган/ulanmagan' ko'rsatadi.
    """
    if ig_settings is None:
        ig_settings = get_instagram_settings()

    token = ig_settings.access_token or ""
    user_id = ig_settings.ig_user_id or ""

    if not token or not user_id or token.startswith("SESSION:"):
        return {"subscribed": False, "reason": "no_token"}

    url = f"{GRAPH_API_BASE}/{user_id}/subscribed_apps"
    try:
        resp = requests.get(url, params={"access_token": token}, timeout=8)
        data = resp.json()
        logger.info("[Instagram Subscribe Check] %s", data)
    except Exception as exc:
        logger.warning("[Instagram Subscribe Check] Xatolik: %s", exc)
        return {"subscribed": False, "error": str(exc)}

    apps = data.get("data", [])
    subscribed_fields = []
    for app in apps:
        subscribed_fields.extend(app.get("subscribed_fields", []))

    is_subscribed = "messages" in subscribed_fields
    return {
        "subscribed": is_subscribed,
        "fields": subscribed_fields,
        "apps": apps,
    }


# ── Webhook Event Parser ──────────────────────────────────────────────────────
def process_instagram_webhook(payload: dict) -> dict:
    """
    Instagram webhook update'ни ишлаш ва InstagramMessage'га сақлаш.
    """
    from .models import InstagramMessage, LeadApplication

    obj_type = payload.get("object", "")
    if obj_type not in ("instagram", "page"):
        logger.info("[Instagram Webhook] Ўтказиб юборилди (object=%s)", obj_type)
        return {"skipped": True, "reason": f"object={obj_type}"}

    processed = 0
    errors = []

    for entry in payload.get("entry", []):
        messaging_events = entry.get("messaging", [])
        for event in messaging_events:
            try:
                _handle_messaging_event(event)
                processed += 1
            except Exception as exc:
                logger.error("[Instagram Webhook] Event ишлашда хатолик: %s | event=%s", exc, event)
                errors.append(str(exc))

        # Instagram post / reels коментариялари (Webhook changes)
        changes_events = entry.get("changes", [])
        for change in changes_events:
            try:
                _handle_comment_change_event(change)
                processed += 1
            except Exception as exc:
                logger.error("[Instagram Webhook] Change event ишлашда хатолик: %s | change=%s", exc, change)
                errors.append(str(exc))

    logger.info("[Instagram Webhook] Ишланди: %d ta event, %d ta хатолик", processed, len(errors))
    return {"processed": processed, "errors": errors}


def _handle_messaging_event(event: dict):
    """Битта messaging event'ни DB'га сақлаш."""
    from .models import InstagramMessage, LeadApplication

    sender_id    = event.get("sender", {}).get("id", "")
    recipient_id = event.get("recipient", {}).get("id", "")
    timestamp_ms = event.get("timestamp", 0)

    msg_obj = event.get("message", {})
    if not msg_obj:
        logger.debug("[Instagram Webhook] Non-message event, sender=%s", sender_id)
        return

    # Echo (бизнинг ўзимиздан чиқган хабар)
    is_echo = msg_obj.get("is_echo", False)
    if is_echo:
        logger.debug("[Instagram Webhook] Echo хабар ўтказиб юборилди")
        return

    mid          = msg_obj.get("mid", "")
    text         = msg_obj.get("text", "")
    attachments  = msg_obj.get("attachments", [])
    reply_to     = msg_obj.get("reply_to", {})
    story        = msg_obj.get("story", {})  # story reply

    # Attachment'лар учун таврифли матн
    attach_label = ""
    if attachments:
        types = [a.get("type", "file") for a in attachments]
        attach_label = " | ".join(f"[{t.upper()}]" for t in types)
        if text:
            attach_label = text + " " + attach_label
        else:
            attach_label = attach_label or "[медиа файл]"

    if story:
        story_url = story.get("url", "")
        attach_label = (attach_label or text or "") + f" [Story Reply: {story_url[:60]}]"

    display_text = attach_label or text or "[хабар матнсиз]"

    # IGSID орқали мавжуд лидни топиш ёки янги яратиш
    lead = LeadApplication.objects.filter(instagram_igsid=sender_id).first()
    if not lead:
        lead = LeadApplication.objects.create(
            name=f"Instagram:{sender_id[:12]}",
            phone="",
            source="instagram",
            status="new",
            instagram_igsid=sender_id,
            message=f"[Instagram DM]: {display_text}",
        )
        logger.info("[Instagram Webhook] ✅ Янги лид яратилди: ID=%s, IGSID=%s", lead.id, sender_id)
    else:
        prev = lead.message or ""
        new_entry = f"[Instagram DM]: {display_text}"
        if new_entry not in (lead.message or ""):
            lead.message = (prev + "\n\n" + new_entry).strip() if prev else new_entry
        if lead.status == "contacted":
            lead.status = "new"
        lead.save(update_fields=["message", "status"])

    # InstagramMessage жадвалига сақлаш (duplicate guard)
    if mid:
        _, created = InstagramMessage.objects.get_or_create(
            message_id=mid,
            defaults={
                "sender_igsid":    sender_id,
                "recipient_igsid": recipient_id,
                "direction":       "in",
                "text":            display_text,
                "raw_payload":     event,
                "timestamp_ms":    timestamp_ms,
                "lead":            lead,
            },
        )
        if created:
            logger.info("[Instagram Webhook] Хабар сақланди: mid=%s", mid)
    else:
        InstagramMessage.objects.create(
            sender_igsid=sender_id,
            recipient_igsid=recipient_id,
            direction="in",
            text=display_text,
            raw_payload=event,
            timestamp_ms=timestamp_ms,
            lead=lead,
        )

    # Telegram'га янги хабар тушганлиги ҳақида хабарнома
    try:
        from .telegram import notify_telegram_new_lead
        from .models import TelegramSettings
        tg_s = TelegramSettings.objects.first()
        if tg_s and tg_s.notify_on_new_lead and lead.status == "new":
            if lead.created_at and (timezone.now() - lead.created_at).seconds < 30:
                notify_telegram_new_lead(lead)
    except Exception as exc:
        logger.warning("[Instagram Webhook] TG хабарнома хатолиги: %s", exc)


def _handle_comment_change_event(change: dict):
    """Instagram post / reels коментариясини Webhook орқали сақлаш."""
    from .models import InstagramComment, InstagramMessage, LeadApplication

    field = change.get("field", "")
    if field != "comments":
        return

    val = change.get("value", {})
    comment_id = str(val.get("id", "")).strip()
    comment_text = str(val.get("text", "")).strip()
    from_user = val.get("from", {})
    commenter_id = str(from_user.get("id", "")).strip()
    commenter_username = str(from_user.get("username", "")).strip() or f"user_{commenter_id[:6]}"
    media_obj = val.get("media", {})
    media_id = str(media_obj.get("id", "")).strip()
    media_type = media_obj.get("media_product_type", "POST/REELS")

    if not comment_id or not comment_text:
        return

    if InstagramComment.objects.filter(comment_id=comment_id).exists():
        return

    lead = None
    if commenter_id:
        lead = LeadApplication.objects.filter(instagram_igsid=commenter_id).first()
    if not lead and commenter_username:
        lead = LeadApplication.objects.filter(instagram_igsid=commenter_username).first()

    raw_text = f"💬 [Instagram Коментария - {media_type}]: {comment_text}"

    if not lead:
        lead = LeadApplication.objects.create(
            name=f"@{commenter_username}",
            phone="",
            source="instagram",
            instagram_igsid=commenter_id or commenter_username,
            message=raw_text,
            status="new",
            course_name_custom=f"Instagram {media_type}",
        )
        logger.info("[Instagram Webhook Comment] Янги лид: ID=%s (@%s)", lead.id, commenter_username)
    else:
        prev = lead.message or ""
        if raw_text not in prev:
            lead.message = (prev + "\n\n" + raw_text).strip() if prev else raw_text
        if lead.status in ("contacted", "waiting", "cancelled"):
            lead.status = "new"
        if not lead.instagram_igsid and commenter_id:
            lead.instagram_igsid = commenter_id
        lead.save(update_fields=["message", "status", "instagram_igsid"])

    InstagramComment.objects.create(
        comment_id=comment_id,
        post_id=media_id,
        post_url="",
        commenter_username=commenter_username,
        commenter_igsid=commenter_id,
        text=comment_text,
        lead=lead,
        is_read=False,
        raw_payload=val,
    )

    InstagramMessage.objects.create(
        lead=lead,
        sender_igsid=commenter_id or commenter_username,
        recipient_igsid="",
        direction="in",
        text=raw_text,
        message_id=f"comment_{comment_id}",
        raw_payload=val,
        timestamp_ms=int(time.time() * 1000),
    )
    logger.info("[Instagram Webhook Comment] Сақланди: @%s: %s", commenter_username, comment_text[:35])


# ── Sending Replies ───────────────────────────────────────────────────────────
def send_instagram_reply(recipient_igsid: str, text: str) -> dict:
    """
    Instagram Messaging API орқали мижозга жавоб юбориш.
    24-соатлик ойнани ҳурмат қилади.
    """
    from .models import InstagramSettings, InstagramMessage

    ig_settings = get_instagram_settings()
    token = ig_settings.access_token or ""

    if not token:
        logger.error("[Instagram Send] Access token мавжуд эмас!")
        return {"success": False, "error": "Instagram аккаунт боғланмаган. Аввал OAuth орқали уланинг."}

    if not ig_settings.is_connected:
        return {"success": False, "error": "Instagram ҳисоб уланмаган."}

    # 1. Агар instagrapi sessiya (username + parol) бўлса
    if token.startswith("SESSION:"):
        cl = get_authenticated_client()
        if not cl:
            return {"success": False, "error": "Instagram sessiyasi topilmadi yoki eskirgan"}
        try:
            uid = int(recipient_igsid) if recipient_igsid.isdigit() else None
            if not uid:
                uid = cl.user_id_from_username(recipient_igsid.lstrip("@"))

            sent = cl.direct_send(text, user_ids=[uid])
            mid = str(getattr(sent, "id", "")) or f"mid_{int(time.time())}"
            InstagramMessage.objects.create(
                sender_igsid=str(cl.user_id or ""),
                recipient_igsid=str(uid),
                direction="out",
                text=text,
                message_id=mid,
                timestamp_ms=int(time.time() * 1000),
            )
            return {"success": True, "message_id": mid}
        except Exception as exc:
            logger.error("[Instagram Send Session] direct_send xatosi: %s", exc)
            return {"success": False, "error": f"Instagram xabari yuborilmadi: {exc}"}

    # 2. Meta OAuth API (Graph API)
    # 24-соатлик ойнани текшириш
    last_inbound = InstagramMessage.objects.filter(
        sender_igsid=recipient_igsid,
        direction="in",
    ).order_by("-timestamp_ms").first()

    if last_inbound:
        elapsed_sec = time.time() - (last_inbound.timestamp_ms / 1000)
        if elapsed_sec > MESSAGING_WINDOW_SECONDS:
            hrs = int(elapsed_sec // 3600)
            return {
                "success": False,
                "error": (
                    f"❌ 24-соатлик хабарлашув ойнаси ёпилган. "
                    f"Мижоз охирги хабар ёзганидан {hrs} соат ўтди. "
                    f"Instagram'да фақат мижоз хабар ёзгандан кейин 24 соат ичида жавоб бериш мумкин."
                ),
                "window_expired": True,
            }
    else:
        return {
            "success": False,
            "error": "❌ Мижоздан ҳали ҳеч қандай хабар олинмаган. Instagram'да фақат мижоз биринчи ёзгандан кейин жавоб бериш мумкин (24 соатлик ойна).",
            "window_expired": True,
        }

    # Хабар юбориш
    page_id = ig_settings.ig_user_id or ""
    url = f"{GRAPH_API_BASE}/{page_id}/messages"
    payload = {
        "recipient": {"id": recipient_igsid},
        "message":   {"text": text},
        "messaging_type": "RESPONSE",
    }
    params = {"access_token": token}

    logger.info("[Instagram Send] %s га хабар юборилмоқда: %s...", recipient_igsid, text[:40])
    try:
        resp = requests.post(url, json=payload, params=params, timeout=10)
        data = resp.json()
    except Exception as exc:
        logger.error("[Instagram Send] Network хатолиги: %s", exc)
        return {"success": False, "error": f"Тармоқ хатоси: {exc}"}

    if resp.status_code != 200 or "error" in data:
        err = data.get("error", {})
        err_msg = err.get("message", str(data)) if isinstance(err, dict) else str(err)
        logger.error("[Instagram Send] API хатолиги: %s", err_msg)
        return {"success": False, "error": err_msg}

    mid = data.get("message_id", "")
    logger.info("[Instagram Send] ✅ Хабар юборилди: mid=%s", mid)

    # Чиқувчи хабарни DB'га сақлаш
    try:
        InstagramMessage.objects.create(
            sender_igsid=page_id,
            recipient_igsid=recipient_igsid,
            direction="out",
            text=text,
            message_id=mid,
            raw_payload={"sent": True, "mid": mid},
            timestamp_ms=int(time.time() * 1000),
        )
    except Exception as exc:
        logger.warning("[Instagram Send] DB сақлашда хатолик: %s", exc)

    return {"success": True, "message_id": mid}


# ── Account Status ────────────────────────────────────────────────────────────
def get_instagram_status() -> dict:
    """Instagram integratsiyasi holati (dashboard uchun)."""
    ig = get_instagram_settings()
    cfg = get_app_config()

    connected = ig.is_connected and bool(ig.access_token)
    expires_at = ig.expires_at

    days_left = None
    if expires_at:
        delta = expires_at - timezone.now()
        days_left = max(0, delta.days)

    # SESSION token => instagrapi, Meta webhook yo'q
    is_session_mode = bool(ig.access_token and ig.access_token.startswith("SESSION:"))

    # So'nggi kiruvchi xabar vaqti
    last_webhook_time = None
    last_webhook_ago = None
    try:
        from .models import InstagramMessage
        last_in = InstagramMessage.objects.filter(direction='in').order_by('-timestamp').first()
        if last_in:
            last_webhook_time = last_in.timestamp.strftime('%d.%m.%Y %H:%M')
            delta_sec = (timezone.now() - last_in.timestamp).total_seconds()
            if delta_sec < 60:
                last_webhook_ago = "Hozirgina"
            elif delta_sec < 3600:
                last_webhook_ago = f"{int(delta_sec // 60)} daqiqa oldin"
            elif delta_sec < 86400:
                last_webhook_ago = f"{int(delta_sec // 3600)} soat oldin"
            else:
                last_webhook_ago = f"{int(delta_sec // 86400)} kun oldin"
    except Exception:
        pass

    return {
        "is_connected":      connected,
        "ig_username":       ig.ig_username,
        "ig_user_id":        ig.ig_user_id,
        "connected_at":      ig.connected_at.isoformat() if ig.connected_at else None,
        "expires_at":        expires_at.isoformat() if expires_at else None,
        "days_left":         days_left,
        "app_id":            cfg["app_id"],
        "redirect_uri":      cfg["redirect_uri"],
        "has_app_secret":    bool(cfg["app_secret"]),
        "full_name":         ig.full_name,
        "profile_pic_url":   ig.profile_pic_url,
        "followers_count":   ig.followers_count,
        "following_count":   ig.following_count,
        "media_count":       ig.media_count,
        "bio":               ig.bio,
        "is_session_mode":   is_session_mode,
        "last_webhook_time": last_webhook_time,
        "last_webhook_ago":  last_webhook_ago,
        "verify_token":      ig.verify_token or cfg.get("verify_token") or "edu_center_ig_verify_2026",
    }


def fetch_conversations_via_api(ig_settings=None) -> dict:
    """
    GET /{ig-user-id}/conversations?platform=instagram&fields=messages{...}
    Webhook ishlamagan yoki tekshirish uchun qo'lda DM xabarlarini tortib olish.
    'Xabarlarni tekshirish (Kanban)' tugmasi uchun Graph API fallback.
    """
    if ig_settings is None:
        ig_settings = get_instagram_settings()

    token = ig_settings.access_token or ""
    user_id = ig_settings.ig_user_id or ""

    if not token or not user_id or token.startswith("SESSION:"):
        return {"success": False, "error": "Meta OAuth token yo'q", "use_polling": True}

    from .models import InstagramMessage, LeadApplication

    url = f"{GRAPH_API_BASE}/{user_id}/conversations"
    params = {
        "platform": "instagram",
        "fields": "id,messages{id,message,from,created_time}",
        "access_token": token,
    }

    logger.info("[Instagram Conversations] GET %s", url)
    try:
        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()
    except Exception as exc:
        logger.error("[Instagram Conversations] Tarmoq xatosi: %s", exc)
        return {"success": False, "error": str(exc)}

    if "error" in data:
        err = data["error"]
        err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        logger.error("[Instagram Conversations] API xatosi: %s | %s", err_msg, data)
        return {"success": False, "error": err_msg, "raw": data}

    convs = data.get("data", [])
    new_messages = 0
    new_leads = 0

    for conv in convs:
        conv_id = conv.get("id", "")
        messages_data = conv.get("messages", {}).get("data", [])

        for msg_item in messages_data:
            msg_id = msg_item.get("id", "")
            msg_text = (msg_item.get("message", "") or "").strip()
            from_obj = msg_item.get("from", {})
            from_id = str(from_obj.get("id", ""))
            from_name = from_obj.get("name", "") or from_obj.get("username", "") or ""
            created_time = msg_item.get("created_time", "")

            # O'zimiz yuborgan xabarlarni o'tkazib yuboramiz
            if from_id == user_id:
                continue

            # Duplicate guard
            if msg_id and InstagramMessage.objects.filter(message_id=msg_id).exists():
                continue

            if not msg_text:
                msg_text = "[Mediya fayl]"

            # LeadApplication topish yoki yaratish
            lead = LeadApplication.objects.filter(instagram_igsid=from_id).first()
            lead_name = from_name or f"Instagram:{from_id[:12]}"

            if not lead:
                lead = LeadApplication.objects.create(
                    name=lead_name,
                    phone="",
                    source="instagram",
                    status="new",
                    instagram_igsid=from_id,
                    message=f"[Instagram DM]: {msg_text}",
                )
                new_leads += 1
                logger.info("[Instagram Conv] ✅ Yangi lead yaratildi: ID=%s (%s)", lead.id, lead_name)
            else:
                prev = lead.message or ""
                entry = f"[Instagram DM]: {msg_text}"
                if entry not in prev:
                    lead.message = (prev + "\n\n" + entry).strip() if prev else entry
                    if lead.status in ("contacted", "waiting"):
                        lead.status = "new"
                    if not lead.instagram_igsid:
                        lead.instagram_igsid = from_id
                    lead.save(update_fields=["message", "status", "instagram_igsid"])

            # InstagramMessage ga saqlash
            try:
                from datetime import datetime as _dt
                ts = _dt.fromisoformat(created_time.replace("Z", "+00:00")).timestamp() if created_time else time.time()
                ts_ms = int(ts * 1000)
            except Exception:
                ts_ms = int(time.time() * 1000)

            InstagramMessage.objects.create(
                lead=lead,
                sender_igsid=from_id,
                recipient_igsid=user_id,
                direction="in",
                text=msg_text,
                message_id=msg_id or None,
                raw_payload={"conv_id": conv_id, "from": from_obj},
                timestamp_ms=ts_ms,
            )
            new_messages += 1

    logger.info("[Instagram Conversations] Yakunlandi: %d yangi xabar, %d yangi lead", new_messages, new_leads)
    return {
        "success": True,
        "new_messages": new_messages,
        "new_leads": new_leads,
        "conversations_checked": len(convs),
    }


def disconnect_instagram() -> dict:
    """Instagram аккаунтини узиш (токенни ўчириш)."""
    ig = get_instagram_settings()
    ig.access_token  = ""
    ig.ig_user_id    = ""
    ig.ig_username   = ""
    ig.is_connected  = False
    ig.connected_at  = None
    ig.expires_at    = None
    ig.save()
    logger.info("[Instagram] Аккаунт улуги олиб ташланди.")
    return {"success": True}


# ── Direct Login (Username + Password via instagrapi) ─────────────────────────
def _save_logged_in_client(cl, username: str) -> dict:
    """Muvaffaqiyatli kirgan instagrapi client'ni DB'ga saqlash."""
    import json as _json

    try:
        user_info = cl.account_info()
        ig_user_id = str(user_info.pk)
        ig_username = user_info.username or username
    except Exception as exc:
        logger.warning("[Instagram Login] account_info xatosi: %s", exc)
        ig_user_id = str(cl.user_id or "")
        ig_username = username

    try:
        session_json = cl.get_settings()
    except Exception:
        session_json = {}

    session_str = _json.dumps(session_json, ensure_ascii=False)

    ig_settings = get_instagram_settings()
    ig_settings.ig_user_id   = ig_user_id
    ig_settings.ig_username  = ig_username
    ig_settings.is_connected = True
    ig_settings.connected_at = timezone.now()
    ig_settings.access_token = "SESSION:" + session_str
    ig_settings.expires_at   = timezone.now() + timezone.timedelta(days=90)
    ig_settings.token_type   = "session"

    # Профиль маълумотлари (статистика)
    try:
        if 'user_info' in locals() and user_info:
            if hasattr(user_info, 'full_name') and user_info.full_name:
                ig_settings.full_name = user_info.full_name
            if hasattr(user_info, 'profile_pic_url') and user_info.profile_pic_url:
                ig_settings.profile_pic_url = str(user_info.profile_pic_url)
            if hasattr(user_info, 'follower_count') and user_info.follower_count is not None:
                ig_settings.followers_count = int(user_info.follower_count)
            if hasattr(user_info, 'following_count') and user_info.following_count is not None:
                ig_settings.following_count = int(user_info.following_count)
            if hasattr(user_info, 'media_count') and user_info.media_count is not None:
                ig_settings.media_count = int(user_info.media_count)
    except Exception as exc:
        logger.warning("[Instagram Login] Profil statistikasini olishda xatolik: %s", exc)

    ig_settings.save()

    logger.info("[Instagram Login] ✅ Muvaffaqiyatli kirdi: @%s (ID=%s)", ig_username, ig_user_id)
    return {
        "success": True,
        "ig_username": ig_username,
        "ig_user_id": ig_user_id,
    }


def login_with_credentials(username: str, password: str) -> dict:
    """
    Instagram'ga username va parol orqali to'g'ridan-to'g'ri kirish.
    2FA talab qilinsa — two_factor_required: True va extra ma'lumotlar qaytariladi.
    """
    try:
        from instagrapi import Client
        from instagrapi.exceptions import (
            LoginRequired, ChallengeRequired, TwoFactorRequired,
            BadPassword, UserNotFound, ClientError,
        )
    except ImportError:
        return {"success": False, "error": "instagrapi o'rnatilmagan. 'pip install instagrapi'"}

    username = username.strip().lstrip("@")
    password = password.strip()

    if not username or not password:
        return {"success": False, "error": "Username va parol bo'sh bo'lmasligi kerak."}

    logger.info("[Instagram Login] Kirish urinishi: @%s", username)

    cl = Client()
    cl.delay_range = [1, 3]

    try:
        cl.login(username, password)

    except TwoFactorRequired as exc:
        logger.warning("[Instagram Login] 2FA talab qilinadi: @%s", username)

        # two_factor_identifier ni ajratib olamiz
        two_factor_identifier = ""
        try:
            info = getattr(exc, "two_factor_info", None) or {}
            two_factor_identifier = info.get("two_factor_identifier", "") if isinstance(info, dict) else ""
        except Exception:
            pass

        # Client settings'ni saqlash (keyingi so'rov uchun)
        try:
            import json as _j
            cl_settings_str = _j.dumps(cl.get_settings(), ensure_ascii=False)
        except Exception:
            cl_settings_str = "{}"

        return {
            "success": False,
            "error": "Ikki bosqichli tasdiqlash (2FA) yoqilgan. Kod kiriting.",
            "two_factor_required": True,
            "two_factor_identifier": two_factor_identifier,
            "cl_settings": cl_settings_str,
            "username": username,
            "password": password,
        }

    except BadPassword:
        return {"success": False, "error": "Parol noto'g'ri. Iltimos, qayta tekshiring."}

    except ChallengeRequired:
        return {
            "success": False,
            "error": "Instagram xavfsizlik tekshiruvi talab qilmoqda (challenge). Instagram ilovasidan tasdiqlang.",
            "challenge_required": True,
        }

    except LoginRequired:
        return {"success": False, "error": "Kirish muvaffaqiyatsiz. Username yoki parolni tekshiring."}

    except UserNotFound:
        return {"success": False, "error": f"@{username} foydalanuvchisi topilmadi."}

    except ClientError as exc:
        return {"success": False, "error": f"Instagram xatosi: {exc}"}

    except Exception as exc:
        logger.error("[Instagram Login] Kutilmagan xatolik: %s", exc)
        return {"success": False, "error": f"Kutilmagan xatolik: {exc}"}

    return _save_logged_in_client(cl, username)


def verify_two_factor_code(username: str, password: str, code: str,
                            two_factor_identifier: str = "",
                            cl_settings_str: str = "{}") -> dict:
    """
    2FA kodni tekshirish va Instagram'ga kirish.
    login_with_credentials() two_factor_required qaytarganidan keyin chaqiriladi.

    Args:
        username: Instagram username
        password: Instagram parol
        code: WhatsApp/SMS/Email dan kelgan 6 xonali kod
        two_factor_identifier: login_with_credentials() qaytargan identifier
        cl_settings_str: login_with_credentials() qaytargan client settings JSON
    """
    try:
        from instagrapi import Client
        from instagrapi.exceptions import (
            TwoFactorRequired, BadPassword, ClientError, ChallengeRequired,
        )
    except ImportError:
        return {"success": False, "error": "instagrapi o'rnatilmagan."}

    import json as _json

    code = code.strip().replace(" ", "").replace("-", "")
    if not code:
        return {"success": False, "error": "Tasdiqlash kodi bo'sh bo'lmasligi kerak."}

    if len(code) < 4:
        return {"success": False, "error": "Kod juda qisqa. Iltimos, to'liq kodni kiriting."}

    username = username.strip().lstrip("@")

    # Avvalgi client settings'ni tiklaymiz
    cl = Client()
    cl.delay_range = [1, 3]
    try:
        if cl_settings_str and cl_settings_str not in ("{}", ""):
            saved = _json.loads(cl_settings_str)
            cl.set_settings(saved)
    except Exception as exc:
        logger.warning("[2FA] Client settings tiklanmadi: %s", exc)

    # 2FA kod bilan kirish
    try:
        cl.login(username, password, verification_code=code)

    except TwoFactorRequired:
        return {"success": False, "error": "Kod noto'g'ri yoki eskirgan. Qayta urinib ko'ring."}

    except BadPassword:
        return {"success": False, "error": "Parol noto'g'ri."}

    except ChallengeRequired:
        return {
            "success": False,
            "error": "Instagram challenge talab qilmoqda. Instagram ilovasidan tasdiqlang.",
            "challenge_required": True,
        }

    except ClientError as exc:
        msg = str(exc)
        logger.error("[2FA] ClientError: %s", msg)
        if any(kw in msg.lower() for kw in ("two factor", "2fa", "verification", "invalid", "wrong")):
            return {"success": False, "error": f"Kod noto'g'ri yoki eskirgan: {msg}"}
        return {"success": False, "error": f"Instagram xatosi: {msg}"}

    except Exception as exc:
        logger.error("[2FA] Kutilmagan xatolik: %s", exc)
        return {"success": False, "error": f"Xatolik: {exc}"}

    return _save_logged_in_client(cl, username)


# ── Instagrapi Session & Direct Messages Polling (Kanban) ────────────────────
def get_authenticated_client():
    """
    DB'dagi saqlangan session orqali instagrapi Client obyektini tiklash.
    """
    ig_settings = get_instagram_settings()
    if not ig_settings.is_connected or not ig_settings.access_token:
        return None
    if not ig_settings.access_token.startswith("SESSION:"):
        return None

    session_str = ig_settings.access_token[len("SESSION:"):]
    try:
        import json as _json
        from instagrapi import Client
        saved = _json.loads(session_str)
        cl = Client()
        cl.delay_range = [1, 2]
        cl.set_settings(saved)
        return cl
    except Exception as exc:
        logger.error("[Instagram] Client session tiklashda xatolik: %s", exc)
        return None


_last_instagram_poll_time = 0
POLL_INTERVAL_SECONDS = 12  # Instagram rate-limit'ga tushmaslik uchun oraliq


def fetch_and_process_instagram_messages(force: bool = False) -> dict:
    """
    Instagram Direct (DM) xabarlarini tekshirish va yangi xabarlarni
    Kanban doskasiga LeadApplication (source='instagram') va InstagramMessage sifatida saqlash.
    """
    global _last_instagram_poll_time

    now_ts = time.time()
    if not force and (now_ts - _last_instagram_poll_time < POLL_INTERVAL_SECONDS):
        return {"skipped": True, "reason": "throttled"}

    _last_instagram_poll_time = now_ts

    cl = get_authenticated_client()
    if not cl:
        return {"skipped": True, "reason": "no_client"}

    from .models import InstagramMessage, LeadApplication

    new_messages_count = 0
    new_leads_count = 0

    try:
        # 1. Asosiy Direct xabarlar (threads)
        threads = cl.direct_threads(amount=10)
        # 2. Yangi obunachi bo'lmaganlardan kelgan so'rovlar (pending inbox)
        try:
            pending = cl.direct_pending_inbox(amount=10)
            if pending:
                threads.extend(pending)
        except Exception:
            pass

        my_user_id = str(cl.user_id or "")

        for thread in threads:
            # Suhbatdosh (mijoz)ni aniqlash
            client_user = None
            for u in getattr(thread, "users", []):
                if str(u.pk) != my_user_id:
                    client_user = u
                    break

            if not client_user and getattr(thread, "inviter", None):
                inv = thread.inviter
                if str(getattr(inv, "pk", "")) != my_user_id:
                    client_user = inv

            client_pk = str(client_user.pk) if client_user else str(getattr(thread, "id", ""))
            client_username = getattr(client_user, "username", "") or ""
            client_fullname = getattr(client_user, "full_name", "") or ""

            # Thread ichidagi xabarlarni ko'rib chiqamiz
            thread_messages = getattr(thread, "messages", [])
            for msg in thread_messages:
                # Agar xabar biz tomonimizdan yuborilgan bo'lsa (viewer)
                is_viewer = getattr(msg, "is_sent_by_viewer", False)
                if is_viewer:
                    continue

                msg_id = str(getattr(msg, "id", ""))
                if not msg_id:
                    continue

                # Duplicate guard: Agar bu xabar allaqachon DB'da bo'lsa, o'tkazib yuboramiz
                if InstagramMessage.objects.filter(message_id=msg_id).exists():
                    continue

                # Matnni aniqlash
                raw_text = getattr(msg, "text", "") or ""
                item_type = getattr(msg, "item_type", "") or "text"

                if not raw_text:
                    if item_type == "media":
                        raw_text = "[Rasm / Video]"
                    elif item_type == "voice_media":
                        raw_text = "[Ovozli xabar]"
                    elif item_type == "clip":
                        raw_text = "[Reels ulashildi]"
                    elif item_type == "story_share":
                        raw_text = "[Story javobi]"
                    else:
                        raw_text = "[Media xabar]"

                # Mijoz uchun LeadApplication topish yoki yaratish
                lead = None
                if client_pk:
                    lead = LeadApplication.objects.filter(instagram_igsid=client_pk).first()
                if not lead and client_username:
                    lead = LeadApplication.objects.filter(name=f"@{client_username}").first()

                lead_title = f"@{client_username}" if client_username else (client_fullname or f"Instagram:{client_pk[:10]}")

                if not lead:
                    lead = LeadApplication.objects.create(
                        name=lead_title,
                        phone="",
                        source="instagram",
                        status="new",
                        instagram_igsid=client_pk,
                        message=f"[Instagram DM]: {raw_text}",
                    )
                    new_leads_count += 1
                    logger.info("[Instagram Polling] ✅ Yangi Kanban lidi yaratildi: ID=%s (%s)", lead.id, lead_title)
                else:
                    prev = lead.message or ""
                    new_entry = f"[Instagram DM]: {raw_text}"
                    if new_entry not in prev:
                        lead.message = (prev + "\n\n" + new_entry).strip() if prev else new_entry
                    if lead.status in ("contacted", "waiting"):
                        lead.status = "new"
                    if not lead.instagram_igsid and client_pk:
                        lead.instagram_igsid = client_pk
                    lead.save(update_fields=["message", "status", "instagram_igsid"])

                # InstagramMessage ga saqlash
                msg_ts = getattr(msg, "timestamp", None)
                ts_ms = int(msg_ts.timestamp() * 1000) if hasattr(msg_ts, 'timestamp') else int(time.time() * 1000)

                InstagramMessage.objects.create(
                    lead=lead,
                    sender_igsid=client_pk,
                    recipient_igsid=my_user_id,
                    direction="in",
                    text=raw_text,
                    message_id=msg_id,
                    raw_payload={"thread_id": str(getattr(thread, "id", "")), "item_type": item_type},
                    timestamp_ms=ts_ms,
                )
                new_messages_count += 1

    except Exception as exc:
        logger.error("[Instagram Polling] Direct xabarlarni olishda xatolik: %s", exc)
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "new_messages": new_messages_count,
        "new_leads": new_leads_count,
    }


_last_comment_poll_time = 0
COMMENT_POLL_INTERVAL_SECONDS = 15  # Post/Reels коментарияларини текшириш оралиғи


def fetch_and_process_instagram_comments(force: bool = False) -> dict:
    """
    Instagram post ва reels'даги янги комментарияларни текшириш.
    Ҳар бир янги комментарияни:
      1. LeadApplication (source='instagram') лиди сифатида Канбан доскага туширади.
      2. InstagramComment ва InstagramMessage жадвалларига сақлайди.
    """
    global _last_comment_poll_time

    now_ts = time.time()
    if not force and (now_ts - _last_comment_poll_time < COMMENT_POLL_INTERVAL_SECONDS):
        return {"skipped": True, "reason": "throttled"}

    _last_comment_poll_time = now_ts

    cl = get_authenticated_client()
    if not cl:
        return {"skipped": True, "reason": "no_client"}

    from .models import InstagramComment, InstagramMessage, LeadApplication

    new_comments_count = 0
    new_leads_count = 0

    try:
        my_user_id = str(cl.user_id or "")

        # Охирги 8 та пост / reels'ни олиш
        try:
            medias = cl.user_medias(cl.user_id, amount=8)
        except Exception as e:
            logger.warning("[Instagram Comments] Medias олишда хатолик: %s", e)
            return {"success": False, "error": str(e)}

        for media in medias:
            media_id = str(getattr(media, "id", "") or getattr(media, "pk", ""))
            code = getattr(media, "code", "")
            media_type = getattr(media, "media_type", 1)
            media_type_label = "Reels" if media_type == 2 else "Post"
            post_url = f"https://www.instagram.com/p/{code}/" if code else ""

            try:
                comments = cl.media_comments(media_id, amount=25)
            except Exception as e:
                logger.debug("[Instagram Comments] media %s comments xato: %s", media_id, e)
                continue

            for comment in comments:
                comment_id = str(getattr(comment, "pk", "") or getattr(comment, "id", ""))
                if not comment_id:
                    continue

                user = getattr(comment, "user", None)
                commenter_pk = str(getattr(user, "pk", "")) if user else ""
                commenter_username = str(getattr(user, "username", "") or "") if user else ""
                commenter_fullname = str(getattr(user, "full_name", "") or "") if user else ""
                comment_text = str(getattr(comment, "text", "") or "").strip()

                if not comment_text:
                    continue

                # Ўзимизнинг жавобимиз бўлса ташлаб юбориш
                if commenter_pk and my_user_id and commenter_pk == my_user_id:
                    continue

                # Аввал сақланган бўлса ўтказиб юбориш
                if InstagramComment.objects.filter(comment_id=comment_id).exists():
                    continue

                # Мижознинг лидини топиш ёки янги яратиш
                lead = None
                if commenter_pk:
                    lead = LeadApplication.objects.filter(instagram_igsid=commenter_pk).first()
                if not lead and commenter_username:
                    lead = LeadApplication.objects.filter(instagram_igsid=commenter_username).first()

                raw_text = f"💬 [Instagram Коментария - {media_type_label}]: {comment_text}"

                if not lead:
                    lead_name = commenter_fullname or (f"@{commenter_username}" if commenter_username else "Instagram Фойдаланувчи")
                    lead = LeadApplication.objects.create(
                        name=lead_name,
                        phone="",
                        source="instagram",
                        instagram_igsid=commenter_pk or commenter_username,
                        message=raw_text,
                        status="new",
                        course_name_custom=f"Instagram {media_type_label} ({code or 'post'})",
                    )
                    new_leads_count += 1
                    logger.info("[Instagram Comments] Янги лид яратилди: ID=%s (@%s)", lead.id, commenter_username)
                else:
                    prev = lead.message or ""
                    if raw_text not in prev:
                        lead.message = (prev + "\n\n" + raw_text).strip() if prev else raw_text
                    if lead.status in ("contacted", "waiting", "cancelled"):
                        lead.status = "new"
                    if not lead.instagram_igsid and (commenter_pk or commenter_username):
                        lead.instagram_igsid = commenter_pk or commenter_username
                    lead.save(update_fields=["message", "status", "instagram_igsid"])

                # InstagramComment жадвалига ёзиш
                InstagramComment.objects.create(
                    comment_id=comment_id,
                    post_id=media_id,
                    post_url=post_url,
                    commenter_username=commenter_username,
                    commenter_igsid=commenter_pk,
                    text=comment_text,
                    lead=lead,
                    is_read=False,
                    raw_payload={
                        "media_id": media_id,
                        "code": code,
                        "media_type": media_type_label,
                        "commenter_pk": commenter_pk,
                        "commenter_username": commenter_username,
                    }
                )

                # InstagramMessage га ҳам ёзиш (Канбан ичидаги чат ойнасида кўриниши учун)
                c_ts = getattr(comment, "created_at_utc", None)
                ts_ms = int(c_ts.timestamp() * 1000) if hasattr(c_ts, "timestamp") else int(time.time() * 1000)

                InstagramMessage.objects.create(
                    lead=lead,
                    sender_igsid=commenter_pk or commenter_username,
                    recipient_igsid=my_user_id,
                    direction="in",
                    text=raw_text,
                    message_id=f"c_{comment_id}",
                    raw_payload={"type": "comment", "media_id": media_id, "code": code, "post_url": post_url},
                    timestamp_ms=ts_ms,
                )

                new_comments_count += 1
                logger.info("[Instagram Comments] Коментария сақланди: @%s: %s", commenter_username, comment_text[:35])

    except Exception as exc:
        import traceback
        logger.error("[Instagram Comments] Текширишда хатолик: %s\n%s", exc, traceback.format_exc())
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "new_comments": new_comments_count,
        "new_leads": new_leads_count,
    }

