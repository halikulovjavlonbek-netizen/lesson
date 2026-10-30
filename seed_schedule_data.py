import os
import django
import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from courses.models import ScheduleSettings, Teacher, Group, Student, Lesson
from courses.schedule_utils import generate_daily_slots

def run():
    print("--- Seeding Schedule & Teachers Data ---")
    settings = ScheduleSettings.get_settings()
    settings.day_start = datetime.time(8, 0)
    settings.day_end = datetime.time(20, 0)
    settings.lesson_duration = 70
    settings.break_duration = 60
    settings.save()
    print("[OK] ScheduleSettings saved (08:00 - 20:00, 70m lesson, 60m break)")

    # Teachers
    teachers_data = [
        {
            'full_name': 'Алиев Сардор Бахтиярович',
            'phone': '+7 708 123 45 67',
            'subjects': 'Python, Django, Web-разработка',
            'color': '#3b82f6', # Blue
            'notes': 'Senior Python developer, 5 лет преподавательского стажа'
        },
        {
            'full_name': 'Ким Елена Владимировна',
            'phone': '+7 777 987 65 43',
            'subjects': 'IELTS, General English, Speaking',
            'color': '#8b5cf6', # Purple
            'notes': 'IELTS 8.5, сертифицированный тренер CELTA'
        },
        {
            'full_name': 'Маратов Нурсултан Кайратович',
            'phone': '+7 701 555 44 33',
            'subjects': 'Математика, Подготовка к ЕНТ',
            'color': '#10b981', # Emerald green
            'notes': 'Победитель республиканских олимпиад, стаж 7 лет'
        },
        {
            'full_name': 'Ахмедова Зарина Руслановна',
            'phone': '+7 705 444 22 11',
            'subjects': 'Frontend, UI/UX, JavaScript',
            'color': '#f59e0b', # Amber
            'notes': 'Практикующий фронтенд разработчик'
        }
    ]

    teacher_objs = {}
    for t_data in teachers_data:
        t, created = Teacher.objects.update_or_create(
            full_name=t_data['full_name'],
            defaults=t_data
        )
        teacher_objs[t.full_name] = t
        print(f"  - Teacher: {t.full_name} ({'Created' if created else 'Updated'})")

    # Groups
    groups_data = [
        {
            'name': 'PY-101 (Начинающие)',
            'subject': 'Python & Алгоритмы',
            'teacher': teacher_objs['Алиев Сардор Бахтиярович'],
            'color': '#3b82f6',
            'students': [
                ('Арман Серікұлы', '+7 707 111 22 33'),
                ('Данияр Мусаев', '+7 708 222 33 44'),
                ('Айгерим Касымова', '+7 775 333 44 55'),
                ('Батырхан Жумабек', '+7 701 444 55 66')
            ]
        },
        {
            'name': 'IELTS-7.0 (Интенсив)',
            'subject': 'IELTS Academic',
            'teacher': teacher_objs['Ким Елена Владимировна'],
            'color': '#8b5cf6',
            'students': [
                ('Мадина Исмаилова', '+7 777 555 66 77'),
                ('Темирлан Асетов', '+7 702 666 77 88'),
                ('Жанель Нурланова', '+7 705 777 88 99')
            ]
        },
        {
            'name': 'МАТ-ЕНТ (11 класс)',
            'subject': 'ЕНТ Математика',
            'teacher': teacher_objs['Маратов Нурсултан Кайратович'],
            'color': '#10b981',
            'students': [
                ('Азамат Болатов', '+7 701 888 99 00'),
                ('Динара Сапарова', '+7 708 999 00 11'),
                ('Санжар Куаныш', '+7 775 000 11 22'),
                ('Камила Ержанова', '+7 707 123 78 90'),
                ('Алишер Умаров', '+7 705 234 89 01')
            ]
        },
        {
            'name': 'JS-WEB (Веб-разработка)',
            'subject': 'Frontend HTML/CSS/JS',
            'teacher': teacher_objs['Ахмедова Зарина Руслановна'],
            'color': '#f59e0b',
            'students': [
                ('Нурлан Бауржанулы', '+7 702 345 67 89'),
                ('Асель Токтарова', '+7 708 456 78 90')
            ]
        }
    ]

    group_objs = {}
    for g_info in groups_data:
        students_list = g_info.pop('students')
        g, created = Group.objects.update_or_create(
            name=g_info['name'],
            defaults=g_info
        )
        group_objs[g.name] = g
        print(f"  - Group: {g.name} ({'Created' if created else 'Updated'})")

        for s_name, s_phone in students_list:
            Student.objects.update_or_create(
                full_name=s_name,
                group=g,
                defaults={'phone': s_phone, 'is_active': True}
            )

    # Lessons
    slots = generate_daily_slots(settings)
    lesson_slots = [s for s in slots if s['type'] == 'lesson']
    # slot 0: 08:00 - 09:10
    # slot 1: 10:10 - 11:20
    # slot 2: 12:20 - 13:30
    # slot 3: 14:30 - 15:40
    # slot 4: 16:40 - 17:50
    # slot 5: 18:50 - 20:00

    Lesson.objects.all().delete()
    print("[OK] Cleared old test lessons")

    sample_schedule = [
        # Mon, Wed, Fri for PY-101 (Teacher: Aliev Sardor)
        (group_objs['PY-101 (Начинающие)'], 0, lesson_slots[0]['start_time'], lesson_slots[0]['end_time'], 'Кабинет 204'),
        (group_objs['PY-101 (Начинающие)'], 2, lesson_slots[0]['start_time'], lesson_slots[0]['end_time'], 'Кабинет 204'),
        (group_objs['PY-101 (Начинающие)'], 4, lesson_slots[0]['start_time'], lesson_slots[0]['end_time'], 'Кабинет 204'),

        # Mon, Wed, Fri for MAT-ENT (Teacher: Maratov Nursultan) - Slot 1 (10:10 - 11:20)
        (group_objs['МАТ-ЕНТ (11 класс)'], 0, lesson_slots[1]['start_time'], lesson_slots[1]['end_time'], 'Аудитория 101'),
        (group_objs['МАТ-ЕНТ (11 класс)'], 2, lesson_slots[1]['start_time'], lesson_slots[1]['end_time'], 'Аудитория 101'),
        (group_objs['МАТ-ЕНТ (11 класс)'], 4, lesson_slots[1]['start_time'], lesson_slots[1]['end_time'], 'Аудитория 101'),

        # Tue, Thu, Sat for IELTS-7.0 (Teacher: Kim Elena) - Slot 2 (12:20 - 13:30)
        (group_objs['IELTS-7.0 (Интенсив)'], 1, lesson_slots[2]['start_time'], lesson_slots[2]['end_time'], 'Кабинет IELTS'),
        (group_objs['IELTS-7.0 (Интенсив)'], 3, lesson_slots[2]['start_time'], lesson_slots[2]['end_time'], 'Кабинет IELTS'),
        (group_objs['IELTS-7.0 (Интенсив)'], 5, lesson_slots[2]['start_time'], lesson_slots[2]['end_time'], 'Кабинет IELTS'),

        # Tue, Thu for JS-WEB (Teacher: Akhmedova Zarina) - Slot 4 (16:40 - 17:50)
        (group_objs['JS-WEB (Веб-разработка)'], 1, lesson_slots[4]['start_time'], lesson_slots[4]['end_time'], 'Лаборатория IT'),
        (group_objs['JS-WEB (Веб-разработка)'], 3, lesson_slots[4]['start_time'], lesson_slots[4]['end_time'], 'Лаборатория IT'),
    ]

    for grp, day_idx, s_time, e_time, room in sample_schedule:
        Lesson.objects.create(
            group=grp,
            teacher=grp.teacher,
            day_of_week=day_idx,
            start_time=s_time,
            end_time=e_time,
            room=room
        )
    print(f"[OK] Created {len(sample_schedule)} sample lessons across the week!")
    print("--- Done seeding schedule data ---")

if __name__ == '__main__':
    run()
