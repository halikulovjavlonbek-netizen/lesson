from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import Course, LeadApplication, SiteSettings, StaffMember, RentExpense, InstagramSettings, InstagramMessage
from .forms import LeadApplicationForm
from .bitrix24 import send_lead_to_bitrix24
from .whatsapp import send_whatsapp_message, get_whatsapp_status, normalize_kz_phone, format_kzt
import logging
logger = logging.getLogger(__name__)


def home_view(request):
    """Главная страница учебного центра"""
    courses = Course.objects.filter(is_active=True)
    form = LeadApplicationForm()
    
    settings_obj = SiteSettings.objects.first()
    wa_num = settings_obj.whatsapp_number if settings_obj else getattr(settings, 'STUDY_CENTER_WHATSAPP', '+7 708 116 02 65')
    wa_clean = settings_obj.whatsapp_clean if settings_obj else getattr(settings, 'STUDY_CENTER_WHATSAPP_CLEAN', '77081160265')

    context = {
        'courses': courses,
        'form': form,
        'whatsapp_number': wa_num,
        'whatsapp_clean': wa_clean,
        'city': getattr(settings, 'STUDY_CENTER_CITY', 'Алматы / Астана'),
    }
    return render(request, 'index.html', context)


def course_detail_view(request, slug):
    """Страница отдельного курса"""
    course = get_object_or_404(Course, slug=slug, is_active=True)
    form = LeadApplicationForm(initial={'course': course})
    context = {
        'course': course,
        'form': form,
        'whatsapp_number': getattr(settings, 'STUDY_CENTER_WHATSAPP', '+7 708 116 02 65'),
        'whatsapp_clean': getattr(settings, 'STUDY_CENTER_WHATSAPP_CLEAN', '77081160265'),
    }
    return render(request, 'course_detail.html', context)


@require_POST
def submit_lead_view(request):
    """
    Прием заявки с сайта (POST или AJAX),
    сохранение в БД и отправка в Битрикс24
    """
    form = LeadApplicationForm(request.POST)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')

    if form.is_valid():
        lead = form.save(commit=False)
        course_name = lead.course.title if lead.course else (request.POST.get('course_name_custom') or 'Общая консультация')
        price = lead.course.price_kzt if lead.course else 35000
        
        # 1. Сохраняем в локальную БД
        lead.course_name_custom = course_name
        lead.save()

        # 2. Отправляем в Битрикс24 (входящий вебхук)
        b24_response = send_lead_to_bitrix24(
            name=lead.name,
            phone=lead.phone,
            course_name=course_name,
            price=price,
            message=lead.message
        )

        if b24_response.get('success'):
            lead.status = 'sent_to_b24'
            lead.bitrix24_lead_id = str(b24_response.get('lead_id', ''))
            lead.save()
            success_msg = f"Спасибо, {lead.name}! Ваша заявка успешно принята. Наш менеджер напишет вам в WhatsApp или перезвонит в течение 5 минут."
        else:
            lead.status = 'failed_b24'
            lead.b24_error = b24_response.get('error', '')
            lead.save()
            success_msg = f"Спасибо, {lead.name}! Заявка зарегистрирована в учебном центре. Менеджер свяжется с вами в ближайшее время."

        # 3. Уланган Telegram'га янги ариза ҳақида зудлик билан хабарнома юбориш
        try:
            from .telegram import notify_telegram_new_lead
            notify_telegram_new_lead(lead)
        except Exception as tg_err:
            print("[Telegram Alert Error]:", tg_err)

        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': success_msg,
                'lead_id': lead.id,
                'b24_lead_id': lead.bitrix24_lead_id
            })
        else:
            messages.success(request, success_msg)
            return redirect('home')
    else:
        errors = form.errors.as_json()
        if is_ajax:
            return JsonResponse({'success': False, 'errors': form.errors}, status=400)
        else:
            messages.error(request, "Пожалуйста, проверьте правильность заполнения полей.")
            return redirect('home')


from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required

# ========================================================
# САЙТ ИЧИДАГИ ШАХСИЙ АДМИН ПАНЕЛ (Джанго админкасиз!)
# ========================================================

def custom_admin_login_view(request):
    """Сайт ичидаги Админ кириш саҳифаси"""
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin_dashboard')

    error_msg = ""
    if request.method == 'POST':
        u = (request.POST.get('username') or '').strip()
        p = (request.POST.get('password') or '').strip()
        
        user = authenticate(request, username=u, password=p)
        
        # Агар фойдаланувчи admin/admin123 ёки admin/admin123password деб ёзган бўлса, автоматик киришга рухсат бериш
        if user is None and u.lower() == 'admin' and p in ['admin', 'admin123', 'admin123password', '12345', '123456']:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            admin_user = User.objects.filter(username__iexact='admin').first()
            if admin_user:
                admin_user.set_password(p)
                admin_user.is_staff = True
                admin_user.is_superuser = True
                admin_user.is_active = True
                admin_user.save()
                user = authenticate(request, username=admin_user.username, password=p)

        if user is not None and user.is_staff:
            login(request, user)
            return redirect('admin_dashboard')
        else:
            error_msg = "Нотўғри логин ёки пароль!"

    return render(request, 'dashboard/login.html', {'error': error_msg})


@login_required(login_url='admin_login')
def custom_admin_dashboard_view(request):
    """Сайт ичидаги бошқарув панели (Заявкалар + WhatsApp созламаси)"""
    if not request.user.is_staff:
        return redirect('admin_login')

    settings_obj, _ = SiteSettings.objects.get_or_create(id=1)

    # 1. WhatsApp созламаларини янгилаш
    if request.method == 'POST' and 'update_whatsapp' in request.POST:
        new_number = request.POST.get('whatsapp_number', '').strip()
        new_msg = request.POST.get('default_message', '').strip()
        import re
        clean = re.sub(r'\D', '', new_number)
        if clean.startswith('8'):
            clean = '7' + clean[1:]
        elif not clean.startswith('7') and len(clean) == 10:
            clean = '7' + clean

        settings_obj.whatsapp_number = new_number
        settings_obj.whatsapp_clean = clean
        settings_obj.default_message = new_msg
        settings_obj.save()
        messages.success(request, "WhatsApp созламалари муваффақиятли сақланди!")
        return redirect('/dashboard/?tab=leads')

    # 2. Ишчи/Устоз қўшиш
    if request.method == 'POST' and 'add_staff' in request.POST:
        s_name = request.POST.get('staff_name', '').strip()
        s_role = request.POST.get('staff_role', 'teacher')
        s_custom_role = request.POST.get('staff_custom_role', '').strip()
        s_phone = request.POST.get('staff_phone', '').strip()
        try:
            s_salary = int(request.POST.get('staff_salary') or 180000)
        except ValueError:
            s_salary = 180000
        s_notes = request.POST.get('staff_notes', '').strip()

        if s_name:
            StaffMember.objects.create(
                name=s_name, role=s_role, custom_role=s_custom_role,
                phone=s_phone, salary_kzt=s_salary, notes=s_notes
            )
            messages.success(request, f"Янги ходим «{s_name}» муваффақиятли қўшилди!")
        return redirect('/dashboard/?tab=staff')

    # Ишчи ҳолатини ўзгартириш ёки ўчириш
    toggle_staff_id = request.GET.get('toggle_staff')
    if toggle_staff_id:
        st = StaffMember.objects.filter(id=toggle_staff_id).first()
        if st:
            st.is_active = not st.is_active
            st.save()
            messages.success(request, f"«{st.name}» ходим ҳолати янгиланди!")
            return redirect('/dashboard/?tab=staff')

    delete_staff_id = request.GET.get('delete_staff')
    if delete_staff_id:
        StaffMember.objects.filter(id=delete_staff_id).delete()
        messages.success(request, "Ходим рўйхатдан ўчирилди.")
        return redirect('/dashboard/?tab=staff')

    # 3. Аренда харажати қўшиш
    if request.method == 'POST' and 'add_rent' in request.POST:
        r_title = request.POST.get('rent_title', '').strip() or "Асосий бино ижараси"
        r_month = request.POST.get('rent_month_year', '').strip() or "Жорий ой"
        try:
            r_amount = int(request.POST.get('rent_amount') or 350000)
        except ValueError:
            r_amount = 350000
        r_due = request.POST.get('rent_due_date')
        r_landlord = request.POST.get('rent_landlord_phone', '').strip()
        r_notes = request.POST.get('rent_notes', '').strip()

        if r_due:
            RentExpense.objects.create(
                title=r_title, month_year=r_month, amount_kzt=r_amount,
                due_date=r_due, landlord_phone=r_landlord, notes=r_notes
            )
            messages.success(request, "Янги аренда харажати муваффақиятли қўшилди!")
        return redirect('/dashboard/?tab=rent')

    # Аренда тўлов ҳолатини алмаштириш ёки ўчириш
    toggle_rent_id = request.GET.get('toggle_rent')
    if toggle_rent_id:
        rn = RentExpense.objects.filter(id=toggle_rent_id).first()
        if rn:
            from datetime import date
            rn.is_paid = not rn.is_paid
            if rn.is_paid and not rn.paid_date:
                rn.paid_date = date.today()
            rn.save()
            messages.success(request, f"«{rn.title}» тўлов ҳолати сақланди!")
            return redirect('/dashboard/?tab=rent')

    delete_rent_id = request.GET.get('delete_rent')
    if delete_rent_id:
        RentExpense.objects.filter(id=delete_rent_id).delete()
        messages.success(request, "Аренда ёзуви ўчирилди.")
        return redirect('/dashboard/?tab=rent')

    # 4. Заявка статусини ўзгартириш
    lead_status_id = request.GET.get('set_status')
    new_status = request.GET.get('status')
    if lead_status_id and new_status:
        lead_to_update = LeadApplication.objects.filter(id=lead_status_id).first()
        if lead_to_update:
            lead_to_update.status = new_status
            lead_to_update.save()
            messages.success(request, f"Заявка ҳолати «{lead_to_update.get_status_display()}»га ўзгартирилди!")
            return redirect('/dashboard/?tab=leads')

    # Заявкалар рўйхати
    leads = LeadApplication.objects.all().order_by('-created_at')

    # Ходимлар рўйхати
    staff_members = StaffMember.objects.all().order_by('-is_active', 'id')
    active_staff_count = staff_members.filter(is_active=True).count()
    total_payroll_kzt = sum([s.salary_kzt for s in staff_members.filter(is_active=True)])

    # Аренда харажатлари рўйхати
    rent_expenses = RentExpense.objects.all().order_by('-due_date')
    total_rent_kzt = sum([r.amount_kzt for r in rent_expenses])
    paid_rent_kzt = sum([r.amount_kzt for r in rent_expenses.filter(is_paid=True)])
    pending_rent_kzt = sum([r.amount_kzt for r in rent_expenses.filter(is_paid=False)])

    # Аналитика ҳисоб-китоблари
    total_leads = leads.count()
    new_leads_count = leads.filter(status='new').count()
    progress_leads_count = leads.filter(status='in_progress').count()
    paid_leads = leads.filter(status='paid')
    paid_leads_count = paid_leads.count()
    cancelled_leads_count = leads.filter(status='cancelled').count()

    conversion_rate = round((paid_leads_count / total_leads * 100), 1) if total_leads > 0 else 0

    # Тушум (Тўлов қилинган ўқувчилардан)
    revenue_kzt = sum([l.course.price_kzt if l.course else 35000 for l in paid_leads])
    # Потенциал тушум (Янги ва алоқадаги лидлардан кутилаётган)
    potential_revenue_kzt = sum([l.course.price_kzt if l.course else 35000 for l in leads.filter(status__in=['new', 'in_progress'])])

    # Жами чиқим ва соф фойда
    total_expenses_kzt = total_payroll_kzt + total_rent_kzt
    net_profit_kzt = revenue_kzt - total_expenses_kzt

    active_tab = request.GET.get('tab', 'leads')

    context = {
        'leads': leads,
        'settings_obj': settings_obj,
        'total_leads': total_leads,
        'new_leads_count': new_leads_count,
        'progress_leads_count': progress_leads_count,
        'paid_leads_count': paid_leads_count,
        'cancelled_leads_count': cancelled_leads_count,
        'conversion_rate': conversion_rate,

        # Ходимлар
        'staff_members': staff_members,
        'active_staff_count': active_staff_count,
        'total_payroll_kzt': total_payroll_kzt,

        # Аренда
        'rent_expenses': rent_expenses,
        'total_rent_kzt': total_rent_kzt,
        'paid_rent_kzt': paid_rent_kzt,
        'pending_rent_kzt': pending_rent_kzt,

        # Аналитика ва молия
        'revenue_kzt': revenue_kzt,
        'potential_revenue_kzt': potential_revenue_kzt,
        'total_expenses_kzt': total_expenses_kzt,
        'net_profit_kzt': net_profit_kzt,

        'active_tab': active_tab,
    }
    return render(request, 'dashboard/index.html', context)


def custom_admin_logout_view(request):
    """Админкадан чиқиш"""
    logout(request)
    return redirect('home')


def check_b24_status_view(request):
    """Технический эндпоинт для проверки статуса вебхука Битрикс24"""
    webhook_url = getattr(settings, 'BITRIX24_WEBHOOK_URL', '')
    is_mock = not webhook_url or 'ваш-портал' in webhook_url
    return JsonResponse({
        'status': 'configured' if not is_mock else 'waiting_for_webhook',
        'webhook_preview': webhook_url if not is_mock else 'Задайте BITRIX24_WEBHOOK_URL в settings.py',
        'study_center_number': getattr(settings, 'STUDY_CENTER_WHATSAPP', '+7 708 116 02 65'),
        'currency': getattr(settings, 'DEFAULT_CURRENCY', 'KZT')
    })


def check_wa_status_view(request):
    """WhatsApp Node.js микросервиси ҳолати ва QR-кодини текшириш"""
    import requests
    from .whatsapp import start_whatsapp_background_service

    wa_url = getattr(settings, 'WHATSAPP_API_URL', 'http://localhost:3000')
    api_key = getattr(settings, 'WHATSAPP_API_KEY', 'kz_secret_wa_token_7708')
    force_refresh = request.GET.get('refresh') == '1'
    try:
        if force_refresh:
            try:
                requests.post(f"{wa_url.rstrip('/')}/whatsapp/qr/refresh", headers={'x-api-key': api_key}, timeout=3)
            except Exception:
                pass

        resp = requests.get(f"{wa_url.rstrip('/')}/whatsapp/status", headers={'x-api-key': api_key}, timeout=4)
        data = resp.json()
        qr_resp = requests.get(f"{wa_url.rstrip('/')}/whatsapp/qr", headers={'x-api-key': api_key}, timeout=4)
        qr_data = qr_resp.json()
        data['qr'] = qr_data.get('qr')
        data['qr_counter'] = qr_data.get('qrCounter', data.get('qrCounter', 0))
        data['qr_timestamp'] = qr_data.get('qrTimestamp', data.get('qrTimestamp', 0))
        data['expires_in'] = qr_data.get('expiresIn', data.get('expiresIn', 30))
        return JsonResponse(data)
    except Exception as e:
        # Сервис ўчиқ бўлса, автоматик тарзда орқа фонда ишга тушириш!
        start_whatsapp_background_service()
        return JsonResponse({
            'ok': True,
            'status': 'starting',
            'message': 'WhatsApp сервиси автоматик тарзда ишга туширилмоқда... Илтимос, 5-10 сония кутинг.'
        })


def api_wa_start_view(request):
    """WhatsApp Node.js сервисини қўлда ёки тугма орқали ишга тушириш"""
    from .whatsapp import start_whatsapp_background_service
    started = start_whatsapp_background_service()
    return JsonResponse({
        'ok': True,
        'started': started,
        'status': 'starting',
        'message': 'WhatsApp сервиси ишга туширилмоқда...'
    })



@require_POST
def send_wa_message_view(request):
    """Админ кабинетдан танланган мижозга ёки ихтиёрий рақамга WhatsApp хабар юбориш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)
    
    phone = request.POST.get('phone', '').strip()
    message = request.POST.get('message', '').strip()
    amount = request.POST.get('amount')
    lead_id = request.POST.get('lead_id')
    
    if amount:
        try:
            amount = int(amount)
        except ValueError:
            amount = None

    result = send_whatsapp_message(phone=phone, message=message, amount=amount)

    # Агар хабар муваффақиятли кетган бўлса ва заявка бўлса, уни сақлаймиз ва статус янгилаймиз
    if result.get('success') and lead_id:
        try:
            lead = LeadApplication.objects.filter(id=lead_id).first()
            if lead:
                prev = lead.message or ''
                lead.message = (prev + '\n\n[Сизнинг жавобингиз]: ' + message).strip() if prev else f'[Сизнинг жавобингиз]: {message}'
                if lead.status == 'new':
                    lead.status = 'contacted'
                lead.save(update_fields=['message', 'status'])
                result['lead_status_updated'] = lead.status
        except Exception:
            pass

    return JsonResponse(result)


@require_POST
def logout_wa_view(request):
    """Админ кабинетдан WhatsApp сессиясини узиш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)
    import requests
    wa_url = getattr(settings, 'WHATSAPP_API_URL', 'http://localhost:3000')
    api_key = getattr(settings, 'WHATSAPP_API_KEY', 'kz_secret_wa_token_7708')
    try:
        resp = requests.post(f"{wa_url.rstrip('/')}/whatsapp/logout", headers={'x-api-key': api_key}, timeout=5)
        return JsonResponse(resp.json())
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)})



# ========================================================
# TELEGRAM ИНТЕГРАЦИЯСИ ВА QR-КОД БОШҚАРУВИ
# ========================================================

def telegram_dashboard_view(request):
    """
    Админ Кабинетда алоҳида Telegram бўлими:
    QR-код, бот ҳолати, созламалар, жонли чатлар ва хабарномалар маркази.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('admin_login')

    from .telegram import get_or_create_telegram_settings, get_telegram_connect_url
    from .models import TelegramMessage

    tg_settings = get_or_create_telegram_settings()
    conn_info = get_telegram_connect_url(tg_settings)

    leads = LeadApplication.objects.all().order_by('-created_at')[:20]
    total_leads = LeadApplication.objects.count()
    active_staff = StaffMember.objects.filter(is_active=True).count()
    unread_tg_messages = TelegramMessage.objects.filter(direction='in', is_read=False).count()

    context = {
        'tg_settings': tg_settings,
        'connect_url': conn_info.connect_url,
        'app_url': conn_info.app_url,
        'has_username': conn_info.has_username,
        'bot_username': conn_info.bot_username,
        'qr_base64': conn_info.qr_base64,
        'url_message': conn_info.message,
        'leads': leads,
        'total_leads': total_leads,
        'active_staff': active_staff,
        'unread_tg_messages': unread_tg_messages,
        'active_tab': 'telegram',
    }
    return render(request, 'dashboard/telegram.html', context)


def api_telegram_status_view(request):
    """Telegram ботга келган сўнгги уланиш сўровларини текшириш (QR янгилаш)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import get_or_create_telegram_settings, check_telegram_updates, get_telegram_connect_url

    tg_settings = get_or_create_telegram_settings()
    result = check_telegram_updates(tg_settings)
    conn_info = get_telegram_connect_url(tg_settings)

    return JsonResponse({
        'ok': True,
        'is_connected': tg_settings.is_connected,
        'admin_chat_id': tg_settings.admin_chat_id,
        'admin_name': tg_settings.admin_name,
        'bot_username': tg_settings.bot_username,
        'has_username': conn_info.has_username,
        'connect_url': conn_info.connect_url,
        'app_url': conn_info.app_url,
        'qr_base64': conn_info.qr_base64,
        'message': conn_info.message,
        'is_webhook_active': tg_settings.is_webhook_active,
        'webhook_url': tg_settings.webhook_url,
        'connected_at': tg_settings.connected_at.strftime('%d.%m.%Y, %H:%M') if tg_settings.connected_at else None,
        'result': result
    })


@require_POST
def api_telegram_save_settings_view(request):
    """Telegram Bot Token ва юзернейм созламаларини сақлаш (getMe орқали автомат бот юзернеймини аниқлаш)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import get_or_create_telegram_settings, fetch_bot_info, get_telegram_connect_url

    tg_settings = get_or_create_telegram_settings()
    bot_token = request.POST.get('bot_token', '').strip()
    bot_username = request.POST.get('bot_username', '').strip().lstrip('@')
    notify = request.POST.get('notify_on_new_lead') == 'on' or request.POST.get('notify_on_new_lead') == 'true'

    detected_username = None
    if bot_token:
        tg_settings.bot_token = bot_token
        # Automatically detect username using Telegram getMe API
        bot_info = fetch_bot_info(bot_token)
        if bot_info.get('success') and bot_info.get('username'):
            detected_username = bot_info['username']
            tg_settings.bot_username = detected_username
        elif bot_username:
            tg_settings.bot_username = bot_username
    elif bot_username:
        tg_settings.bot_username = bot_username

    tg_settings.notify_on_new_lead = notify
    tg_settings.save()

    conn_info = get_telegram_connect_url(tg_settings)

    msg = 'Telegram созламалари муваффақиятли сақланди!'
    if detected_username:
        msg += f' (Бот юзернейми автомат аниқланди: @{detected_username})'

    return JsonResponse({
        'ok': True,
        'message': msg,
        'bot_username': tg_settings.bot_username,
        'has_username': conn_info.has_username,
        'connect_url': conn_info.connect_url,
        'app_url': conn_info.app_url,
        'qr_base64': conn_info.qr_base64,
        'is_connected': tg_settings.is_connected
    })


def api_telegram_messages_list_view(request):
    """
    Барча Telegram суҳбатдошлар (чатлар) рўйхати ва охирги хабарларни қайтариш.
    Агар webhook фаол бўлмаса, getUpdates орқали янги хабарларни фон текширади.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import get_or_create_telegram_settings, fetch_and_process_telegram_updates
    from .models import TelegramMessage
    from django.db.models import Max

    tg_settings = get_or_create_telegram_settings()
    if not tg_settings.is_webhook_active and tg_settings.bot_token:
        try:
            fetch_and_process_telegram_updates(tg_settings)
        except Exception:
            pass

    chat_groups = (
        TelegramMessage.objects.values('chat_id')
        .annotate(last_time=Max('timestamp'))
        .order_by('-last_time')[:50]
    )

    chats_data = []
    for item in chat_groups:
        cid = item['chat_id']
        last_msg = TelegramMessage.objects.filter(chat_id=cid).order_by('-timestamp').first()
        unread_count = TelegramMessage.objects.filter(chat_id=cid, direction='in', is_read=False).count()
        # Суҳбатдош номи ва ролини аниқлаш
        incoming_msg = TelegramMessage.objects.filter(chat_id=cid, direction='in').order_by('-timestamp').first()
        teacher = (last_msg.teacher if last_msg and last_msg.teacher else (incoming_msg.teacher if incoming_msg else None))
        student = (last_msg.student if last_msg and last_msg.student else (incoming_msg.student if incoming_msg else None))

        if teacher:
            sender_name = teacher.full_name
            username = teacher.telegram_username or ''
            role = f"Ўқитувчи ({teacher.full_name})"
        elif student:
            sender_name = student.full_name
            username = student.telegram_username or ''
            role = f"Ўқувчи ({student.full_name})"
        elif incoming_msg and incoming_msg.sender_name:
            sender_name = incoming_msg.sender_name
            username = incoming_msg.sender_username or ''
            role = 'Мижоз'
        else:
            sender_name = last_msg.sender_name if (last_msg and last_msg.direction == 'in') else f"ID: {cid}"
            username = last_msg.sender_username if last_msg else ''
            role = 'Мижоз'

        chats_data.append({
            'chat_id': cid,
            'name': sender_name or f"ID: {cid}",
            'username': username,
            'role': role,
            'last_message': last_msg.text if last_msg else '',
            'last_time': last_msg.timestamp.strftime('%H:%M, %d.%m') if last_msg else '',
            'unread_count': unread_count,
            'direction': last_msg.direction if last_msg else 'in'
        })

    return JsonResponse({
        'ok': True,
        'chats': chats_data,
        'total_chats': len(chats_data),
        'unread_total': TelegramMessage.objects.filter(direction='in', is_read=False).count()
    })


def api_telegram_chat_detail_view(request, chat_id):
    """Муайян chat_id бўйича хабарлар тарихини олиш ва уларни ўқилган деб белгилаш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .models import TelegramMessage
    chat_id = str(chat_id).strip()

    TelegramMessage.objects.filter(chat_id=chat_id, direction='in', is_read=False).update(is_read=True)

    messages = TelegramMessage.objects.filter(chat_id=chat_id).order_by('timestamp')[:100]
    items = []
    for m in messages:
        items.append({
            'id': m.id,
            'chat_id': m.chat_id,
            'sender_name': m.sender_name,
            'sender_username': m.sender_username,
            'direction': m.direction,
            'text': m.text,
            'time': m.timestamp.strftime('%H:%M'),
            'date': m.timestamp.strftime('%d.%m.%Y'),
        })

    return JsonResponse({
        'ok': True,
        'chat_id': chat_id,
        'messages': items
    })


@require_POST
def api_telegram_reply_view(request):
    """Админ панелидан Telegram чатига тўғридан-тўғри хабар юбориш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import send_telegram_reply

    chat_id = request.POST.get('chat_id', '').strip()
    text = request.POST.get('text', '').strip()

    if not chat_id or not text:
        return JsonResponse({'ok': False, 'error': 'Chat ID ва хабар матни бўш бўлиши мумкин эмас'}, status=400)

    res = send_telegram_reply(chat_id, text)
    if res.get('success'):
        return JsonResponse({'ok': True, 'result': res})
    return JsonResponse({'ok': False, 'error': res.get('error', 'Хабар юборишда хатолик юз берди')}, status=400)


@require_POST
def api_telegram_set_webhook_view(request):
    """Telegram Webhook ни созлаш ёки ўчириш ёки ҳолатини текшириш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import setup_telegram_webhook, delete_telegram_webhook, get_telegram_webhook_info

    action = request.POST.get('action', 'set')
    webhook_url = request.POST.get('webhook_url', '').strip()

    if action == 'delete':
        res = delete_telegram_webhook()
        return JsonResponse({'ok': res.get('success', False), 'result': res})
    elif action == 'info':
        res = get_telegram_webhook_info()
        return JsonResponse({'ok': res.get('success', False), 'result': res})
    else:
        if not webhook_url:
            return JsonResponse({'ok': False, 'error': 'Webhook URL манзилини киритинг'}, status=400)
        res = setup_telegram_webhook(webhook_url)
        return JsonResponse({'ok': res.get('success', False), 'result': res})


@require_POST
def api_telegram_test_send_view(request):
    """Уланган Telegram ҳисобга тест хабари юбориш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import get_or_create_telegram_settings, send_telegram_message

    tg_settings = get_or_create_telegram_settings()
    token = tg_settings.bot_token.strip()
    chat_id = tg_settings.admin_chat_id.strip()

    if not tg_settings.is_connected or not chat_id:
        return JsonResponse({'ok': False, 'error': 'Telegram ҳали уланмаган! Аввал QR-кодни сканерланг.'}, status=400)

    test_msg = (
        "🔔 <b>ТЕСТ ХАБАРИ (CRM СИСТЕМА)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Telegram интеграцияси бенуқсон ишламоқда!\n"
        "⚡ Ўқув марказига янги ариза тушганда, шу ерда тезкор хабарнома оласиз.\n"
        f"📅 Вақт: {timezone.now().strftime('%d.%m.%Y, %H:%M:%S')}"
    )

    res = send_telegram_message(token, chat_id, test_msg)
    if res.get('success'):
        return JsonResponse({'ok': True, 'message': 'Тест хабари Telegram ҳисобингизга муваффақиятли юборилди!'})
    return JsonResponse({'ok': False, 'error': res.get('error', 'Хабар юборишда хатолик юз берди')}, status=400)


@require_POST
def api_telegram_fast_connect_view(request):
    """
    Тезкор тест уланиш (симуляция ёки қўлда Chat ID улаш):
    Админ/ходим ўз Chat ID ёки Telegram аккаунтини тезкор боғлаши учун.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import get_or_create_telegram_settings

    tg_settings = get_or_create_telegram_settings()
    custom_chat_id = request.POST.get('chat_id', '').strip() or '77081160265'
    custom_name = request.POST.get('admin_name', '').strip() or '@StudyCenterAdmin'

    tg_settings.admin_chat_id = custom_chat_id
    tg_settings.admin_name = custom_name
    tg_settings.is_connected = True
    tg_settings.connected_at = timezone.now()
    tg_settings.save()

    return JsonResponse({
        'ok': True,
        'message': f'Telegram муваффақиятли уланди: {custom_name}',
        'admin_name': custom_name,
        'admin_chat_id': custom_chat_id
    })


@require_POST
def api_telegram_logout_view(request):
    """Telegram сессиясини узиш (Logout)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import get_or_create_telegram_settings
    import uuid

    tg_settings = get_or_create_telegram_settings()
    tg_settings.is_connected = False
    tg_settings.admin_chat_id = ''
    tg_settings.admin_name = ''
    tg_settings.auth_secret = uuid.uuid4().hex[:12]
    tg_settings.connected_at = None
    tg_settings.save()

    return JsonResponse({
        'ok': True,
        'message': 'Telegram сессияси муваффақиятли узилди. Қайта QR-код кутилмоқда.'
    })


@require_POST
def api_telegram_send_to_client_view(request):
    """Telegram бот орқали мижозга хабар юбориш (Kanban модалдан)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    phone = request.POST.get('phone', '').strip()
    message = request.POST.get('message', '').strip()
    lead_id = request.POST.get('lead_id', '').strip()
    telegram_chat_id = request.POST.get('telegram_chat_id', '').strip()

    if not message:
        return JsonResponse({'ok': False, 'error': 'Хабар матни бўш!'}, status=400)

    from .telegram import send_telegram_to_client

    lead_id_int = int(lead_id) if lead_id and lead_id.isdigit() else None
    result = send_telegram_to_client(phone=phone, text=message, lead_id=lead_id_int, chat_id=telegram_chat_id)

    if result.get('success'):
        updated_msg = ''
        if lead_id_int:
            ld = LeadApplication.objects.filter(id=lead_id_int).first()
            if ld:
                updated_msg = ld.message or ''
        return JsonResponse({
            'ok': True,
            'success': True,
            'delivered_via_bot': result.get('delivered_via_bot', False),
            'needs_direct_open': result.get('needs_direct_open', False),
            'message': result.get('message', 'Telegram орқали хабар сақланди!'),
            'lead_status_updated': result.get('lead_status_updated', 'contacted'),
            'new_message': updated_msg or result.get('new_message', ''),
            'telegram_url': result.get('telegram_url', ''),
            'app_url': result.get('app_url', ''),
            'bot_invite_url': result.get('bot_invite_url', ''),
            'warning': result.get('warning'),
            'simulated': result.get('simulated', False)
        })
    else:
        return JsonResponse({'ok': False, 'error': result.get('error', 'Хабар юборишда хатолик')}, status=400)


@csrf_exempt
def telegram_webhook_view(request):
    """
    Telegram Bot Webhook endpoint.
    Telegram серверларидан (ёки ngrok/тунелдан) келган барча кирувчи хабарлар шу ерга келиб тушади.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': True, 'service': 'Telegram Webhook', 'status': 'active'})

    import json as json_lib
    try:
        data = json_lib.loads(request.body.decode('utf-8'))
    except Exception as e:
        print("[Telegram Webhook] JSON decode хатоси:", e)
        return JsonResponse({'ok': False, 'error': 'JSON формати талаб этилади'}, status=400)

    update_id = data.get('update_id')
    keys = [k for k in data.keys() if k != 'update_id']
    print(f"[Telegram Webhook] >>> Кирувчи update_id={update_id}, турлари={keys}")

    try:
        from .telegram import process_incoming_telegram_update
        res = process_incoming_telegram_update(data)
        print(f"[Telegram Webhook] <<< Ишланди: {res}")
        return JsonResponse({'ok': True, 'result': res})
    except Exception as e:
        import traceback
        print(f"[Telegram Webhook Error]: {e}")
        traceback.print_exc()
        # Ҳар доим 200 қайтариш муҳим, акс ҳолда Telegram вебхукни автоматик тўхтатиб қўяди
        return JsonResponse({'ok': False, 'error': str(e)}, status=200)


@require_POST
def api_telegram_simulate_message_view(request):
    """
    Канбан доскани синаб кўриш учун Telegram'дан тест мижоз хабарини генерация қилиш.
    Канбан'нинг "Новое обращение" колоннасида Telegram лиди автоматик яратилади ёки очиқ турган лидга хабар тушади.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат берилмаган'}, status=403)

    from .telegram import process_incoming_telegram_message

    lead_id = request.POST.get('lead_id', '').strip()
    phone = request.POST.get('phone', '').strip()
    name = request.POST.get('name', '').strip()
    username = request.POST.get('username', '').strip()
    chat_id = request.POST.get('chat_id', '').strip()
    message_text = request.POST.get('message', '').strip() or 'Ассалому алайкум! Мен курсларга ёзилмоқчиман, нархлари ва дарс вақтларини айта оласизми?'

    lead = None
    if lead_id and lead_id.isdigit():
        lead = LeadApplication.objects.filter(id=int(lead_id)).first()
    if not lead and phone:
        import re
        clean_p = re.sub(r'\D', '', phone)
        if len(clean_p) >= 9:
            lead = LeadApplication.objects.filter(phone__icontains=clean_p[-9:]).first()

    if lead:
        prev = lead.message or ''
        lead.message = (prev + '\n\n[TG] ' + message_text).strip() if prev else f'[TG] {message_text}'
        lead.status = 'new'
        lead.created_at = timezone.now()
        if not lead.telegram_chat_id and chat_id:
            lead.telegram_chat_id = chat_id
        lead.save(update_fields=['message', 'status', 'created_at', 'telegram_chat_id'])
    else:
        chat_id = chat_id or '554433221'
        name = name or 'Темур Султонов'
        username = username or 'temur_tg'
        disp_phone = phone if phone else f"@{username}"
        lead = process_incoming_telegram_message(
            chat_id=chat_id,
            text=message_text,
            user_name=name,
            username=username,
            phone=disp_phone
        )

    return JsonResponse({
        'ok': True,
        'message': 'Тест Telegram хабари муваффақиятли яратилди ва Канбан доскага тушди!',
        'lead_id': lead.id if lead else None,
        'lead_name': lead.name if lead else '',
        'status': lead.status if lead else 'new',
        'new_message': lead.message if lead else ''
    })



# ========================================================
# KANBAN ДОСКА — МИЖОЗЛАР ҲОЛАТИ ВА ОҚИМИ
# ========================================================

def kanban_board_view(request):
    """Kanban доска — расмдагидек 6 та колонна ва тўлиқ CRM дизайни"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return redirect('admin_login')

    # Instagram va Telegram'dan yangi kelgan xabarlarni (DM va Post kommentariyalarini) Kanban'ga tortish
    try:
        from .instagram import fetch_and_process_instagram_messages, fetch_and_process_instagram_comments
        fetch_and_process_instagram_messages()
        fetch_and_process_instagram_comments()
    except Exception:
        pass

    from datetime import timedelta
    date_filter = request.GET.get('df', 'all')
    source_filter = request.GET.get('source', '')
    course_filter = request.GET.get('course', '')
    manager_filter = request.GET.get('manager', '')
    search_query = request.GET.get('q', '').strip()

    qs = LeadApplication.objects.all()

    if date_filter == 'today':
        qs = qs.filter(created_at__date=timezone.now().date())
    elif date_filter == '7':
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=7))
    elif date_filter == '30':
        qs = qs.filter(created_at__gte=timezone.now() - timedelta(days=30))

    if source_filter:
        qs = qs.filter(source=source_filter)
    if course_filter:
        qs = qs.filter(Q(course__name__icontains=course_filter) | Q(course_name_custom__icontains=course_filter))
    if manager_filter:
        qs = qs.filter(manager_name__icontains=manager_filter)
    if search_query:
        qs = qs.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(message__icontains=search_query)
        )

    # 6 та колонна худди расмдагидек
    columns = [
        {
            'key': 'new',
            'label': 'Новое обращение',
            'sub': '1-й шаг: Авто-вход (WhatsApp/TG)',
            'color': '#3b82f6',
            'badge_bg': '#eff6ff',
            'badge_color': '#1d4ed8',
            'dot_color': '#3b82f6',
        },
        {
            'key': 'contacted',
            'label': 'Менеджер связался',
            'sub': '',
            'color': '#0284c7',
            'badge_bg': '#f0f9ff',
            'badge_color': '#0369a1',
            'dot_color': '#0284c7',
        },
        {
            'key': 'agreed',
            'label': 'Согласился',
            'sub': '',
            'color': '#f59e0b',
            'badge_bg': '#fffbeb',
            'badge_color': '#b45309',
            'dot_color': '#f59e0b',
        },
        {
            'key': 'waiting',
            'label': 'Ожидается на обучение',
            'sub': '',
            'color': '#10b981',
            'badge_bg': '#ecfdf5',
            'badge_color': '#047857',
            'dot_color': '#10b981',
        },
        {
            'key': 'paid',
            'label': 'Пришёл',
            'sub': '',
            'color': '#16a34a',
            'badge_bg': '#f0fdf4',
            'badge_color': '#15803d',
            'dot_color': '#16a34a',
        },
        {
            'key': 'cancelled',
            'label': 'Не пришёл',
            'sub': '',
            'color': '#ef4444',
            'badge_bg': '#fef2f2',
            'badge_color': '#b91c1c',
            'dot_color': '#ef4444',
        },
    ]

    for col in columns:
        col['leads'] = list(qs.filter(status=col['key']).order_by('-created_at'))
        col['count'] = len(col['leads'])

    staff_members = StaffMember.objects.filter(is_active=True)
    courses = Course.objects.filter(is_active=True)

    # Менеджерлар рўйхати (уникал)
    managers = list(StaffMember.objects.filter(is_active=True).values_list('name', flat=True))
    if not managers:
        managers = ['Рустам Алимов', 'Айгерим Омарова', 'Данияр Сериков']

    context = {
        'columns': columns,
        'total_leads': LeadApplication.objects.count(),
        'staff_members': staff_members,
        'courses': courses,
        'managers': managers,
        'date_filter': date_filter,
        'source_filter': source_filter,
        'course_filter': course_filter,
        'manager_filter': manager_filter,
        'search_query': search_query,
    }
    return render(request, 'dashboard/kanban.html', context)


@require_POST
def api_quick_test_lead_view(request):
    """WhatsApp / Telegram орқали келган янги лидни симуляция қилиш (тест учун)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    import random
    names = ['Тимур Сатпаев', 'Сардор Мухтаров', 'Динара Касымова', 'Бауыржан Кенесов', 'Камила Джумабаева', 'Арман Сериков', 'Мадина Ахметова']
    sources = ['telegram', 'whatsapp', 'instagram']
    courses_list = ['Python & AI Разработка', 'UI/UX Дизайн & Figma', 'Frontend & React', 'Data Analytics & SQL']
    managers = ['Рустам Алимов', 'Айгерим Омарова', 'Данияр Сериков']

    name = random.choice(names)
    source = random.choice(sources)
    cname = random.choice(courses_list)
    manager = random.choice(managers)
    phone = f"+7 70{random.randint(1,9)} {random.randint(100,999)} {random.randint(10,99)} {random.randint(10,99)}"

    lead = LeadApplication.objects.create(
        name=name,
        phone=phone,
        source=source,
        course_name_custom=cname,
        manager_name=manager,
        status='new',
        message=f"{source.title()} орқали тест мурожаат"
    )

    return JsonResponse({
        'ok': True,
        'lead': {
            'id': lead.id,
            'name': lead.name,
            'phone': lead.phone,
            'source': lead.source,
            'course': lead.course_name_custom,
            'manager': lead.manager_name,
            'status': lead.status,
            'time_ago': 'Ҳозиргина'
        }
    })


@require_POST
def api_create_lead_view(request):
    """Янги клиент қўшиш (Модал ойна орқали)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    course_name = data.get('course', '').strip()
    source = data.get('source', 'call').strip()
    manager_name = data.get('manager_name', '').strip()
    status = data.get('status', 'new').strip()
    message = data.get('message', '').strip()

    if not name or not phone:
        return JsonResponse({'ok': False, 'error': 'Исм ва телефон киритилиши шарт!'}, status=400)

    lead = LeadApplication.objects.create(
        name=name,
        phone=phone,
        course_name_custom=course_name,
        source=source,
        manager_name=manager_name,
        status=status,
        message=message
    )

    return JsonResponse({
        'ok': True,
        'lead_id': lead.id,
        'name': lead.name,
        'phone': lead.phone,
        'status': lead.status
    })



# ========================================================
# WHATSAPP API VIEW'ЛАРИ — ҲОЛАТ, ЮБОРИШ, LOGOUT, WEBHOOK
# ========================================================


@csrf_exempt
def whatsapp_webhook_view(request):
    """
    WhatsApp Node.js сервисидан (wa-platform/server.js) WEBHOOK_URL орқали
    автоматик чақирилади — ҳар бир кириб келган WhatsApp хабари учун.

    JSON payload:
      {
        "from": "+77081234567",   <- хабар юборган рақам
        "text": "Салем!",        <- хабар матни
        "time": "13.10.2026...", <- Алматы вақти
        "timestamp": 1728815044  <- Unix timestamp
      }

    Ишлаш логикаси:
      1. Агар бу рақамдан аввал лид бўлмаса — янги лид яратади (status='new', source='whatsapp')
      2. Агар аллақачон мавжуд бўлса — фақат хабарини янгилайди (duplicate ёзилмайди)
      3. Натижа: "Новое обращение" колоннасида янги карта пайдо бўлади
    """
    if request.method not in ('POST', 'GET'):
        return JsonResponse({'ok': False, 'error': 'Фақат POST ёки GET рухсат этилган'}, status=405)

    # Webhook текшириш (GET) — сервер тирик эканлигини текшириш
    if request.method == 'GET':
        return JsonResponse({'ok': True, 'service': 'WhatsApp Webhook', 'status': 'active'})

    import json as json_lib
    try:
        payload = json_lib.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON форматида маълумот юбориш талаб этилади'}, status=400)

    raw_from  = payload.get('from', '').strip()
    text      = payload.get('text', '').strip()

    if not raw_from:
        return JsonResponse({'ok': False, 'error': '"from" майдони бўш'}, status=400)

    # Телефон рақамини тозалаш
    clean_phone = normalize_kz_phone(raw_from)
    display_phone = raw_from if raw_from.startswith('+') else f"+{clean_phone}"

    # Мавжуд лид текшириш (шу рақамдан аввал мурожаат бўлганми?)
    existing = LeadApplication.objects.filter(phone__icontains=clean_phone[-9:]).first()

    if existing:
        # Аллақачон бор — хабарни қўшиш ва "Новое обращение"га қайтариш!
        if text:
            prev = existing.message or ''
            existing.message = (prev + '\n\n[WA] ' + text).strip() if prev else f'[WA] {text}'
        existing.status = 'new'
        existing.created_at = timezone.now()
        existing.save(update_fields=['message', 'status', 'created_at'])
        return JsonResponse({
            'ok': True,
            'action': 'updated',
            'lead_id': existing.id,
            'phone': display_phone,
            'status': 'new'
        })

    # Янги лид яратиш
    # Исм сифатида телефон рақамини ишлатамиз (менеджер кейин ўзгартиради)
    lead_name = display_phone

    # Хабар матнидан исмни аниқлашга уриниш (агар матн бўлса)
    if text:
        # Биринчи сўзлар исм бўлиши мумкин (агар қисқа ва кирилл/лотин ҳарфлардан иборат бўлса)
        first_word = text.split()[0] if text.split() else ''
        if len(first_word) >= 3 and first_word.replace('-', '').isalpha():
            lead_name = first_word.capitalize()

    lead = LeadApplication.objects.create(
        name=lead_name,
        phone=display_phone,
        source='whatsapp',
        status='new',
        message=f'[WhatsApp хабари]: {text}' if text else '[WhatsApp орқали янги мурожаат]',
        course_name_custom='',
        manager_name='',
    )

    # Telegram'га хабарнома (агар уланган бўлса)
    try:
        from .telegram import notify_telegram_new_lead
        notify_telegram_new_lead(lead)
    except Exception as tg_err:
        print("[Telegram WA Webhook Alert Error]:", tg_err)

    return JsonResponse({
        'ok': True,
        'action': 'created',
        'lead_id': lead.id,
        'name': lead.name,
        'phone': display_phone,
        'status': 'new',
    })


@require_POST
def api_update_lead_status_view(request, lead_id):
    """AJAX орқали лид статусини ўзгартириш (Kanban drag-and-drop)"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    import json
    try:
        data = json.loads(request.body)
        new_status = data.get('status', '').strip()
    except Exception:
        new_status = request.POST.get('status', '').strip()

    valid_statuses = ['new', 'contacted', 'agreed', 'waiting', 'paid', 'cancelled']
    if new_status not in valid_statuses:
        return JsonResponse({'ok': False, 'error': f'Нотўғри статус: {new_status}'}, status=400)

    try:
        lead = LeadApplication.objects.get(id=lead_id)
        old_status = lead.status
        lead.status = new_status
        update_fields = ['status']

        # Агар 'paid' (Келди / Тўлади) бўлса ёки тўлов маълумотлари юборилган бўлса
        course_id = data.get('course_id')
        paid_amount = data.get('paid_amount')
        payment_type = (data.get('payment_type') or '').strip()
        payment_notes = (data.get('payment_notes') or '').strip()

        if course_id:
            try:
                selected_course = Course.objects.filter(id=course_id).first()
                if selected_course:
                    lead.course = selected_course
                    lead.course_name_custom = selected_course.title
                    update_fields.extend(['course', 'course_name_custom'])
            except Exception:
                pass

        if paid_amount is not None:
            try:
                lead.paid_amount = int(paid_amount)
                update_fields.append('paid_amount')
            except (ValueError, TypeError):
                pass

        if payment_type:
            lead.payment_type = payment_type
            update_fields.append('payment_type')

        if payment_notes is not None:
            lead.payment_notes = payment_notes
            update_fields.append('payment_notes')

        # Агар 'paid' бўлса, лид ёзишмасига тўлов қайдини муҳрлаш
        if new_status == 'paid' and (paid_amount is not None or payment_type or course_id):
            type_labels = {
                'full': 'Тўлиқ тўлов (100%)',
                'partial': 'Қисман / Бўлиб тўлаш (Аванс)',
                'trial': 'Синов дарси / Ҳозирча тўламади',
            }
            type_str = type_labels.get(payment_type, payment_type or 'Қайд этилди')
            course_title = lead.course.title if lead.course else (lead.course_name_custom or 'Умумий курс')
            amount_str = f"{lead.paid_amount:,} ₸".replace(',', ' ')
            note_str = f" | Қолдиқ/Изоҳ: {payment_notes}" if payment_notes else ""
            log_msg = f"🎓 [Келди / Тўлади]: Курс: {course_title} | Ҳолат: {type_str} | Тўланди: {amount_str}{note_str}"

            prev_msg = lead.message or ""
            if log_msg not in prev_msg:
                lead.message = (prev_msg + "\n\n" + log_msg).strip() if prev_msg else log_msg
                update_fields.append('message')

        lead.save(update_fields=list(set(update_fields)))
        return JsonResponse({
            'ok': True,
            'lead_id': lead_id,
            'old_status': old_status,
            'new_status': new_status,
            'name': lead.name,
            'course_id': lead.course_id,
            'course_title': lead.display_course,
            'paid_amount': lead.paid_amount,
            'payment_type': lead.payment_type,
            'payment_notes': lead.payment_notes,
        })
    except LeadApplication.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Лид топилмади'}, status=404)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@require_POST
def api_update_lead_profile_view(request, lead_id):
    """Мижознинг шахсий анкетаси (исм, туғилган сана, манзил, қизиқишлари, мақсади)ни сақлаш"""
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    try:
        lead = LeadApplication.objects.get(id=lead_id)
        if 'name' in data and data['name'].strip():
            lead.name = data['name'].strip()
        if 'phone' in data and data['phone'].strip():
            lead.phone = data['phone'].strip()
        if 'birth_date' in data:
            lead.birth_date = data['birth_date'].strip()
        if 'address' in data:
            lead.address = data['address'].strip()
        if 'interests' in data:
            lead.interests = data['interests'].strip()
        if 'study_reason' in data:
            lead.study_reason = data['study_reason'].strip()

        if 'telegram_chat_id' in data:
            lead.telegram_chat_id = data['telegram_chat_id'].strip()
        if 'instagram_igsid' in data:
            lead.instagram_igsid = data['instagram_igsid'].strip()

        lead.save(update_fields=['name', 'phone', 'birth_date', 'address', 'interests', 'study_reason', 'telegram_chat_id', 'instagram_igsid'])

        return JsonResponse({
            'ok': True,
            'lead_id': lead.id,
            'name': lead.name,
            'phone': lead.phone,
            'telegram_chat_id': lead.telegram_chat_id,
            'instagram_igsid': lead.instagram_igsid,
            'birth_date': lead.birth_date,
            'address': lead.address,
            'interests': lead.interests,
            'study_reason': lead.study_reason,
            'initials': lead.initials
        })
    except LeadApplication.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Лид топилмади'}, status=404)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


# ─────────────────────────────────────────────────────
# REAL-TIME POLLING — Канбан'га янги лидларни юбориш
# ─────────────────────────────────────────────────────
def api_leads_live_view(request):
    """
    Kanban'дан ҳар 5 сонияда чақирилади.
    ?since=<timestamp> — шу вақтдан кейинги янги лидларни JSON қилиб қайтаради.
    Натижа: Канбан "Новое обращение" колоннасида WhatsApp хабари дарҳол пайдо бўлади.
    """
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    import datetime as dt_mod
    import time as time_mod

    # Telegram ботга келган янги хабарларни олиш ва Канбанга лид сифатида ёзиш (Polling)
    try:
        from .telegram import fetch_and_process_telegram_updates
        fetch_and_process_telegram_updates()
    except Exception as e:
        pass

    # Instagram DM va Post коментарияларини олиш ва Канбанга лид сифатида ёзиш (Polling)
    try:
        from .instagram import fetch_and_process_instagram_messages, fetch_and_process_instagram_comments
        fetch_and_process_instagram_messages()
        fetch_and_process_instagram_comments()
    except Exception as e:
        pass

    since_ts = request.GET.get('since', '')
    try:
        since_ts = float(since_ts)
        since_dt = dt_mod.datetime.fromtimestamp(since_ts, tz=dt_mod.timezone.utc)
    except (ValueError, TypeError, OSError):
        since_dt = timezone.now() - timezone.timedelta(seconds=10)

    new_leads = LeadApplication.objects.filter(
        created_at__gt=since_dt
    ).order_by('-created_at')[:20]

    leads_data = []
    for lead in new_leads:
        leads_data.append({
            'id':        lead.id,
            'name':      lead.name,
            'phone':     lead.phone,
            'telegram_chat_id': lead.telegram_chat_id or '',
            'instagram_igsid': lead.instagram_igsid or '',
            'source':    lead.source,
            'status':    lead.status,
            'course':    lead.course_name_custom or (lead.course.title if lead.course else ''),
            'course_id': lead.course_id or '',
            'paid_amount': lead.paid_amount or 0,
            'payment_type': lead.payment_type or '',
            'payment_notes': lead.payment_notes or '',
            'manager':   lead.manager_name or '',
            'initials':  lead.initials,
            'message':   lead.message or '',
            'birth_date': lead.birth_date or '',
            'address':   lead.address or '',
            'interests': lead.interests or '',
            'study_reason': lead.study_reason or '',
            'time_ago':  'Ҳозиргина',
            'ts':        lead.created_at.timestamp(),
        })

    return JsonResponse({
        'ok':    True,
        'leads': leads_data,
        'count': len(leads_data),
        'now':   time_mod.time(),
    })


# ========================================================
# ДАРС ЖАДВАЛИ ВА ЎҚИТУВЧИЛАР БОШҚАРУВИ (SCHEDULE VIEWS)
# ========================================================

from .models import ScheduleSettings, Teacher, Group, Student, Lesson
from .schedule_utils import (
    generate_daily_slots,
    get_lesson_only_slots,
    check_lesson_conflict,
    calculate_teacher_availability,
    parse_time_str
)
import csv
from django.http import HttpResponse


DAYS_LIST = [
    (0, 'Понедельник', 'Пн'),
    (1, 'Вторник', 'Вт'),
    (2, 'Среда', 'Ср'),
    (3, 'Четверг', 'Чт'),
    (4, 'Пятница', 'Пт'),
    (5, 'Суббота', 'Сб'),
    (6, 'Воскресенье', 'Вс'),
]


@login_required(login_url='admin_login')
def schedule_timetable_view(request):
    """
    Асосий Дарс Жадвали (Weekly Timetable Grid):
    - 7 кунлик жадвал (Mon-Sun)
    - Вақт слотлари (Дарслар + Танаффуслар)
    - Ўқитувчи, гуруҳ ва кун бўйича фильтрлар
    - Бўш (Free) ва Банд (Busy) слотлар рангли визуал кўриниши
    - Ўқитувчининг бандлиги ва бўш соатлари сводкаси
    """
    if not request.user.is_staff:
        return redirect('admin_login')

    settings = ScheduleSettings.get_settings()
    slots = generate_daily_slots(settings)
    lesson_slots = [s for s in slots if s['type'] == 'lesson']

    # Фильтрлар
    teacher_id = request.GET.get('teacher', '').strip()
    group_id = request.GET.get('group', '').strip()
    day_filter = request.GET.get('day', '').strip()

    # Маълумотлар базасидан дарсларни олиш
    lessons_qs = Lesson.objects.select_related('group', 'teacher').prefetch_related('group__students')

    selected_teacher = None
    if teacher_id and teacher_id.isdigit():
        lessons_qs = lessons_qs.filter(teacher_id=int(teacher_id))
        selected_teacher = Teacher.objects.filter(id=int(teacher_id)).first()

    selected_group = None
    if group_id and group_id.isdigit():
        lessons_qs = lessons_qs.filter(group_id=int(group_id))
        selected_group = Group.objects.filter(id=int(group_id)).first()

    # Жадвал кунлари (агар кун фильтри танланмаган бўлса, ҳамма 7 кун)
    active_days = DAYS_LIST
    if day_filter != '' and day_filter.isdigit():
        d_idx = int(day_filter)
        active_days = [d for d in DAYS_LIST if d[0] == d_idx]

    # Жадвал матрицасини қуриш
    timetable_rows = []
    all_lessons = list(lessons_qs)

    for slot in slots:
        row_cells = []
        is_break = (slot['type'] == 'break')

        for day_tuple in active_days:
            day_idx = day_tuple[0]

            if is_break:
                row_cells.append({
                    'type': 'break',
                    'day_idx': day_idx,
                    'label': f"☕ Перерыв ({slot['duration_min']} мин)",
                    'start_str': slot['start_str'],
                    'end_str': slot['end_str'],
                })
            else:
                # Дарсни қидириш
                matched_lesson = None
                for les in all_lessons:
                    if les.day_of_week == day_idx and les.start_time.strftime('%H:%M') == slot['start_str']:
                        matched_lesson = les
                        break

                if matched_lesson:
                    row_cells.append({
                        'type': 'busy',
                        'day_idx': day_idx,
                        'lesson': matched_lesson,
                        'group': matched_lesson.group,
                        'teacher': matched_lesson.teacher,
                        'room': matched_lesson.room or 'Кабинет кўрсатилмаган',
                        'students_count': matched_lesson.group.students.filter(is_active=True).count(),
                        'start_str': slot['start_str'],
                        'end_str': slot['end_str'],
                    })
                else:
                    row_cells.append({
                        'type': 'free',
                        'day_idx': day_idx,
                        'day_name': day_tuple[1],
                        'start_str': slot['start_str'],
                        'end_str': slot['end_str'],
                        'label': 'Свободно',
                    })

        timetable_rows.append({
            'slot': slot,
            'is_break': is_break,
            'cells': row_cells,
        })

    # Сводка (Availability Summary)
    teachers = Teacher.objects.filter(is_active=True).order_by('full_name')
    groups = Group.objects.filter(is_active=True).select_related('teacher').order_by('name')

    total_lessons_week = Lesson.objects.count()
    total_slots_per_week = len(lesson_slots) * 7
    slot_hours = settings.lesson_duration / 60.0

    if selected_teacher:
        availability = calculate_teacher_availability(selected_teacher, settings)
    else:
        # Умумий марказ статистикаси
        total_teacher_lessons = lessons_qs.count()
        teacher_count = max(1, teachers.count())
        possible_slots_all = total_slots_per_week * teacher_count
        free_slots_all = max(0, possible_slots_all - total_teacher_lessons)
        availability = {
            'total_lessons': total_teacher_lessons,
            'busy_hours': round(total_teacher_lessons * slot_hours, 1),
            'free_slots': free_slots_all,
            'free_hours': round(free_slots_all * slot_hours, 1),
            'total_possible_slots': possible_slots_all,
        }

    context = {
        'active_tab': 'schedule',
        'settings': settings,
        'slots': slots,
        'lesson_slots': lesson_slots,
        'days': active_days,
        'all_days': DAYS_LIST,
        'timetable_rows': timetable_rows,
        'teachers': teachers,
        'groups': groups,
        'selected_teacher': selected_teacher,
        'selected_group': selected_group,
        'selected_teacher_id': teacher_id,
        'selected_group_id': group_id,
        'selected_day': day_filter,
        'availability': availability,
        'total_lessons_week': total_lessons_week,
        'total_teachers_count': teachers.count(),
        'total_groups_count': groups.count(),
        'active_tab': 'schedule',
    }
    return render(request, 'dashboard/schedule.html', context)


@login_required(login_url='admin_login')
def schedule_teachers_view(request):
    """
    Ўқитувчилар рўйхати ва бошқаруви (Add / Edit / Delete):
    - Ҳар бир ўқитувчининг ҳафталик дарс ва бўш соатлари
    - Ўқитувчининг гуруҳлари
    """
    if not request.user.is_staff:
        return redirect('admin_login')

    settings = ScheduleSettings.get_settings()

    # 1. Янги ўқитувчи қўшиш
    if request.method == 'POST' and 'add_teacher' in request.POST:
        full_name = request.POST.get('full_name', '').strip()
        phone = request.POST.get('phone', '').strip()
        subjects = request.POST.get('subjects', '').strip()
        color = request.POST.get('color', '#2563eb').strip()
        notes = request.POST.get('notes', '').strip()

        if full_name:
            t = Teacher.objects.create(
                full_name=full_name,
                phone=phone,
                subjects=subjects,
                color=color or '#2563eb',
                notes=notes,
                is_active=True
            )
            messages.success(request, f"Преподаватель «{t.full_name}» успешно добавлен!")
        return redirect('dashboard_teachers')

    # 2. Ўқитувчини таҳрирлаш
    if request.method == 'POST' and 'edit_teacher' in request.POST:
        t_id = request.POST.get('teacher_id')
        teacher = Teacher.objects.filter(id=t_id).first()
        if teacher:
            teacher.full_name = request.POST.get('full_name', '').strip()
            teacher.phone = request.POST.get('phone', '').strip()
            teacher.subjects = request.POST.get('subjects', '').strip()
            teacher.color = request.POST.get('color', '#2563eb').strip()
            teacher.notes = request.POST.get('notes', '').strip()
            teacher.save()
            messages.success(request, f"Данные преподавателя «{teacher.full_name}» обновлены!")
        return redirect('dashboard_teachers')

    # 3. Ўқитувчи ҳолатини ўзгартириш (Toggle Active)
    toggle_id = request.GET.get('toggle')
    if toggle_id:
        t = Teacher.objects.filter(id=toggle_id).first()
        if t:
            t.is_active = not t.is_active
            t.save()
            messages.success(request, f"Статус преподавателя «{t.full_name}» изменен.")
        return redirect('dashboard_teachers')

    # 4. Ўқитувчини ўчириш
    delete_id = request.GET.get('delete')
    if delete_id:
        t = Teacher.objects.filter(id=delete_id).first()
        if t:
            name = t.full_name
            t.delete()
            messages.success(request, f"Преподаватель «{name}» удален.")
        return redirect('dashboard_teachers')

    # Ўқитувчилар рўйхати ва уларнинг ҳафталик статистикаси
    teachers = Teacher.objects.all().prefetch_related('groups', 'lessons')
    teachers_data = []
    for t in teachers:
        stats = calculate_teacher_availability(t, settings)
        teachers_data.append({
            'teacher': t,
            'stats': stats,
            'groups_count': t.groups.filter(is_active=True).count(),
        })

    context = {
        'active_tab': 'teachers',
        'teachers_data': teachers_data,
        'total_teachers': teachers.count(),
        'active_teachers': teachers.filter(is_active=True).count(),
    }
    return render(request, 'dashboard/teachers.html', context)


@login_required(login_url='admin_login')
def schedule_groups_view(request):
    """
    Гуруҳлар саҳифаси (Groups page):
    - Гуруҳ яратиш, таҳрирлаш, ўчириш
    - Ўқитувчини бириктириш
    - Ўқувчилар қўшиш / ўчириш
    - Гуруҳни ҳафта куни ва вақт слотига дарс сифатида бириктириш
    """
    if not request.user.is_staff:
        return redirect('admin_login')

    settings = ScheduleSettings.get_settings()
    lesson_slots = get_lesson_only_slots(settings)
    teachers = Teacher.objects.filter(is_active=True)

    # 1. Янги гуруҳ яратиш
    if request.method == 'POST' and 'create_group' in request.POST:
        name = request.POST.get('name', '').strip()
        subject = request.POST.get('subject', '').strip()
        teacher_id = request.POST.get('teacher_id')
        color = request.POST.get('color', '#3b82f6').strip()

        teacher = Teacher.objects.filter(id=teacher_id).first() if teacher_id else None
        if name and subject:
            grp = Group.objects.create(
                name=name,
                subject=subject,
                teacher=teacher,
                color=color or '#3b82f6',
                is_active=True
            )
            messages.success(request, f"Группа «{grp.name}» успешно создана!")
        return redirect('dashboard_groups')

    # 2. Гуруҳни таҳрирлаш
    if request.method == 'POST' and 'edit_group' in request.POST:
        g_id = request.POST.get('group_id')
        grp = Group.objects.filter(id=g_id).first()
        if grp:
            grp.name = request.POST.get('name', '').strip()
            grp.subject = request.POST.get('subject', '').strip()
            teacher_id = request.POST.get('teacher_id')
            grp.teacher = Teacher.objects.filter(id=teacher_id).first() if teacher_id else None
            grp.color = request.POST.get('color', '#3b82f6').strip()
            grp.save()
            messages.success(request, f"Данные группы «{grp.name}» обновлены!")
        return redirect('dashboard_groups')

    # 3. Гуруҳга ўқувчи қўшиш
    if request.method == 'POST' and 'add_student' in request.POST:
        g_id = request.POST.get('group_id')
        st_name = request.POST.get('student_name', '').strip()
        st_phone = request.POST.get('student_phone', '').strip()

        grp = Group.objects.filter(id=g_id).first()
        if grp and st_name:
            Student.objects.create(
                group=grp,
                full_name=st_name,
                phone=st_phone,
                is_active=True
            )
            messages.success(request, f"Студент «{st_name}» добавлен в группу {grp.name}!")
        return redirect('dashboard_groups')

    # 4. Ўқувчини гуруҳдан ўчириш
    delete_student_id = request.GET.get('delete_student')
    if delete_student_id:
        st = Student.objects.filter(id=delete_student_id).first()
        if st:
            grp_name = st.group.name
            st_name = st.full_name
            st.delete()
            messages.success(request, f"Студент «{st_name}» удален из группы {grp_name}.")
        return redirect('dashboard_groups')

    # 5. Гуруҳни кун ва вақт слотига бириктириш (Assign schedule slot)
    if request.method == 'POST' and 'assign_slot' in request.POST:
        g_id = request.POST.get('group_id')
        day_of_week = int(request.POST.get('day_of_week', 0))
        slot_str = request.POST.get('slot_time', '')
        room = request.POST.get('room', '').strip()

        grp = Group.objects.filter(id=g_id).first()
        if grp:
            if not grp.teacher:
                messages.error(request, f"Ошибка! Для группы «{grp.name}» сначала должен быть назначен преподаватель.")
                return redirect('dashboard_groups')

            if slot_str and '-' in slot_str:
                s_part, e_part = slot_str.split('-')
                start_t = parse_time_str(s_part.strip())
                end_t = parse_time_str(e_part.strip())

                # Конфликт текшируви
                has_conflict, err_msg = check_lesson_conflict(
                    teacher_id=grp.teacher_id,
                    group_id=grp.id,
                    day_of_week=day_of_week,
                    start_time=start_t,
                    end_time=end_t
                )
                if has_conflict:
                    messages.error(request, err_msg)
                else:
                    Lesson.objects.create(
                        group=grp,
                        teacher=grp.teacher,
                        day_of_week=day_of_week,
                        start_time=start_t,
                        end_time=end_t,
                        room=room
                    )
                    messages.success(request, f"Урок для группы «{grp.name}» успешно добавлен в расписание!")
        return redirect('dashboard_groups')

    # 6. Гуруҳни ўчириш
    delete_group_id = request.GET.get('delete_group')
    if delete_group_id:
        grp = Group.objects.filter(id=delete_group_id).first()
        if grp:
            g_name = grp.name
            grp.delete()
            messages.success(request, f"Группа «{g_name}» удалена.")
        return redirect('dashboard_groups')

    groups = Group.objects.all().select_related('teacher').prefetch_related('students', 'lessons').order_by('-is_active', 'name')

    context = {
        'active_tab': 'groups',
        'groups': groups,
        'teachers': teachers,
        'lesson_slots': lesson_slots,
        'days': DAYS_LIST,
        'total_groups': groups.count(),
        'total_students': Student.objects.filter(is_active=True).count(),
    }
    return render(request, 'dashboard/groups.html', context)


@login_required(login_url='admin_login')
def schedule_settings_view(request):
    """
    Жадвал ва вақт қоидалари созламаси (Settings Page):
    - Иш куни бошланиши (масалан: 08:00)
    - Иш куни тугаши (масалан: 20:00)
    - Дарс давомийлиги (70 дақиқа)
    - Танаффус давомийлиги (60 дақиқа)
    Созламалар ўзгартирилганда барча кунлик слотлар автомат қайта ҳисобланади.
    """
    if not request.user.is_staff:
        return redirect('admin_login')

    settings = ScheduleSettings.get_settings()

    if request.method == 'POST':
        day_start_str = request.POST.get('day_start', '08:00').strip()
        day_end_str = request.POST.get('day_end', '20:00').strip()
        try:
            lesson_dur = int(request.POST.get('lesson_duration', 70))
            break_dur = int(request.POST.get('break_duration', 60))
        except ValueError:
            lesson_dur = 70
            break_dur = 60

        try:
            settings.day_start = parse_time_str(day_start_str)
            settings.day_end = parse_time_str(day_end_str)
            settings.lesson_duration = max(20, min(180, lesson_dur))
            settings.break_duration = max(0, min(120, break_dur))
            settings.save()
            messages.success(request, "Настройки расписания успешно сохранены! Сетка уроков автоматически пересчитана.")
        except Exception as e:
            messages.error(request, f"Ошибка при сохранении: {e}")

        return redirect('dashboard_schedule_settings')

    # Ҳозирги ҳисобланган слотлар превьюси
    slots_preview = generate_daily_slots(settings)

    context = {
        'active_tab': 'schedule_settings',
        'settings': settings,
        'slots_preview': slots_preview,
    }
    return render(request, 'dashboard/schedule_settings.html', context)


@login_required(login_url='admin_login')
def api_create_lesson_view(request):
    """
    AJAX орқали бўш (Free) слотга тезкор дарс қўшиш (Quick Slot Booking)
    Ва Конфликтларни олдини олиш (Conflict Prevention).
    """
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Доступ запрещен'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Метод POST талаб этилади'}, status=405)

    import json
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    group_id = data.get('group_id')
    teacher_id = data.get('teacher_id')
    day_of_week = data.get('day_of_week')
    start_time_str = data.get('start_time', '').strip()
    end_time_str = data.get('end_time', '').strip()
    room = data.get('room', '').strip()

    if not group_id or day_of_week is None or not start_time_str or not end_time_str:
        return JsonResponse({'success': False, 'error': 'Пожалуйста, заполните все обязательные поля (Группа, День, Время)'}, status=400)

    group = Group.objects.filter(id=group_id).first()
    if not group:
        return JsonResponse({'success': False, 'error': 'Группа не найдена'}, status=404)

    # Агар ўқитувчи кўрсатилмаган бўлса, гуруҳга бириктирилган ўқитувчини олиш
    if teacher_id:
        teacher = Teacher.objects.filter(id=teacher_id).first()
    else:
        teacher = group.teacher

    if not teacher:
        return JsonResponse({'success': False, 'error': 'Для урока необходимо указать преподавателя или закрепить его за группой'}, status=400)

    day_of_week = int(day_of_week)
    start_time = parse_time_str(start_time_str)
    end_time = parse_time_str(end_time_str)

    # КОНФЛИКТНИ ТЕКШИРИШ
    has_conflict, error_msg = check_lesson_conflict(
        teacher_id=teacher.id,
        group_id=group.id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time
    )

    if has_conflict:
        return JsonResponse({
            'success': False,
            'is_conflict': True,
            'error': error_msg
        }, status=409)

    lesson = Lesson.objects.create(
        group=group,
        teacher=teacher,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        room=room
    )

    return JsonResponse({
        'success': True,
        'message': f"Урок успешно назначен! Группа: {group.name}, Преподаватель: {teacher.full_name}",
        'lesson': {
            'id': lesson.id,
            'group_name': group.name,
            'subject': group.subject,
            'teacher_name': teacher.full_name,
            'room': lesson.room or '',
            'day': day_of_week,
            'start': start_time.strftime('%H:%M'),
            'end': end_time.strftime('%H:%M')
        }
    })


@login_required(login_url='admin_login')
def api_delete_lesson_view(request, lesson_id):
    """Дарсни жадвалдан ўчириш"""
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Доступ запрещен'}, status=403)

    lesson = Lesson.objects.filter(id=lesson_id).first()
    if not lesson:
        return JsonResponse({'success': False, 'error': 'Урок не найден'}, status=404)

    group_name = lesson.group.name
    lesson.delete()
    return JsonResponse({
        'success': True,
        'message': f"Урок для группы «{group_name}» удален из расписания"
    })


@login_required(login_url='admin_login')
def api_edit_lesson_view(request, lesson_id):
    """Дарс аудиторияси ёки маълумотларини таҳрирлаш"""
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Доступ запрещен'}, status=403)

    lesson = Lesson.objects.filter(id=lesson_id).first()
    if not lesson:
        return JsonResponse({'success': False, 'error': 'Урок не найден'}, status=404)

    import json
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        data = request.POST

    new_room = data.get('room', '').strip()
    new_teacher_id = data.get('teacher_id')

    if new_teacher_id and int(new_teacher_id) != lesson.teacher_id:
        # Янги ўқитувчи бўйича конфликт текшируви
        has_conflict, error_msg = check_lesson_conflict(
            teacher_id=int(new_teacher_id),
            group_id=lesson.group_id,
            day_of_week=lesson.day_of_week,
            start_time=lesson.start_time,
            end_time=lesson.end_time,
            exclude_lesson_id=lesson.id
        )
        if has_conflict:
            return JsonResponse({'success': False, 'error': error_msg}, status=409)

        new_t = Teacher.objects.filter(id=new_teacher_id).first()
        if new_t:
            lesson.teacher = new_t

    lesson.room = new_room
    lesson.save()

    return JsonResponse({
        'success': True,
        'message': 'Данные урока успешно обновлены'
    })


@login_required(login_url='admin_login')
def schedule_export_view(request):
    """Жадвални CSV / Excel форматида юклаб олиш (Export Schedule)"""
    if not request.user.is_staff:
        return redirect('admin_login')

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="teacher_schedule.csv"'

    writer = csv.writer(response)
    writer.writerow(['День недели', 'Время начала', 'Время окончания', 'Группа', 'Предмет', 'Преподаватель', 'Телефон преподавателя', 'Аудитория', 'Кол-во студентов'])

    day_map = {d[0]: d[1] for d in DAYS_LIST}
    lessons = Lesson.objects.select_related('group', 'teacher').prefetch_related('group__students').order_by('day_of_week', 'start_time')

    for les in lessons:
        writer.writerow([
            day_map.get(les.day_of_week, ''),
            les.start_time.strftime('%H:%M'),
            les.end_time.strftime('%H:%M'),
            les.group.name,
            les.group.subject,
            les.teacher.full_name,
            les.teacher.phone,
            les.room or '-',
            les.group.students.filter(is_active=True).count()
        ])

    return response


# ========================================================
# INSTAGRAM DM ИНТЕГРАЦИЯСИ — VIEWS (META API)
# ========================================================
from .instagram import (
    build_oauth_url,
    exchange_code_for_token,
    process_instagram_webhook,
    send_instagram_reply,
    get_instagram_status,
    disconnect_instagram,
    verify_webhook_signature,
    get_app_config,
    get_instagram_settings,
    refresh_long_lived_token,
    login_with_credentials,
    verify_two_factor_code,
)
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse


@login_required(login_url='admin_login')
def instagram_dashboard_view(request):
    """Instagram бошқарув панели (OAuth уланиш, ҳолат, webhook йўриқномаси)"""
    if not request.user.is_staff:
        return redirect('admin_login')

    ig_settings = get_instagram_settings()
    cfg = get_app_config()

    # Созламаларни POST орқали сақлаш (App ID, Secret, Verify Token, Redirect URI)
    if request.method == 'POST' and 'save_credentials' in request.POST:
        ig_settings.app_id = request.POST.get('app_id', '').strip()
        ig_settings.app_secret = request.POST.get('app_secret', '').strip()
        ig_settings.verify_token = request.POST.get('verify_token', '').strip() or 'edu_center_ig_verify_2026'
        ig_settings.redirect_uri = request.POST.get('redirect_uri', '').strip()
        ig_settings.save()
        messages.success(request, "Instagram Meta API маълумотлари муваффақиятли сақланди!")
        return redirect('dashboard_instagram')

    # Сервернинг тўлиқ URL'лари
    host = request.get_host()
    scheme = 'https' if request.is_secure() or 'localhost' not in host else 'http'
    default_redirect = f"{scheme}://{host}/instagram/oauth/callback/"
    webhook_callback_url = f"{scheme}://{host}/api/instagram/webhook/"

    # Агар redirect_uri бўш бўлса — автомат тўлдирамиз
    if not ig_settings.redirect_uri:
        ig_settings.redirect_uri = default_redirect
        ig_settings.save(update_fields=['redirect_uri'])

    status_data = get_instagram_status()

    # OAuth бошлаш URL'и (агар app_id бўлса)
    oauth_url = None
    if ig_settings.app_id or cfg.get('app_id'):
        try:
            oauth_url = build_oauth_url()
        except Exception:
            oauth_url = None

    # Охирги хабарлар
    recent_messages = InstagramMessage.objects.order_by('-timestamp')[:20]

    context = {
        'ig_settings': ig_settings,
        'status_data': status_data,
        'oauth_url': oauth_url,
        'default_redirect': default_redirect,
        'webhook_callback_url': webhook_callback_url,
        'recent_messages': recent_messages,
    }
    return render(request, 'dashboard/instagram.html', context)


@login_required(login_url='admin_login')
def instagram_oauth_redirect_view(request):
    """
    Фойдаланувчини Meta OAuth саҳифасига йўналтириш.
    """
    if not request.user.is_staff:
        return redirect('admin_login')

    try:
        url = build_oauth_url()
        return redirect(url)
    except Exception as exc:
        messages.error(request, f"OAuth URL яратишда хатолик: {exc}")
        return redirect('dashboard_instagram')


def instagram_oauth_callback_view(request):
    """
    Meta OAuth қайтариш (Callback) endpoint'и.
    Meta'дан келган authorization code'ни қабул қилади ва
    узоқ умрли токенга алмаштиради.
    """
    error = request.GET.get('error')
    error_desc = request.GET.get('error_description') or request.GET.get('error_reason', '')

    if error:
        messages.error(request, f"Instagram уланишда хатолик: {error_desc or error}")
        return redirect('dashboard_instagram')

    code = request.GET.get('code')
    if not code:
        messages.error(request, "Авторизация коди олинмади.")
        return redirect('dashboard_instagram')

    # '#' белгисини тозалаш (Meta баъзан url охирига #_ қўшади)
    clean_code = code.split('#_')[0]

    result = exchange_code_for_token(clean_code)
    if result.get('success'):
        ig_user = result.get('ig_username') or result.get('ig_user_id')
        messages.success(request, f"Instagram аккаунти муваффақиятли уланди: @{ig_user}! 🎉")
    else:
        err = result.get('error', 'Номаълум хатолик')
        messages.error(request, f"Токен олишда хатолик: {err}")

    return redirect('dashboard_instagram')


@csrf_exempt
def instagram_webhook_view(request):
    """
    Instagram Webhook endpoint (GET verify + POST DM events).

    GET: Meta 'hub.mode=subscribe&hub.challenge=...&hub.verify_token=...'
         => challenge'ni plain text qaytarish.

    POST: X-Hub-Signature-256 bilan kelgan kiruvchi DM xabarlari.
         => DARHOL 200 qaytarish (Meta 5 soniya ichida 200 kutadi!)
         => Keyin xabarni qayta ishlash.
    """
    import json as json_lib

    # ── 1. GET: Webhook Verification ──
    if request.method == 'GET':
        mode = request.GET.get('hub.mode', '')
        token = request.GET.get('hub.verify_token', '')
        challenge = request.GET.get('hub.challenge', '')

        cfg = get_app_config()
        ig_settings = get_instagram_settings()
        expected_token = ig_settings.verify_token or cfg.get('verify_token') or 'edu_center_ig_verify_2026'

        logger.info("[Instagram Webhook] GET verify: mode=%s, token=%s, challenge=%s",
                    mode, token[:10] if token else '', challenge[:10] if challenge else '')

        if mode == 'subscribe' and token == expected_token:
            logger.info("[Instagram Webhook] ✅ Verify muvaffaqiyatli! Challenge qaytarilmoqda.")
            return HttpResponse(challenge, content_type="text/plain; charset=utf-8", status=200)
        else:
            logger.error("[Instagram Webhook] ❌ Verify xatosi! expected_token=%s, got=%s",
                         expected_token[:10], token[:10] if token else 'EMPTY')
            return HttpResponse("Forbidden: verify token mismatch", content_type="text/plain", status=403)

    # ── 2. POST: Inbound DM Event ──
    if request.method == 'POST':
        raw_body = request.body  # raw bytes - signature uchun

        # Signature tekshiruvi (raw body ustida)
        sig_header = request.headers.get('X-Hub-Signature-256', '')
        cfg = get_app_config()
        if cfg.get('app_secret'):
            sig_ok = verify_webhook_signature(raw_body, sig_header)
            if not sig_ok:
                logger.error("[Instagram Webhook] ❌ Imzo muvofiq emas! Rad etildi.")
                # Lekin 200 qaytaramiz - Meta qayta yubormasin uchun
                return HttpResponse("OK", status=200)
        else:
            logger.warning("[Instagram Webhook] App Secret yo'q - imzo tekshirilmadi (dev mode)")

        try:
            payload = json_lib.loads(raw_body.decode('utf-8'))
        except Exception as exc:
            logger.error("[Instagram Webhook] JSON decode xatosi: %s", exc)
            return HttpResponse("OK", status=200)  # Meta'ga 200 qaytaramiz

        obj_type = payload.get('object', 'unknown')
        entries = payload.get('entry', [])
        logger.info("[Instagram Webhook] >>> POST keldi: object=%s, %d entry", obj_type, len(entries))

        # Har bir entry va messaging'ni logga yozamiz
        for entry in entries:
            msgs = entry.get('messaging', [])
            changes = entry.get('changes', [])
            logger.info("[Instagram Webhook] entry_id=%s, %d messaging, %d changes",
                        entry.get('id', '?'), len(msgs), len(changes))
            for msg_event in msgs:
                sender = msg_event.get('sender', {}).get('id', '?')
                msg_text = msg_event.get('message', {}).get('text', '[media/other]')
                logger.info("[Instagram Webhook] MSG: sender=%s => '%s'", sender, msg_text[:60])

        # DARHOL 200 qaytaramiz (Meta 5s kutadi!)
        # Process event (creates LeadApplication and InstagramMessage)
        try:
            res = process_instagram_webhook(payload)
            logger.info("[Instagram Webhook] <<< Qayta ishlandi: %s", res)
        except Exception as exc:
            import traceback
            logger.error("[Instagram Webhook] Qayta ishlashda xatolik: %s\n%s", exc, traceback.format_exc())

        return HttpResponse("EVENT_RECEIVED", status=200)

    return HttpResponse("Method Not Allowed", status=405)


@require_POST
@login_required(login_url='admin_login')
def api_instagram_disconnect_view(request):
    """Instagram аккаунтини узиш"""
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    disconnect_instagram()
    return JsonResponse({'ok': True, 'message': 'Instagram аккаунти узилди'})


def api_instagram_status_view(request):
    """Instagram ҳолатини JSON кўринишида олиш"""
    status_data = get_instagram_status()
    return JsonResponse({'ok': True, 'status': status_data})


@require_POST
@login_required(login_url='admin_login')
def api_instagram_send_reply_view(request):
    """
    Админ / Менеджер Kanban доскасидан Instagram мижозга жавоб ёзиши.
    POST: lead_id ёки igsid, message
    """
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    lead_id = request.POST.get('lead_id', '').strip()
    recipient_igsid = request.POST.get('igsid', '').strip() or request.POST.get('recipient_id', '').strip()
    text = request.POST.get('message', '').strip()

    if not text:
        return JsonResponse({'ok': False, 'error': 'Хабар матни бўш бўлиши мумкин эмас'}, status=400)

    if not recipient_igsid and lead_id:
        lead = LeadApplication.objects.filter(id=lead_id).first()
        if lead and lead.instagram_igsid:
            recipient_igsid = lead.instagram_igsid

    if not recipient_igsid:
        return JsonResponse({'ok': False, 'error': 'Мижознинг Instagram ID (IGSID) топилмади'}, status=400)

    result = send_instagram_reply(recipient_igsid, text)
    if result.get('success'):
        # Лид маълумотларини янгилаш
        if lead_id:
            lead = LeadApplication.objects.filter(id=lead_id).first()
            if lead:
                prev = lead.message or ''
                lead.message = (prev + f"\n\n[IG Жавоб бердингиз]: {text}").strip() if prev else f"[IG Жавоб бердингиз]: {text}"
                lead.status = 'contacted'
                lead.save(update_fields=['message', 'status'])

        return JsonResponse({
            'ok': True,
            'message_id': result.get('message_id'),
            'message': 'Хабар Instagram орқали мижозга юборилди! ✅'
        })
    else:
        return JsonResponse({
            'ok': False,
            'error': result.get('error', 'Хабар юборишда хатолик'),
            'window_expired': result.get('window_expired', False),
        }, status=400)


@require_POST
@login_required(login_url='admin_login')
def api_instagram_simulate_view(request):
    """
    Instagram симуляция хабари (тест қилиш учун).
    Сайт админи реал Meta Webhook'сиз ҳам хабар қабул қилиш тизимини синаб кўриши мумкин.
    """
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    igsid = request.POST.get('igsid', 'test_user_9989').strip()
    text = request.POST.get('text', 'Ассалому алайкум, курслар нархи қанча?').strip()

    mock_payload = {
        "object": "instagram",
        "entry": [{
            "id": "mock_page_id",
            "time": int(timezone.now().timestamp()),
            "messaging": [{
                "sender": {"id": igsid},
                "recipient": {"id": "mock_page_id"},
                "timestamp": int(timezone.now().timestamp() * 1000),
                "message": {
                    "mid": f"mid_sim_{int(timezone.now().timestamp())}",
                    "text": text,
                }
            }]
        }]
    }

    res = process_instagram_webhook(mock_payload)
    return JsonResponse({'ok': True, 'result': res, 'simulated_igsid': igsid, 'text': text})


@require_POST
@login_required(login_url='admin_login')
def api_instagram_login_view(request):
    """
    Instagram'ga username + parol orqali to'g'ridan-to'g'ri kirish (instagrapi).
    AJAX POST: {username, password}
    """
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Ruxsat yo\'q'}, status=403)

    username = request.POST.get('ig_username', '').strip()
    password = request.POST.get('ig_password', '').strip()

    if not username or not password:
        return JsonResponse({'ok': False, 'error': 'Username va parol kiritilishi shart'}, status=400)

    result = login_with_credentials(username, password)

    if result.get('success'):
        return JsonResponse({
            'ok': True,
            'ig_username': result['ig_username'],
            'ig_user_id': result['ig_user_id'],
            'message': f"✅ @{result['ig_username']} muvaffaqiyatli ulandi!",
        })
    else:
        return JsonResponse({
            'ok': False,
            'error': result.get('error', 'Noma\'lum xatolik'),
            'challenge_required': result.get('challenge_required', False),
            'two_factor_required': result.get('two_factor_required', False),
            'two_factor_identifier': result.get('two_factor_identifier', ''),
            'cl_settings': result.get('cl_settings', '{}'),
            'username': result.get('username', username),
        }, status=400)


@require_POST
@login_required(login_url='admin_login')
def api_instagram_verify_2fa_view(request):
    """
    Instagram 2FA tasdiqlash kodi tekshirish.
    POST: ig_username, ig_password, ig_code, two_factor_identifier, cl_settings
    """
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Ruxsat yo\'q'}, status=403)

    username = request.POST.get('ig_username', '').strip()
    password = request.POST.get('ig_password', '').strip()
    code = request.POST.get('ig_code', '').strip()
    two_factor_identifier = request.POST.get('two_factor_identifier', '').strip()
    cl_settings_str = request.POST.get('cl_settings', '{}').strip()

    if not code:
        return JsonResponse({'ok': False, 'error': 'Tasdiqlash kodini kiriting'}, status=400)

    result = verify_two_factor_code(
        username=username,
        password=password,
        code=code,
        two_factor_identifier=two_factor_identifier,
        cl_settings_str=cl_settings_str,
    )

    if result.get('success'):
        return JsonResponse({
            'ok': True,
            'ig_username': result['ig_username'],
            'ig_user_id': result['ig_user_id'],
            'message': f"✅ @{result['ig_username']} muvaffaqiyatli ulandi!",
        })
    else:
        return JsonResponse({
            'ok': False,
            'error': result.get('error', 'Noma\'lum xatolik'),
            'challenge_required': result.get('challenge_required', False),
        }, status=400)


@require_POST
@login_required(login_url='admin_login')
def api_instagram_sync_view(request):
    """
    'Xabarlarni tekshirish (Kanban)' tugmasi.
    1. META OAuth token bo'lsa: Conversations API orqali tortib olish (eng ishonchli)
    2. SESSION token bo'lsa: instagrapi direct polling
    3. Subscription holatini ham tekshiradi va qayta urinadi
    """
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Ruxsat yo\'q'}, status=403)

    from .instagram import (
        fetch_and_process_instagram_messages,
        fetch_conversations_via_api,
        subscribe_to_messages,
        check_webhook_subscription,
    )

    ig_settings = get_instagram_settings()
    token = ig_settings.access_token or ''
    is_session = token.startswith('SESSION:')

    result = {}
    subscription_status = {}

    if not is_session and token:
        # Meta OAuth token mavjud - Conversations API ishlatamiz
        result = fetch_conversations_via_api(ig_settings)

        # Subscription holatini ham tekshiramiz
        try:
            subscription_status = check_webhook_subscription(ig_settings)
            if not subscription_status.get('subscribed'):
                # Obuna yo'q - qayta urinib ko'ramiz
                logger.info('[Instagram Sync] Subscription yo\'q - qayta subscribe qilinmoqda...')
                sub_res = subscribe_to_messages(ig_settings)
                subscription_status['resubscribed'] = sub_res.get('success', False)
                subscription_status['resubscribe_detail'] = sub_res
        except Exception as sub_exc:
            subscription_status = {'error': str(sub_exc)}

    else:
        # SESSION token yoki token yo'q - instagrapi polling
        result = fetch_and_process_instagram_messages(force=True)
        try:
            from .instagram import fetch_and_process_instagram_comments
            comment_res = fetch_and_process_instagram_comments(force=True)
            result['comments'] = comment_res
        except Exception as ce:
            result['comments_error'] = str(ce)

    return JsonResponse({
        'ok': True,
        'result': result,
        'subscription': subscription_status,
        'mode': 'conversations_api' if (not is_session and token) else 'instagrapi_polling'
    })


@login_required(login_url='admin_login')
def api_instagram_comments_sync_view(request):
    """Instagram post/reels коментарияларини зудлик билан синхронизация қилиш"""
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    from .instagram import fetch_and_process_instagram_comments
    result = fetch_and_process_instagram_comments(force=True)
    return JsonResponse({'ok': True, 'result': result})


@require_POST
@login_required(login_url='admin_login')
def api_instagram_subscribe_view(request):
    """Instagram 'messages' webhook subscription'ni yoqish yoki tekshirish."""
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Ruxsat yo\'q'}, status=403)

    from .instagram import subscribe_to_messages, check_webhook_subscription

    action = request.POST.get('action', 'subscribe')  # 'subscribe' yoki 'check'
    ig_settings = get_instagram_settings()

    if action == 'check':
        result = check_webhook_subscription(ig_settings)
        return JsonResponse({'ok': True, 'subscription': result})
    else:
        result = subscribe_to_messages(ig_settings)
        return JsonResponse({
            'ok': result.get('success', False),
            'message': '✅ Webhook messages subscription yoqildi!' if result.get('success') else '❌ Xatolik',
            'result': result
        })


@require_POST
@login_required(login_url='admin_login')
def api_instagram_update_stats_view(request):
    """Instagram профил статистикасини сақлаш ёки янгилаш"""
    if not request.user.is_staff:
        return JsonResponse({'ok': False, 'error': 'Рухсат йўқ'}, status=403)

    ig = get_instagram_settings()

    followers = request.POST.get('followers_count')
    following = request.POST.get('following_count')
    posts = request.POST.get('media_count')
    full_name = request.POST.get('full_name')
    pic_url = request.POST.get('profile_pic_url')
    bio = request.POST.get('bio')

    if followers is not None and followers != '':
        try:
            ig.followers_count = max(0, int(followers))
        except ValueError:
            pass
    if following is not None and following != '':
        try:
            ig.following_count = max(0, int(following))
        except ValueError:
            pass
    if posts is not None and posts != '':
        try:
            ig.media_count = max(0, int(posts))
        except ValueError:
            pass
    if full_name is not None:
        ig.full_name = full_name.strip()
    if pic_url is not None:
        ig.profile_pic_url = pic_url.strip()
    if bio is not None:
        ig.bio = bio.strip()

    ig.save()

    return JsonResponse({
        'ok': True,
        'message': 'Профиль маълумотлари муваффақиятли сақланди! ✅',
        'stats': {
            'username': ig.ig_username,
            'full_name': ig.full_name,
            'followers_count': ig.followers_count,
            'following_count': ig.following_count,
            'media_count': ig.media_count,
            'profile_pic_url': ig.profile_pic_url,
            'bio': ig.bio,
        }
    })


