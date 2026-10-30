import datetime
from .models import ScheduleSettings, Teacher, Group, Lesson, Student


def parse_time_str(time_val):
    """Qabul qilingan vaqtni datetime.time obyektiga o'tkazish"""
    if isinstance(time_val, datetime.time):
        return time_val
    if isinstance(time_val, datetime.datetime):
        return time_val.time()
    if isinstance(time_val, str):
        parts = time_val.strip().split(':')
        return datetime.time(int(parts[0]), int(parts[1]))
    raise ValueError(f"Noto'g'ri vaqt formati: {time_val}")


def time_to_minutes(t):
    """Time obyektini sutka boshidan minutlarga aylantirish"""
    t = parse_time_str(t)
    return t.hour * 60 + t.minute


def minutes_to_time(m):
    """Minutlarni datetime.time obyektiga aylantirish"""
    m = m % (24 * 60)
    hours = m // 60
    minutes = m % 60
    return datetime.time(hours, minutes)


def generate_daily_slots(settings=None):
    """
    Sozlamalar asosida kunlik vaqt slotlarini generatsiya qilish:
    Dars -> Tanaffus -> Dars -> Tanaffus...
    Default: 08:00 dan 20:00 gacha, dars 70 min, tanaffus 60 min.
    """
    if settings is None:
        settings = ScheduleSettings.get_settings()

    start_min = time_to_minutes(settings.day_start)
    end_min = time_to_minutes(settings.day_end)
    lesson_dur = settings.lesson_duration
    break_dur = settings.break_duration

    slots = []
    curr_min = start_min
    lesson_idx = 1

    while curr_min + lesson_dur <= end_min:
        l_start = minutes_to_time(curr_min)
        l_end = minutes_to_time(curr_min + lesson_dur)
        
        slots.append({
            'index': lesson_idx,
            'type': 'lesson',
            'start_time': l_start,
            'end_time': l_end,
            'start_str': l_start.strftime('%H:%M'),
            'end_str': l_end.strftime('%H:%M'),
            'label': f"{l_start.strftime('%H:%M')} – {l_end.strftime('%H:%M')}",
            'duration_min': lesson_dur,
        })
        lesson_idx += 1
        curr_min += lesson_dur

        # Tanaffus qo'shish (agar oxirgi darsdan keyin yana dars sig'sa yoki vaqt qolgan bo'lsa)
        if curr_min + break_dur <= end_min and (curr_min + break_dur + lesson_dur <= end_min or break_dur > 0):
            b_start = minutes_to_time(curr_min)
            b_end = minutes_to_time(curr_min + break_dur)
            slots.append({
                'index': None,
                'type': 'break',
                'start_time': b_start,
                'end_time': b_end,
                'start_str': b_start.strftime('%H:%M'),
                'end_str': b_end.strftime('%H:%M'),
                'label': f"{b_start.strftime('%H:%M')} – {b_end.strftime('%H:%M')}",
                'duration_min': break_dur,
            })
            curr_min += break_dur
        else:
            break

    return slots


def get_lesson_only_slots(settings=None):
    """Faqat dars slotlarini olish (tanaffussiz)"""
    all_slots = generate_daily_slots(settings)
    return [s for s in all_slots if s['type'] == 'lesson']


def check_lesson_conflict(teacher_id, group_id, day_of_week, start_time, end_time, exclude_lesson_id=None):
    """
    Konfliktlarni tekshirish:
    1. O'qituvchi ayni paytda boshqa guruhda darsda emasmi?
    2. Guruh ayni paytda boshqa darsda emasmi?
    Interval kesishuvi: A_start < B_end and A_end > B_start
    """
    start_t = parse_time_str(start_time)
    end_t = parse_time_str(end_time)

    # 1. O'qituvchi bandligini tekshirish
    teacher_conflicts = Lesson.objects.filter(
        teacher_id=teacher_id,
        day_of_week=day_of_week,
        start_time__lt=end_t,
        end_time__gt=start_t
    )
    if exclude_lesson_id:
        teacher_conflicts = teacher_conflicts.exclude(id=exclude_lesson_id)

    if teacher_conflicts.exists():
        conf = teacher_conflicts.select_related('teacher', 'group').first()
        return True, (
            f"Конфликт расписания! Преподаватель {conf.teacher.full_name} уже занят(а) "
            f"в это время ({conf.start_time.strftime('%H:%M')}–{conf.end_time.strftime('%H:%M')}) "
            f"с группой «{conf.group.name}»."
        )

    # 2. Guruh bandligini tekshirish
    group_conflicts = Lesson.objects.filter(
        group_id=group_id,
        day_of_week=day_of_week,
        start_time__lt=end_t,
        end_time__gt=start_t
    )
    if exclude_lesson_id:
        group_conflicts = group_conflicts.exclude(id=exclude_lesson_id)

    if group_conflicts.exists():
        conf = group_conflicts.select_related('teacher', 'group').first()
        return True, (
            f"Конфликт расписания! Группа «{conf.group.name}» уже имеет урок "
            f"в это время ({conf.start_time.strftime('%H:%M')}–{conf.end_time.strftime('%H:%M')}) "
            f"у преподавателя {conf.teacher.full_name}."
        )

    return False, None


def calculate_teacher_availability(teacher, settings=None, days_count=7):
    """
    O'qituvchi haftalik statistikasini hisoblash:
    - Jami darslar soni (lessons per week)
    - Jami bo'sh soatlar (free hours per week)
    """
    if settings is None:
        settings = ScheduleSettings.get_settings()

    lesson_slots = get_lesson_only_slots(settings)
    total_slots_per_week = len(lesson_slots) * days_count
    slot_hours = settings.lesson_duration / 60.0

    lessons_count = Lesson.objects.filter(teacher=teacher).count()
    free_slots = max(0, total_slots_per_week - lessons_count)
    free_hours = round(free_slots * slot_hours, 1)
    busy_hours = round(lessons_count * slot_hours, 1)

    return {
        'total_lessons': lessons_count,
        'busy_hours': busy_hours,
        'free_slots': free_slots,
        'free_hours': free_hours,
        'total_possible_slots': total_slots_per_week,
    }
