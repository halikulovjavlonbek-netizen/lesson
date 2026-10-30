import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_lead_to_bitrix24(name: str, phone: str, course_name: str, price: int = 0, message: str = "") -> dict:
    """
    Отправка лида в Битрикс24 через REST API (входящий вебхук crm.lead.add).
    Возвращает словарь с результатом (success: True/False, lead_id: ... или error).
    """
    webhook_url = getattr(settings, 'BITRIX24_WEBHOOK_URL', '')
    
    # Если вебхук пока тестовый/заглушка - логируем и возвращаем симуляцию
    if not webhook_url or 'ваш-портал' in webhook_url:
        logger.info(f"[Bitrix24 Mock] Лид успешно зафиксирован локально: {name}, {phone}, {course_name}, {price} KZT")
        return {
            'success': True,
            'mock': True,
            'lead_id': 9999,
            'message': 'Вебхук еще не настроен, лид сохранен в базе данных сайта'
        }

    # Формируем URL для вызова crm.lead.add
    endpoint = webhook_url.rstrip('/') + '/crm.lead.add.json'
    
    payload = {
        'fields': {
            'TITLE': f'Заявка с сайта: {name} ({course_name})',
            'NAME': name,
            'STATUS_ID': 'NEW', # Стадия "Новая заявка"
            'OPENED': 'Y',      # Доступен всем менеджерам очереди
            'OPPORTUNITY': price,
            'CURRENCY_ID': getattr(settings, 'DEFAULT_CURRENCY', 'KZT'),
            'SOURCE_ID': 'WEB', # Источник: Сайт
            'SOURCE_DESCRIPTION': f'Форма записи на пробный урок с сайта учебного центра',
            'PHONE': [
                {'VALUE': phone, 'VALUE_TYPE': 'WORK'}
            ],
            'COMMENTS': (
                f"<b>Выбранный курс:</b> {course_name}<br>"
                f"<b>Ориентировочная стоимость:</b> {price:,.0f} ₸<br>"
                f"<b>Сообщение клиента:</b> {message or 'Без комментария'}<br>"
                f"<b>Рабочий номер центра:</b> {getattr(settings, 'STUDY_CENTER_WHATSAPP', '+7 708 116 02 65')}"
            )
        },
        'params': {'REGISTER_SONET_EVENT': 'Y'} # Уведомить менеджеров в живой ленте/колокольчике
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=10)
        data = response.json()
        if 'result' in data:
            return {'success': True, 'lead_id': data['result']}
        else:
            logger.error(f"Bitrix24 API Error: {data}")
            return {'success': False, 'error': data.get('error_description', 'Неизвестная ошибка API')}
    except Exception as e:
        logger.exception("Ошибка при отправке запроса в Битрикс24")
        return {'success': False, 'error': str(e)}
