from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('course/<slug:slug>/', views.course_detail_view, name='course_detail'),
    path('submit-lead/', views.submit_lead_view, name='submit_lead'),
    path('api/b24-status/', views.check_b24_status_view, name='b24_status'),
    
    # Шахсий Админ Кабинет (Джанго админкасиз!)
    path('dashboard/login/', views.custom_admin_login_view, name='admin_login'),
    path('dashboard/', views.custom_admin_dashboard_view, name='admin_dashboard'),
    path('dashboard/logout/', views.custom_admin_logout_view, name='admin_logout'),

    # WhatsApp API & Webhook
    path('api/wa-status/', views.check_wa_status_view, name='wa_status'),
    path('api/wa-start/', views.api_wa_start_view, name='wa_start'),
    path('api/wa-send/', views.send_wa_message_view, name='wa_send'),
    path('api/wa-logout/', views.logout_wa_view, name='wa_logout'),
    path('api/whatsapp/webhook/', views.whatsapp_webhook_view, name='wa_webhook'),

    # Telegram Интеграцияси & QR-код
    path('dashboard/telegram/', views.telegram_dashboard_view, name='dashboard_telegram'),
    path('api/telegram/status/', views.api_telegram_status_view, name='api_telegram_status'),
    path('api/telegram/save/', views.api_telegram_save_settings_view, name='api_telegram_save'),
    path('api/telegram/test-send/', views.api_telegram_test_send_view, name='api_telegram_test_send'),
    path('api/telegram/fast-connect/', views.api_telegram_fast_connect_view, name='api_telegram_fast_connect'),
    path('api/telegram/logout/', views.api_telegram_logout_view, name='api_telegram_logout'),
    path('api/telegram/send-to-client/', views.api_telegram_send_to_client_view, name='api_telegram_send_client'),
    path('api/telegram/webhook/', views.telegram_webhook_view, name='telegram_webhook'),
    path('api/telegram/set-webhook/', views.api_telegram_set_webhook_view, name='api_telegram_set_webhook'),
    path('api/telegram/simulate/', views.api_telegram_simulate_message_view, name='telegram_simulate'),
    path('api/telegram/messages/', views.api_telegram_messages_list_view, name='api_telegram_messages_list'),
    path('api/telegram/chat/<str:chat_id>/', views.api_telegram_chat_detail_view, name='api_telegram_chat_detail'),
    path('api/telegram/reply/', views.api_telegram_reply_view, name='api_telegram_reply'),

    # Instagram DM Интеграцияси (Meta API)
    path('dashboard/instagram/', views.instagram_dashboard_view, name='dashboard_instagram'),
    path('instagram/oauth/redirect/', views.instagram_oauth_redirect_view, name='instagram_oauth_redirect'),
    path('instagram/oauth/callback/', views.instagram_oauth_callback_view, name='instagram_oauth_callback'),
    path('api/instagram/webhook/', views.instagram_webhook_view, name='instagram_webhook'),
    path('api/instagram/status/', views.api_instagram_status_view, name='api_instagram_status'),
    path('api/instagram/disconnect/', views.api_instagram_disconnect_view, name='api_instagram_disconnect'),
    path('api/instagram/reply/', views.api_instagram_send_reply_view, name='api_instagram_reply'),
    path('api/instagram/send-reply/', views.api_instagram_send_reply_view, name='api_instagram_send_reply'),
    path('api/instagram/simulate/', views.api_instagram_simulate_view, name='api_instagram_simulate'),
    path('api/instagram/login/', views.api_instagram_login_view, name='api_instagram_login'),
    path('api/instagram/verify-2fa/', views.api_instagram_verify_2fa_view, name='api_instagram_verify_2fa'),
    path('api/instagram/sync/', views.api_instagram_sync_view, name='api_instagram_sync'),
    path('api/instagram/comments-sync/', views.api_instagram_comments_sync_view, name='api_instagram_comments_sync'),
    path('api/instagram/update-stats/', views.api_instagram_update_stats_view, name='api_instagram_update_stats'),
    path('api/instagram/subscribe/', views.api_instagram_subscribe_view, name='api_instagram_subscribe'),


    # Kanban Доска
    path('dashboard/kanban/', views.kanban_board_view, name='dashboard_kanban'),
    path('api/lead/<int:lead_id>/status/', views.api_update_lead_status_view, name='api_lead_status'),
    path('api/lead/<int:lead_id>/profile/', views.api_update_lead_profile_view, name='api_lead_profile'),
    path('api/lead/create/', views.api_create_lead_view, name='api_lead_create'),
    path('api/lead/quick-test/', views.api_quick_test_lead_view, name='api_quick_test_lead'),
    path('api/leads/live/', views.api_leads_live_view, name='api_leads_live'),

    # Дарс жадвали ва Ўқитувчилар бошқаруви (Schedule Management)
    path('dashboard/schedule/', views.schedule_timetable_view, name='dashboard_schedule'),
    path('dashboard/teachers/', views.schedule_teachers_view, name='dashboard_teachers'),
    path('dashboard/groups/', views.schedule_groups_view, name='dashboard_groups'),
    path('dashboard/schedule/settings/', views.schedule_settings_view, name='dashboard_schedule_settings'),
    path('dashboard/schedule/export/', views.schedule_export_view, name='dashboard_schedule_export'),

    # Schedule AJAX APIs
    path('api/schedule/lesson/create/', views.api_create_lesson_view, name='api_schedule_create_lesson'),
    path('api/schedule/lesson/<int:lesson_id>/delete/', views.api_delete_lesson_view, name='api_schedule_delete_lesson'),
    path('api/schedule/lesson/<int:lesson_id>/edit/', views.api_edit_lesson_view, name='api_schedule_edit_lesson'),
]

