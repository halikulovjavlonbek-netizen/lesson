import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from courses.models import Course

courses_data = [
    {
        'title': 'General English (Английский язык)',
        'slug': 'general-english',
        'category': 'languages',
        'short_description': 'Разговорный английский для детей и взрослых от уровня Beginner до Advanced.',
        'full_description': 'Интенсивный курс с носителем и квалифицированными преподавателями (IELTS 8.0+). Акцент на разговорную речь, снятие языкового барьера, грамматику и словарный запас.',
        'duration': '3 месяца (12 уроков в месяц)',
        'price_kzt': 35000,
        'badge': 'ХИТ ПРОДАЖ',
        'order': 1,
    },
    {
        'title': 'Python & IT-разработка для школьников и студентов',
        'slug': 'python-programming',
        'category': 'it',
        'short_description': 'С нуля до создания реальных ботов, сайтов и игр на Python.',
        'full_description': 'Курс знакомит с основами программирования, алгоритмами, ООП, разработкой Telegram-ботов и web-приложений. Подходит как для новичков, так и для продвинутых.',
        'duration': '4 месяца (8 уроков в месяц)',
        'price_kzt': 45000,
        'badge': 'ТОП ВЫБОР',
        'order': 2,
    },
    {
        'title': 'Подготовка к ЕНТ и НИШ (Математика + Грамотность)',
        'slug': 'ent-math-prep',
        'category': 'school',
        'short_description': 'Подготовка к поступлению в топовые школы и университеты Казахстана.',
        'full_description': 'Разбор сложных тестовых задач, формул, лайфхаков быстрого счета и логики. Авторская методика от преподавателей-призеров олимпиад.',
        'duration': '6 месяцев (12 уроков в месяц)',
        'price_kzt': 30000,
        'badge': 'РЕЗУЛЬТАТ 120+',
        'order': 3,
    },
    {
        'title': 'IELTS Intensive 7.5+',
        'slug': 'ielts-intensive',
        'category': 'languages',
        'short_description': 'Быстрая подготовка к сдаче экзамена IELTS (Speaking, Writing, Reading, Listening).',
        'full_description': 'Курс нацелен на сдачу экзамена на высокий балл для поступления в зарубежные вузы или Nazarbayev University. Мок-тесты каждую субботу.',
        'duration': '2 месяца (интенсив)',
        'price_kzt': 48000,
        'badge': 'ПРЕМИУМ',
        'order': 4,
    },
    {
        'title': 'Web-разработка: Frontend (HTML, CSS, JavaScript)',
        'slug': 'frontend-web',
        'category': 'it',
        'short_description': 'Создание красивых современных адаптивных сайтов и интерфейсов с нуля.',
        'full_description': 'Полный цикл создания сайтов: верстка, интерактивность, адаптация под смартфоны, публикация в интернет.',
        'duration': '3 месяца (8 занятий в месяц)',
        'price_kzt': 40000,
        'badge': 'ПРАКТИКА',
        'order': 5,
    },
    {
        'title': 'Ментальная арифметика и скорочтение',
        'slug': 'mental-math',
        'category': 'school',
        'short_description': 'Развитие памяти, концентрации и скорости мышления для детей 6–12 лет.',
        'full_description': 'Игровые методики счета на абакусе, развитие обоих полушарий мозга, улучшение успеваемости в школе.',
        'duration': '3 месяца (8 занятий в месяц)',
        'price_kzt': 28000,
        'badge': 'ДЛЯ ДЕТЕЙ',
        'order': 6,
    }
]

for item in courses_data:
    course, created = Course.objects.update_or_create(
        slug=item['slug'],
        defaults=item
    )
    print(f"Курс: {course.title} - {course.price_kzt} KZT ({'создан' if created else 'обновлен'})")

print("Все курсы успешно загружены!")
