from django.contrib import admin
from django.utils.html import format_html
import urllib.parse
import re
from .models import Course, LeadApplication, SiteSettings, InstagramSettings, InstagramMessage

@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('whatsapp_number', 'whatsapp_clean', 'qr_preview')
    fieldsets = (
        ('WhatsApp созламалари', {
            'fields': ('whatsapp_number', 'whatsapp_clean', 'default_message', 'qr_code_display'),
            'description': 'Бу ерда кўрсатилган рақам сайтнинг барча тугмаларида ва QR-кодларида ишлайди.'
        }),
    )
    readonly_fields = ('qr_code_display',)

    def qr_preview(self, obj):
        return format_html(
            '<img src="https://api.qrserver.com/v1/create-qr-code/?size=60x60&data=https%3A%2F%2Fwa.me%2F{}" style="border-radius:6px; border:1px solid #ccc;"/>',
            obj.whatsapp_clean
        )
    qr_preview.short_description = "QR-код"

    def qr_code_display(self, obj):
        if not obj or not obj.whatsapp_clean:
            return "Аввал рақамни сақланг"
        link = f"https://wa.me/{obj.whatsapp_clean}"
        qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={urllib.parse.quote(link)}"
        return format_html(
            '<div style="text-align:left;">'
            '<img src="{}" style="border-radius:12px; border:2px solid #25D366; padding:4px;"/><br>'
            '<small style="color:#666;">Телефонингиз билан ушбу QR-кодни сканер қилиб тест қилишингиз мумкин.</small>'
            '</div>',
            qr_url
        )
    qr_code_display.short_description = "Ишчи WhatsApp QR-коди"


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'price_kzt_display', 'duration', 'badge', 'is_active', 'order')
    list_filter = ('category', 'is_active')
    search_fields = ('title', 'short_description')
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ('is_active', 'order')

    def price_kzt_display(self, obj):
        return f"{obj.price_kzt:,} ₸"
    price_kzt_display.short_description = "Ойлик нархи (₸)"


@admin.register(LeadApplication)
class LeadApplicationAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone_with_whatsapp', 'course_display', 'status', 'created_at', 'chat_btn')
    list_filter = ('status', 'course', 'created_at')
    search_fields = ('name', 'phone', 'message', 'course_name_custom')
    readonly_fields = ('created_at', 'whatsapp_direct_link')
    list_editable = ('status',)

    def course_display(self, obj):
        course_title = obj.course.title if obj.course else (obj.course_name_custom or "Умумий маслаҳат")
        return format_html('<b style="color:#2563eb;">{}</b>', course_title)
    course_display.short_description = "Танланган фан"

    def phone_with_whatsapp(self, obj):
        # Тоза рақам (фақат сонлар)
        clean = re.sub(r'\D', '', obj.phone)
        if clean.startswith('8'):
            clean = '7' + clean[1:]
        elif not clean.startswith('7') and len(clean) == 10:
            clean = '7' + clean

        return format_html(
            '<span style="font-weight:600; font-size:14px;">{}</span>',
            obj.phone
        )
    phone_with_whatsapp.short_description = "Телефон рақами"

    def chat_btn(self, obj):
        """Битта босганда тўғридан-тўғри мижознинг WhatsApp чатига кирадиган яшил тугма"""
        clean = re.sub(r'\D', '', obj.phone)
        if clean.startswith('8'):
            clean = '7' + clean[1:]
        elif not clean.startswith('7') and len(clean) == 10:
            clean = '7' + clean

        course_title = obj.course.title if obj.course else (obj.course_name_custom or "курс")
        
        # Тайёр саломлашиш хабари
        msg = f"Ассалому алайкум, {obj.name}! Сиз ўқув марказимиз сайтида «{course_title}» курсига ёзилиш учун заявка қолдирган эдингиз. Қачон дарсни бошлашни режалаштиряпсиз?"
        encoded_msg = urllib.parse.quote(msg)
        wa_url = f"https://wa.me/{clean}?text={encoded_msg}"

        return format_html(
            '<a href="{}" target="_blank" style="'
            'background-color:#25D366; color:#ffffff; padding:7px 14px; border-radius:6px; '
            'text-decoration:none; font-weight:700; font-size:13px; display:inline-flex; align-items:center; gap:6px;'
            'box-shadow: 0 2px 6px rgba(37,211,102,0.4);">'
            '💬 WhatsApp-да ёзиш'
            '</a>',
            wa_url
        )
    chat_btn.short_description = "WhatsApp чати"

    def whatsapp_direct_link(self, obj):
        clean = re.sub(r'\D', '', obj.phone)
        if clean.startswith('8'):
            clean = '7' + clean[1:]
        elif not clean.startswith('7') and len(clean) == 10:
            clean = '7' + clean
        wa_url = f"https://wa.me/{clean}"
        return format_html(
            '<a href="{}" target="_blank" style="font-size:16px; color:#25D366; font-weight:bold;">'
            '🔗 https://wa.me/{} (Босиб чатни очиш)'
            '</a>',
            wa_url, clean
        )
    whatsapp_direct_link.short_description = "Мижоз WhatsApp ҳаволаси"


from .models import StaffMember, RentExpense

@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'phone', 'salary_kzt_display', 'is_active', 'hired_date')
    list_filter = ('role', 'is_active')
    search_fields = ('name', 'phone', 'custom_role')
    list_editable = ('is_active',)

    def salary_kzt_display(self, obj):
        return f"{obj.salary_kzt:,} ₸"
    salary_kzt_display.short_description = "Ойлик маоши (₸)"


@admin.register(RentExpense)
class RentExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'month_year', 'amount_kzt_display', 'due_date', 'is_paid', 'paid_date')
    list_filter = ('is_paid', 'month_year')
    search_fields = ('title', 'landlord_phone', 'notes')
    list_editable = ('is_paid',)

    def amount_kzt_display(self, obj):
        return f"{obj.amount_kzt:,} ₸"
    amount_kzt_display.short_description = "Ижара нархи (₸)"


from .models import ScheduleSettings, Teacher, Group, Student, Lesson

@admin.register(ScheduleSettings)
class ScheduleSettingsAdmin(admin.ModelAdmin):
    list_display = ('day_start', 'day_end', 'lesson_duration', 'break_duration', 'updated_at')

@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'subjects', 'color', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('full_name', 'phone', 'subjects')
    list_editable = ('is_active',)

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'subject', 'teacher', 'color', 'is_active', 'created_at')
    list_filter = ('is_active', 'teacher', 'subject')
    search_fields = ('name', 'subject')
    list_editable = ('is_active',)

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'group', 'is_active', 'created_at')
    list_filter = ('is_active', 'group')
    search_fields = ('full_name', 'phone')
    list_editable = ('is_active',)

@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('day_of_week', 'start_time', 'end_time', 'group', 'teacher', 'room')
    list_filter = ('day_of_week', 'teacher', 'group')
    search_fields = ('group__name', 'teacher__full_name', 'room')


@admin.register(InstagramSettings)
class InstagramSettingsAdmin(admin.ModelAdmin):
    list_display = ('ig_username', 'is_connected', 'ig_user_id', 'expires_at', 'updated_at')
    readonly_fields = ('access_token', 'connected_at', 'updated_at')


@admin.register(InstagramMessage)
class InstagramMessageAdmin(admin.ModelAdmin):
    list_display = ('message_id', 'sender_igsid', 'direction', 'text_short', 'timestamp', 'is_read')
    list_filter = ('direction', 'is_read', 'timestamp')
    search_fields = ('message_id', 'sender_igsid', 'text')

    def text_short(self, obj):
        return (obj.text[:50] + '...') if len(obj.text) > 50 else obj.text
    text_short.short_description = "Хабар матни"


