from django.db import models

class Course(models.Model):
    title = models.CharField("Название курса", max_length=200)
    slug = models.SlugField("URL-метка", unique=True)
    category = models.CharField("Категория", max_length=100, choices=[
        ('languages', 'Иностранные языки'),
        ('it', 'IT и Программирование'),
        ('school', 'Школьные предметы и ЕНТ'),
    ], default='languages')
    short_description = models.CharField("Краткое описание", max_length=255)
    full_description = models.TextField("Полное описание")
    duration = models.CharField("Длительность", max_length=100, default="3 месяца (8 занятий в месяц)")
    price_kzt = models.PositiveIntegerField("Стоимость в месяц (₸)", default=35000)
    badge = models.CharField("Бейдж", max_length=50, blank=True, help_text="Например: Хит, Для детей, Для взрослых")
    is_active = models.BooleanField("Активен", default=True)
    order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Курс"
        verbose_name_plural = "Курсы"
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.title} ({self.price_kzt:,} ₸/мес)"

    @property
    def name(self):
        return self.title


class SiteSettings(models.Model):
    """Сайт ва WhatsApp созламалари (Админ ўзгартириши учун)"""
    whatsapp_number = models.CharField(
        "Ишчи WhatsApp рақами", 
        max_length=30, 
        default="+7 708 116 02 65",
        help_text="Мижозларга кўринадиган ва чат очиладиган рақам"
    )
    whatsapp_clean = models.CharField(
        "WhatsApp рақами (фақат рақамлар)", 
        max_length=20, 
        default="77081160265",
        help_text="Фақат рақамлар: 77081160265"
    )
    default_message = models.TextField(
        "Мижозга юбориладиган тайёр саломлашиш матни",
        default="Ассалому алайкум! Сиз бизнинг ўқув марказимиз сайтида дарсга ёзилиш учун заявка қолдирган эдингиз. Қайси вақтда дарсни бошлашни хоҳлайсиз?",
        help_text="Админ заявкадаги WhatsApp тугмасини босганда ушбу матн автомат чатга ёзилади"
    )

    class Meta:
        verbose_name = "WhatsApp ва Сайт созламаси"
        verbose_name_plural = "WhatsApp ва Сайт созламалари"

    def __str__(self):
        return f"WhatsApp: {self.whatsapp_number}"


class LeadApplication(models.Model):
    STATUS_CHOICES = [
        ('new',         'Янги мурожаат 🆕'),
        ('contacted',   'Менеджер боғланди 💬'),
        ('agreed',      'Розилик берди ✅'),
        ('waiting',     'Ўқишни кутмоқда 📚'),
        ('paid',        'Келди / Тўлади 🎓'),
        ('cancelled',   'Келмади / Рад этди ❌'),
    ]

    SOURCE_CHOICES = [
        ('whatsapp',  'WhatsApp'),
        ('telegram',  'Telegram'),
        ('instagram', 'Instagram'),
        ('call',      'Қўнғироқ / Звонок'),
        ('web',       'Веб-сайт'),
        ('other',     'Бошқа'),
    ]

    name = models.CharField("Мижоз исми", max_length=150)
    phone = models.CharField("Телефон рақами (+7)", max_length=30)
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Танланган фан/курс")
    course_name_custom = models.CharField("Фан/Йўналиш (қўлда)", max_length=200, blank=True)
    message = models.TextField("Мижоз изоҳи / Истаклари", blank=True)
    source = models.CharField("Манбаа", max_length=20, choices=SOURCE_CHOICES, default='web', blank=True)
    manager_name = models.CharField("Менеджер исми", max_length=100, blank=True)
    # Мижоз шахсий анкетаси / Профили
    birth_date = models.CharField("Туғилган санаси (йили/ойи)", max_length=100, blank=True)
    address = models.CharField("Яшаш манзили / Қаерда туради", max_length=255, blank=True)
    interests = models.TextField("Қизиқишлари", blank=True)
    study_reason = models.TextField("Нима учун ўқимоқчи / Мақсади", blank=True)

    # Тўлов ва Курс келишуви маълумотлари (Пришел / Тўлади босқичи учун)
    paid_amount = models.PositiveIntegerField("Тўланган сумма (₸)", default=0, blank=True)
    payment_type = models.CharField(
        "Тўлов ҳолати",
        max_length=30,
        blank=True,
        default="",
        choices=[
            ('full', 'Тўлиқ тўлов (100%)'),
            ('partial', 'Қисман / Бўлиб тўлаш'),
            ('trial', 'Синов дарси / Ҳозирча тўламади'),
        ]
    )
    payment_notes = models.CharField("Тўлов изоҳи / Қолдиқ", max_length=255, blank=True)

    # Статус
    status = models.CharField("Ҳолати", max_length=30, choices=STATUS_CHOICES, default='new')
    bitrix24_lead_id = models.CharField("Битрикс24 Лид ID", max_length=50, blank=True, null=True)
    b24_error = models.TextField("Битрикс24 хатолиги", blank=True)
    telegram_chat_id = models.CharField("Telegram Chat ID", max_length=100, blank=True, null=True, db_index=True)
    instagram_igsid = models.CharField("Instagram IGSID", max_length=100, blank=True, null=True, db_index=True)

    created_at = models.DateTimeField("Заявка вақти", auto_now_add=True)

    class Meta:
        verbose_name = "Келиб тушган заявка"
        verbose_name_plural = "Келиб тушган заявкалар"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.phone}) - {self.course or self.course_name_custom}"

    @property
    def display_course(self):
        if self.course_name_custom:
            return self.course_name_custom
        if self.course:
            return self.course.name
        return "Python & AI Разработка"

    @property
    def initials(self):
        parts = self.name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        elif parts and len(parts[0]) >= 2:
            return parts[0][:2].upper()
        elif parts:
            return parts[0][:1].upper()
        return "КЛ"


class StaffMember(models.Model):
    """Ўқув маркази ходимлари ва устозлари"""
    ROLE_CHOICES = [
        ('teacher', 'Ўқитувчи / Устоз 👨‍🏫'),
        ('admin', 'Администратор / Менеджер 👩‍💼'),
        ('marketer', 'Маркетолог / Таргетолог 📈'),
        ('accountant', 'Бухгалтер 🧮'),
        ('technical', 'Техник ходим / IT 💻'),
        ('other', 'Бошқа лавозим 👥'),
    ]

    name = models.CharField("Ходим исми", max_length=150)
    role = models.CharField("Лавозими", max_length=50, choices=ROLE_CHOICES, default='teacher')
    custom_role = models.CharField("Аниқ йўналиши (масалан: IELTS устози)", max_length=100, blank=True)
    phone = models.CharField("Телефон рақами (+7)", max_length=30)
    salary_kzt = models.PositiveIntegerField("Ойлик маоши (₸)", default=180000)
    hired_date = models.DateField("Иш бошлаган санаси", auto_now_add=True)
    is_active = models.BooleanField("Ҳолати (Фаол ишламоқда)", default=True)
    notes = models.TextField("Қўшимча маълумот / Изоҳ", blank=True)

    class Meta:
        verbose_name = "Ходим / Устоз"
        verbose_name_plural = "Ходимлар ва Устозлар"
        ordering = ['-is_active', 'name']

    def __str__(self):
        return f"{self.name} - {self.get_role_display()} ({self.salary_kzt:,} ₸)"


class RentExpense(models.Model):
    """Аренда (Бино ва хоналар ижараси) харажатлари"""
    title = models.CharField("Бино / Хона номи", max_length=200, default="Асосий ўқув маркази биноси")
    month_year = models.CharField("Ой ва йил (масалан: Октябрь 2026)", max_length=100)
    amount_kzt = models.PositiveIntegerField("Ижара нархи (₸)", default=350000)
    due_date = models.DateField("Тўлов муддати")
    is_paid = models.BooleanField("Тўланганми?", default=False)
    paid_date = models.DateField("Тўланган сана", null=True, blank=True)
    landlord_phone = models.CharField("Ижара берувчи рақами (+7)", max_length=30, blank=True)
    notes = models.TextField("Изоҳ / Шартнома рақами", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Аренда харажати"
        verbose_name_plural = "Аренда харажатлари"
        ordering = ['-due_date']

    def __str__(self):
        status = "Тўланган" if self.is_paid else "Кутилмоқда"
        return f"{self.title} ({self.month_year}) - {self.amount_kzt:,} ₸ [{status}]"


class TelegramSettings(models.Model):
    """Telegram интеграцияси созламалари ва QR-код сессияси"""
    bot_token = models.CharField(
        "Telegram Bot Token", 
        max_length=200, 
        blank=True, 
        default="",
        help_text="@BotFather дан олинган токен (масалан: 123456789:ABCdef...)"
    )
    bot_username = models.CharField(
        "Бот юзернейми (username)", 
        max_length=100, 
        blank=True, 
        default="EduCenterKzBot",
        help_text="@ белгисисиз, масалан: EduCenterKzBot"
    )
    admin_chat_id = models.CharField(
        "Уланган Администратор Chat ID", 
        max_length=100, 
        blank=True, 
        default="",
        help_text="QR-кодни сканерлаб уланганда автомат ёзилади"
    )
    admin_name = models.CharField(
        "Администратор исми / юзернейми", 
        max_length=150, 
        blank=True, 
        default=""
    )
    is_connected = models.BooleanField("Уланган ҳолатдами?", default=False)
    auth_secret = models.CharField(
        "QR уланиш махфий калити", 
        max_length=64, 
        blank=True, 
        default=""
    )
    notify_on_new_lead = models.BooleanField(
        "Янги лид тушганда Telegram'га хабарнома юбориш", 
        default=True
    )
    webhook_url = models.URLField("Webhook URL", max_length=500, blank=True, null=True, help_text="Telegram серверлари хабар юборадиган HTTPS манзил")
    is_webhook_active = models.BooleanField("Webhook фаолми?", default=False)
    connected_at = models.DateTimeField("Уланган вақт", null=True, blank=True)
    last_update_id = models.BigIntegerField("Охирги Telegram Update ID", default=0)
    updated_at = models.DateTimeField("Сўнгги ўзгариш", auto_now=True)

    class Meta:
        verbose_name = "Telegram созламаси"
        verbose_name_plural = "Telegram созламалари"

    def __str__(self):
        status = "Уланган ✅" if self.is_connected else "Кутилмоқда ⏳"
        return f"Telegram: @{self.bot_username} [{status}]"


# ========================================================
# ДАРС ЖАДВАЛИ ВА ЎҚИТУВЧИЛАР БОШҚАРУВИ (SCHEDULE MANAGEMENT)
# ========================================================

class ScheduleSettings(models.Model):
    """Жадвал созламалари: Иш куни бошланиши, тугаши ва дарс/танаффус давомийлиги"""
    day_start = models.TimeField("Иш куни бошланиши", default="08:00")
    day_end = models.TimeField("Иш куни тугаши", default="20:00")
    lesson_duration = models.PositiveIntegerField("Дарс давомийлиги (дақиқа)", default=70)
    break_duration = models.PositiveIntegerField("Танаффус давомийлиги (дақиқа)", default=60)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Жадвал созламаси"
        verbose_name_plural = "Жадвал созламалари"

    def __str__(self):
        return f"Жадвал: {self.day_start.strftime('%H:%M')}-{self.day_end.strftime('%H:%M')} (Дарс: {self.lesson_duration}м, Танаффус: {self.break_duration}м)"

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(id=1, defaults={
            'day_start': '08:00',
            'day_end': '20:00',
            'lesson_duration': 70,
            'break_duration': 60,
        })
        return obj


class Teacher(models.Model):
    """Ўқитувчи (Преподаватель)"""
    full_name = models.CharField("Ф.И.Ш / Тўлиқ исми", max_length=150)
    phone = models.CharField("Телефон рақами", max_length=30)
    subjects = models.CharField("Ўтадиган фан(лар)и", max_length=255, help_text="Масалан: Инглиз тили, IELTS, Математика")
    color = models.CharField("Ранг коди", max_length=20, default="#2563eb", help_text="Жадвалда ажралиб туриши учун HEX ранг")
    is_active = models.BooleanField("Ҳолати (Фаол)", default=True)
    telegram_chat_id = models.CharField("Telegram Chat ID", max_length=50, blank=True, null=True)
    telegram_username = models.CharField("Telegram Username", max_length=100, blank=True, null=True)
    notes = models.TextField("Қўшимча маълумот / Изоҳ", blank=True)
    created_at = models.DateTimeField("Қўшилган сана", auto_now_add=True)

    class Meta:
        verbose_name = "Ўқитувчи"
        verbose_name_plural = "Ўқитувчилар"
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.subjects})"


class Group(models.Model):
    """Ўқувчилар гуруҳи"""
    name = models.CharField("Гуруҳ номи", max_length=100)
    subject = models.CharField("Фан", max_length=150)
    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name='groups', verbose_name="Бириктирилган ўқитувчи")
    color = models.CharField("Гуруҳ ранги", max_length=20, default="#3b82f6")
    is_active = models.BooleanField("Фаол гуруҳ", default=True)
    created_at = models.DateTimeField("Очилган вақти", auto_now_add=True)

    class Meta:
        verbose_name = "Гуруҳ"
        verbose_name_plural = "Гуруҳлар"
        ordering = ['name']

    def __str__(self):
        teacher_name = self.teacher.full_name if self.teacher else "Тайинланмаган"
        return f"{self.name} - {self.subject} ({teacher_name})"

    @property
    def student_count(self):
        return self.students.filter(is_active=True).count()


class Student(models.Model):
    """Ўқувчи"""
    full_name = models.CharField("Ўқувчи Ф.И.Ш", max_length=150)
    phone = models.CharField("Телефон рақами", max_length=30, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='students', verbose_name="Гуруҳи")
    is_active = models.BooleanField("Ўқимоқдами?", default=True)
    telegram_chat_id = models.CharField("Telegram Chat ID", max_length=50, blank=True, null=True)
    telegram_username = models.CharField("Telegram Username", max_length=100, blank=True, null=True)
    created_at = models.DateTimeField("Рўйхатдан ўтган вақти", auto_now_add=True)

    class Meta:
        verbose_name = "Ўқувчи"
        verbose_name_plural = "Ўқувчилар"
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.group.name})"


class Lesson(models.Model):
    """Жадвалдаги дарс"""
    DAY_CHOICES = [
        (0, 'Душанба (Понедельник)'),
        (1, 'Сешанба (Вторник)'),
        (2, 'Чоршанба (Среда)'),
        (3, 'Пайшанба (Четверг)'),
        (4, 'Жума (Пятница)'),
        (5, 'Шанба (Суббота)'),
        (6, 'Якшанба (Воскресенье)'),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='lessons', verbose_name="Гуруҳ")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name='lessons', verbose_name="Ўқитувчи")
    day_of_week = models.IntegerField("Ҳафта куни", choices=DAY_CHOICES)
    start_time = models.TimeField("Бошланиш вақти")
    end_time = models.TimeField("Тугаш вақти")
    room = models.CharField("Хона / Аудитория", max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Дарс"
        verbose_name_plural = "Дарслар"
        ordering = ['day_of_week', 'start_time']

    def __str__(self):
        return f"{self.get_day_of_week_display()}: {self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} | {self.group.name} ({self.teacher.full_name})"


class TelegramMessage(models.Model):
    """Telegram орқали юборилган ва қабул қилинган хабарлар тарихи"""
    DIRECTION_CHOICES = [
        ('in', 'Кирувчи (Incoming)'),
        ('out', 'Чиқувчи (Outgoing)'),
    ]

    chat_id = models.CharField("Telegram Chat ID", max_length=50, db_index=True)
    message_id = models.BigIntegerField("Message ID", null=True, blank=True)
    sender_name = models.CharField("Юборувчи исми", max_length=150, blank=True, default="")
    sender_username = models.CharField("Юборувчи @username", max_length=100, blank=True, default="")
    direction = models.CharField("Йўналиш", max_length=5, choices=DIRECTION_CHOICES, default='in')
    text = models.TextField("Хабар матни", blank=True, default="")
    timestamp = models.DateTimeField("Юборилган вақти", auto_now_add=True, db_index=True)
    is_read = models.BooleanField("Ўқилдими?", default=False)
    raw_payload = models.JSONField("Хом маълумот (JSON)", default=dict, blank=True)

    teacher = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name='telegram_messages', verbose_name="Бириктирилган ўқитувчи")
    student = models.ForeignKey(Student, on_delete=models.SET_NULL, null=True, blank=True, related_name='telegram_messages', verbose_name="Бириктирилган ўқувчи")

    class Meta:
        db_table = 'telegram_messages'
        verbose_name = "Telegram хабари"
        verbose_name_plural = "Telegram хабарлари"
        ordering = ['timestamp']

    def __str__(self):
        return f"[{self.direction.upper()}] {self.sender_name or self.chat_id}: {self.text[:30]}"


# ========================================================
# INSTAGRAM DM ИНТЕГРАЦИЯСИ (META API)
# ========================================================

class InstagramSettings(models.Model):
    """Instagram Graph API интеграцияси созламалари ва уланган аккаунт"""
    app_id = models.CharField("Meta App ID", max_length=100, blank=True, default="")
    app_secret = models.CharField("Meta App Secret", max_length=200, blank=True, default="")
    verify_token = models.CharField("Webhook Verify Token", max_length=100, blank=True, default="edu_center_ig_verify_2026")
    redirect_uri = models.URLField("OAuth Redirect URI", max_length=500, blank=True, default="")

    access_token = models.TextField("Long-lived Access Token", blank=True, default="")
    token_type = models.CharField("Token Type", max_length=50, blank=True, default="bearer")
    ig_user_id = models.CharField("Instagram Business Account ID", max_length=100, blank=True, default="", db_index=True)
    ig_username = models.CharField("Instagram @username", max_length=100, blank=True, default="")

    is_connected = models.BooleanField("Уланган ҳолатдами?", default=False)
    connected_at = models.DateTimeField("Уланган сана", null=True, blank=True)
    expires_at = models.DateTimeField("Токен муддати тугаши", null=True, blank=True)
    updated_at = models.DateTimeField("Сўнгги янгиланиш", auto_now=True)

    # Профиль маълумотлари (статистика)
    full_name = models.CharField("Исм / Тўлиқ ном", max_length=150, blank=True, default="")
    profile_pic_url = models.TextField("Аватар расми URL", blank=True, default="")
    followers_count = models.IntegerField("Подписчики", default=0)
    following_count = models.IntegerField("Подписки", default=0)
    media_count = models.IntegerField("Публикации", default=0)
    bio = models.TextField("Bio / Тавсиф", blank=True, default="")

    class Meta:
        verbose_name = "Instagram созламаси"
        verbose_name_plural = "Instagram созламалари"

    def __str__(self):
        status = f"@{self.ig_username} (Уланган ✅)" if self.is_connected else "Уланмаган ❌"
        return f"Instagram: {status}"


class InstagramMessage(models.Model):
    """Instagram Direct орқали келган ва юборилган хабарлар тарихи"""
    DIRECTION_CHOICES = [
        ('in', 'Кирувчи (Incoming)'),
        ('out', 'Чиқувчи (Outgoing)'),
    ]

    message_id = models.CharField("Message ID (mid)", max_length=255, unique=True, null=True, blank=True, db_index=True)
    sender_igsid = models.CharField("Юборувчи IGSID", max_length=100, db_index=True)
    recipient_igsid = models.CharField("Қабул қилувчи IGSID", max_length=100, db_index=True)
    direction = models.CharField("Йўналиш", max_length=5, choices=DIRECTION_CHOICES, default='in')
    text = models.TextField("Хабар матни", blank=True, default="")
    timestamp_ms = models.BigIntegerField("Timestamp (ms)", default=0, db_index=True)
    timestamp = models.DateTimeField("Юборилган вақти", auto_now_add=True, db_index=True)
    is_read = models.BooleanField("Ўқилдими?", default=False)
    raw_payload = models.JSONField("Хом маълумот (JSON)", default=dict, blank=True)

    lead = models.ForeignKey(LeadApplication, on_delete=models.SET_NULL, null=True, blank=True, related_name='instagram_messages', verbose_name="Бириктирилган Лид")

    class Meta:
        db_table = 'instagram_messages'
        verbose_name = "Instagram хабари"
        verbose_name_plural = "Instagram хабарлари"
        ordering = ['timestamp']

    def __str__(self):
        return f"[{self.direction.upper()}] {self.sender_igsid}: {self.text[:30]}"


class InstagramComment(models.Model):
    """Instagram post/reels комментариялари ва саволлари"""
    comment_id = models.CharField("Comment ID", max_length=255, unique=True, db_index=True)
    post_id = models.CharField("Post/Media ID", max_length=255, db_index=True)
    post_url = models.URLField("Post/Reels URL", max_length=500, blank=True)
    commenter_username = models.CharField("Коментария ёзган", max_length=150, db_index=True)
    commenter_igsid = models.CharField("Коментатор IGSID", max_length=100, blank=True, db_index=True)
    text = models.TextField("Коментария матни")
    timestamp = models.DateTimeField("Ёзилган вақти", auto_now_add=True, db_index=True)
    is_read = models.BooleanField("Ўқилдими?", default=False)
    lead = models.ForeignKey(
        LeadApplication, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='instagram_comments',
        verbose_name="Бириктирилган Лид"
    )
    raw_payload = models.JSONField("Хом JSON маълумот", default=dict, blank=True)

    class Meta:
        db_table = 'instagram_comments'
        verbose_name = "Instagram комментарияси"
        verbose_name_plural = "Instagram комментариялари"
        ordering = ['-timestamp']

    def __str__(self):
        return f"@{self.commenter_username}: {self.text[:40]}"


