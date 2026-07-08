"""Product Need / Problem-Solution Intelligence Engine -- B2B seller traffic
factory. Fail-closed, rule-based, ZERO external API calls (no OpenAI /
Higgsfield / network of any kind).

Given seller-supplied product data (name, category, description, optional
manual positioning fields), produces a structured HYPOTHESIS report: core
problem solved, target segments, jobs-to-be-done, pains, desired outcomes,
benefits, objections, use cases, hook angles, video angles, recommended
content mix.

This is intentionally NOT "magic": matching is plain keyword-overlap against
a small library of category heuristics. When no category matches well, the
engine returns an honest low-confidence generic hypothesis instead of
inventing specifics -- confidence_notes always says how the guess was made,
and needs_owner_review is always True. Manual seller-supplied positioning
fields (who_is_this_for, what_problem_does_it_usually_solve, ...) always
take priority over the keyword heuristic when present.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import b2b_storage as st

POSITIONING_MODES = ("pain", "desire", "comfort", "status", "emotion")

# selected_ad_strategy values -- the first 3 correspond to ad_strategy_options[*]
# .strategy_id in every category template; multi_angle_test is the MVP default
# recommendation (test all three angles instead of committing to one).
AD_STRATEGY_IDS = ("pain_problem", "demo_use_case", "benefit_convenience", "multi_angle_test")

# Human-readable labels for seller-facing UI -- backend values unchanged.
POSITIONING_MODE_LABELS = {
    "pain": "Решение боли",
    "desire": "Желание",
    "comfort": "Удобство",
    "status": "Статус",
    "emotion": "Эмоция",
}

MANUAL_POSITIONING_FIELDS = (
    "who_is_this_for", "what_problem_does_it_usually_solve", "why_people_buy_it",
    "top_3_benefits", "use_cases", "common_questions", "objections",
    "what_should_not_be_claimed", "tone_preference",
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ProductIntelligenceError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"[\n;,]+", text)
    return [p.strip() for p in parts if p.strip()]


# -- category heuristics library ---------------------------------------------
# Each entry: keywords (RU/EN substrings, lowercase) used for matching, a
# human label, and a full report template following the shape described in
# the module docstring. Templates are deep-copied per call, never mutated
# in place here.

CATEGORY_TEMPLATES = {
    "airfryer_silicone_form": {
        "label": "силиконовая форма/вкладыш для аэрогриля",
        "keywords": ("аэрогриль", "аэрогриля", "аэрогрилю", "силиконовая форма",
                    "airfryer", "air fryer", "форма для аэрогриля", "антипригарн",
                    "вкладыш для аэрогриля"),
        "report": {
            "core_problem_solved": (
                "После готовки в аэрогриле чаша/корзина сильно пачкается жиром и "
                "соусом, и её сложно и долго отмывать."
            ),
            "secondary_problems_solved": [
                "Еда и брызги жира разлетаются по решётке корзины во время готовки",
                "Антипригарное покрытие корзины со временем царапается и стирается "
                "от металлических приборов и жёсткой мочалки",
                "Неудобно доставать готовую еду из глубокой решётчатой корзины",
            ],
            "ideal_customer_segments": [
                {"segment": "Владельцы аэрогриля, готовящие часто (3+ раз в неделю)",
                 "why_this_segment_cares": "Каждая готовка = новая долгая мойка корзины",
                 "pain_level": 5},
                {"segment": "Родители, готовящие детям курицу/картошку/наггетсы",
                 "why_this_segment_cares": "Хотят готовить быстро и не тратить вечер на мытьё посуды",
                 "pain_level": 4},
                {"segment": "Те, кто бережёт антипригарное покрытие корзины",
                 "why_this_segment_cares": "Понимают, что новая корзина для аэрогриля стоит дорого",
                 "pain_level": 4},
            ],
            "jobs_to_be_done": [
                {"job": "Приготовить еду в аэрогриле без последующей долгой мойки",
                 "context": "будний вечер после работы", "priority": 5},
                {"job": "Защитить дорогое антипригарное покрытие корзины",
                 "context": "регулярное использование аэрогриля", "priority": 4},
                {"job": "Быстро и аккуратно достать готовую еду",
                 "context": "готовка для всей семьи", "priority": 3},
            ],
            "pain_points": [
                {"pain": "Жир и соус пригорают к решётке корзины",
                 "why_it_happens": "Корзина аэрогриля решётчатая, ничего не собирает под продуктом",
                 "severity": 5},
                {"pain": "Долгая мойка корзины после каждой готовки",
                 "why_it_happens": "Нужно отмывать пригоревший жир вручную или замачивать",
                 "severity": 5},
                {"pain": "Царапины на антипригарном покрытии",
                 "why_it_happens": "Металлические приборы/жёсткие губки при чистке",
                 "severity": 3},
            ],
            "desired_outcomes": [
                {"outcome": "Мыть только форму, а не всю корзину", "type": "practical"},
                {"outcome": "Готовить без страха испортить корзину", "type": "functional"},
                {"outcome": "Меньше времени на уборку кухни после готовки", "type": "emotional"},
            ],
            "product_benefits": [
                {"benefit": "Жир и соус остаются в форме, а не на решётке корзины",
                 "mapped_to_pain": "Жир и соус пригорают к решётке корзины"},
                {"benefit": "Мыть нужно только силиконовую форму, а не всю корзину",
                 "mapped_to_pain": "Долгая мойка корзины после каждой готовки"},
                {"benefit": "Корзина аэрогриля больше не контактирует с едой напрямую",
                 "mapped_to_pain": "Царапины на антипригарном покрытии"},
            ],
            "likely_objections": [
                {"objection": "Форма помешает нормальной циркуляции горячего воздуха",
                 "response_angle": "Перфорированная/рифлёная форма пропускает воздух, продукт "
                                   "всё равно обжаривается, а не готовится на пару"},
                {"objection": "Силикон может быть небезопасен при высокой температуре",
                 "response_angle": "Указать температурный диапазон термостойкого пищевого "
                                   "силикона и сертификаты, если есть"},
                {"objection": "Не факт что подойдёт под мой размер корзины",
                 "response_angle": "Показать таблицу размеров корзин / универсальность формы"},
            ],
            "use_cases": [
                {"scenario": "Жарка курицы/крылышек",
                 "why_product_fits": "Жир с курицы стекает и остаётся в форме, а не на решётке"},
                {"scenario": "Картофель фри / дольки картофеля",
                 "why_product_fits": "Масло и крахмал не пачкают корзину, форма легко отмывается"},
                {"scenario": "Выпечка (кекс, запеканка)",
                 "why_product_fits": "Форма держит жидкое тесто, которое иначе вытекло бы через решётку"},
                {"scenario": "Разогрев/приготовление рыбы",
                 "why_product_fits": "Рыба не прилипает и не разваливается на решётке, легче переворачивать"},
            ],
            "hook_angles": [
                {"angle_type": "pain",
                 "hook": "Вот почему после каждого аэрогриля ты полчаса отмываешь корзину",
                 "why_it_should_work": "Узнаваемая ежедневная боль, вызывает мгновенный отклик"},
                {"angle_type": "problem_solution",
                 "hook": "Кладёшь ЭТО в корзину аэрогриля -- и больше не трёшь решётку",
                 "why_it_should_work": "Явный до/после эффект, понятная выгода за 3 секунды"},
                {"angle_type": "demo",
                 "hook": "Готовим курицу в аэрогриле с силиконовой формой -- смотри, что с корзиной",
                 "why_it_should_work": "Визуальное доказательство без слов убеждает лучше текста"},
                {"angle_type": "comparison",
                 "hook": "Корзина аэрогриля без формы vs с формой после одной готовки",
                 "why_it_should_work": "Прямое сравнение до/после -- сильный визуальный аргумент"},
                {"angle_type": "curiosity",
                 "hook": "Секрет, почему у некоторых аэрогриль всегда выглядит как новый",
                 "why_it_should_work": "Интрига + обещание простого решения"},
            ],
            "video_message_angles": [
                {"angle": "Грязная корзина после готовки -> чистая корзина с формой",
                 "viewer_thought_to_trigger": "О, у меня аэрогриль тоже весь грязный после готовки. "
                                              "Мне это нужно.",
                 "recommended_scene_direction": "Крупный план грязной решётки корзины, затем форма "
                                                "достаётся чистой, форма моется за 10 секунд"},
                {"angle": "Процесс готовки курицы с формой внутри корзины",
                 "viewer_thought_to_trigger": "Так вот как это работает, воздух всё равно проходит",
                 "recommended_scene_direction": "Показать форму в корзине, закрытие крышки, готовую курицу"},
                {"angle": "Сравнение времени мойки: с формой и без",
                 "viewer_thought_to_trigger": "Это реально экономит мне время каждый день",
                 "recommended_scene_direction": "Таймер на экране: мойка корзины без формы vs мойка формы"},
            ],
            "recommended_content_mix": {"pain_problem": 30, "problem_solution": 25, "demo": 20,
                                        "recipe_or_use_case": 15, "ugc_style": 5, "meme_style": 5},
            "positioning_mode": "pain",
            "ad_strategy_options": [
                {"strategy_id": "pain_problem", "title": "Через боль",
                 "main_message": "Показываем проблему покупателя и сразу даём решение.",
                 "viewer_thought": "Да, у меня тоже после готовки грязная чаша.",
                 "example_hook": "Опять мыть аэрогриль после курицы?",
                 "recommended_for": "Тем, кто уже сталкивался с этой проблемой и ищет решение"},
                {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
                 "main_message": "Показываем товар в действии: как он используется и чем помогает.",
                 "viewer_thought": "Понятно, как это работает.",
                 "example_hook": "Вот как я готовлю курицу, чтобы потом меньше отмывать чашу.",
                 "recommended_for": "Тем, кто хочет сначала увидеть, как это работает"},
                {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
                 "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                                 "делает процесс приятнее.",
                 "viewer_thought": "Это удобно, надо попробовать.",
                 "example_hook": "Маленькая форма, которая делает готовку в аэрогриле аккуратнее.",
                 "recommended_for": "Тем, кто ценит удобство и аккуратность"},
            ],
        },
    },
    "flashlight": {
        "label": "фонарик / портативный источник света",
        "keywords": ("фонарик", "фонарь", "flashlight", "torch", "led фонарь",
                    "аккумуляторный фонарь", "ручной фонарь"),
        "report": {
            "core_problem_solved": (
                "Обычный фонарик слабо светит, быстро садится и не подходит для "
                "длительных поездок/отключений света."
            ),
            "secondary_problems_solved": [
                "Неудобно брать с собой в поездку/машину",
                "Разряжается в самый неподходящий момент",
                "Тяжело найти в темноте нужный уровень яркости",
            ],
            "ideal_customer_segments": [
                {"segment": "Автомобилисты, держащие фонарь в багажнике",
                 "why_this_segment_cares": "Нужен при поломке/ремонте ночью на трассе", "pain_level": 4},
                {"segment": "Дачники и рыбаки",
                 "why_this_segment_cares": "Частые отключения света / ночная активность вне дома",
                 "pain_level": 5},
                {"segment": "Семьи, готовящиеся к отключениям электричества",
                 "why_this_segment_cares": "Хотят надёжный источник света дома", "pain_level": 4},
            ],
            "jobs_to_be_done": [
                {"job": "Осветить тёмный участок на большое расстояние",
                 "context": "ночная дорога/двор/дача", "priority": 5},
                {"job": "Иметь при себе надёжный источник света долго без подзарядки",
                 "context": "поездка, поход, отключение света", "priority": 5},
                {"job": "Быстро найти нужную вещь в темноте (гараж, кладовка, машина)",
                 "context": "бытовая ситуация", "priority": 3},
            ],
            "pain_points": [
                {"pain": "Слабый луч света, не видно на расстоянии",
                 "why_it_happens": "дешёвые светодиоды/маленькая батарея", "severity": 4},
                {"pain": "Быстро садится батарея", "why_it_happens": "малая ёмкость аккумулятора",
                 "severity": 5},
                {"pain": "Неудобно брать с собой / громоздкий",
                 "why_it_happens": "не рассчитан на компактное ношение", "severity": 2},
            ],
            "desired_outcomes": [
                {"outcome": "Яркий дальний свет в нужный момент", "type": "functional"},
                {"outcome": "Уверенность, что фонарь не подведёт в дороге", "type": "emotional"},
                {"outcome": "Долго работает без подзарядки", "type": "practical"},
            ],
            "product_benefits": [
                {"benefit": "Мощный дальний луч света",
                 "mapped_to_pain": "Слабый луч света, не видно на расстоянии"},
                {"benefit": "Долгий заряд батареи / автономная работа",
                 "mapped_to_pain": "Быстро садится батарея"},
                {"benefit": "Компактный и удобный корпус",
                 "mapped_to_pain": "Неудобно брать с собой / громоздкий"},
            ],
            "likely_objections": [
                {"objection": "Наверное, слабее, чем кажется на видео",
                 "response_angle": "Показать реальное расстояние луча в темноте, сравнение с "
                                   "обычным фонариком"},
                {"objection": "Быстро разрядится, как и другие",
                 "response_angle": "Показать время работы от одного заряда на таймере"},
                {"objection": "Хрупкий, не переживёт падение/дождь",
                 "response_angle": "Продемонстрировать влагозащиту и ударопрочность если заявлены"},
            ],
            "use_cases": [
                {"scenario": "Ночная поломка машины на трассе",
                 "why_product_fits": "Яркий дальний свет помогает осмотреть двигатель/дорогу"},
                {"scenario": "Отключение света дома",
                 "why_product_fits": "Долгий заряд обеспечивает свет на весь вечер"},
                {"scenario": "Дача/рыбалка ночью", "why_product_fits": "Автономность без розетки рядом"},
                {"scenario": "Поиск вещей в гараже/кладовке", "why_product_fits": "Компактный, всегда под рукой"},
            ],
            "hook_angles": [
                {"angle_type": "pain",
                 "hook": "Знакомая ситуация: фонарик сел именно тогда, когда он нужнее всего",
                 "why_it_should_work": "Узнаваемая раздражающая ситуация"},
                {"angle_type": "demo", "hook": "Тест дальности света в полной темноте",
                 "why_it_should_work": "Наглядное доказательство характеристик"},
                {"angle_type": "comparison", "hook": "Обычный фонарик из магазина у дома vs этот",
                 "why_it_should_work": "Прямое визуальное сравнение убеждает быстрее слов"},
                {"angle_type": "problem_solution", "hook": "Больше никогда не остаться в темноте на трассе",
                 "why_it_should_work": "Обещание решения конкретного страха"},
                {"angle_type": "curiosity",
                 "hook": "Почему этот фонарик держат в бардачке даже дальнобойщики",
                 "why_it_should_work": "Социальное доказательство + любопытство"},
            ],
            "video_message_angles": [
                {"angle": "Ночная поломка на трассе, фонарик спасает ситуацию",
                 "viewer_thought_to_trigger": "О, у меня тоже был случай, когда фонарик подвёл. Надо такой.",
                 "recommended_scene_direction": "Тёмная дорога, открытый капот, яркий луч освещает двигатель"},
                {"angle": "Сравнение времени работы от заряда",
                 "viewer_thought_to_trigger": "Это реально долго работает, не то что мой старый",
                 "recommended_scene_direction": "Таймер/цифры на экране, фонарь горит непрерывно"},
            ],
            "recommended_content_mix": {"pain_problem": 25, "problem_solution": 25, "demo": 30,
                                        "recipe_or_use_case": 10, "ugc_style": 5, "meme_style": 5},
            "positioning_mode": "pain",
            "ad_strategy_options": [
                {"strategy_id": "pain_problem", "title": "Через боль",
                 "main_message": "Показываем проблему покупателя и сразу даём решение.",
                 "viewer_thought": "Да, обычный фонарик светит слабо/садится быстро.",
                 "example_hook": "Фонарик, который реально выручает в темноте.",
                 "recommended_for": "Тем, кого уже подводил слабый фонарик"},
                {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
                 "main_message": "Показываем товар в действии: как он используется и чем помогает.",
                 "viewer_thought": "Вижу, как далеко он светит.",
                 "example_hook": "Показываю, как этот фонарик светит ночью.",
                 "recommended_for": "Тем, кто хочет увидеть реальную дальность света"},
                {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
                 "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                                 "делает процесс приятнее.",
                 "viewer_thought": "Такой удобно держать в машине/на даче.",
                 "example_hook": "Одна вещь, которую стоит держать в машине.",
                 "recommended_for": "Тем, кто хочет всегда иметь под рукой надёжный источник света"},
            ],
        },
    },
    "organizer_container": {
        "label": "органайзер / контейнер для хранения",
        "keywords": ("органайзер", "контейнер", "хранени", "organizer", "storage box",
                    "кофр", "бокс для хранения"),
        "report": {
            "core_problem_solved": (
                "Вещи разбросаны и хранятся в беспорядке, из-за чего сложно быстро найти нужное."
            ),
            "secondary_problems_solved": [
                "Захламлённое пространство визуально раздражает",
                "Мелкие вещи теряются или закатываются в труднодоступные места",
                "На поиск нужной вещи уходит много времени",
            ],
            "ideal_customer_segments": [
                {"segment": "Люди с маленькой квартирой/ограниченным пространством",
                 "why_this_segment_cares": "Каждый см³ хранения на счету", "pain_level": 4},
                {"segment": "Родители с детскими вещами/игрушками",
                 "why_this_segment_cares": "Много мелких предметов, которые быстро создают хаос",
                 "pain_level": 4},
                {"segment": "Любители порядка (organization enthusiasts)",
                 "why_this_segment_cares": "Получают эмоциональное удовольствие от системного хранения",
                 "pain_level": 3},
            ],
            "jobs_to_be_done": [
                {"job": "Быстро найти нужную вещь без раскопок", "context": "сборы на работу/учёбу",
                 "priority": 5},
                {"job": "Освободить видимое пространство от хаоса", "context": "уборка дома", "priority": 4},
                {"job": "Компактно хранить много мелких предметов",
                 "context": "ограниченное пространство шкафа/ящика", "priority": 4},
            ],
            "pain_points": [
                {"pain": "Долгие поиски нужной вещи в общей куче",
                 "why_it_happens": "нет разделения по категориям", "severity": 4},
                {"pain": "Вещи мнутся/ломаются при хранении навалом",
                 "why_it_happens": "отсутствие отдельных отсеков", "severity": 3},
                {"pain": "Постоянный визуальный беспорядок раздражает",
                 "why_it_happens": "нет единой системы хранения", "severity": 3},
            ],
            "desired_outcomes": [
                {"outcome": "Порядок и системность в хранении", "type": "emotional"},
                {"outcome": "Экономия времени на поиск вещей", "type": "practical"},
                {"outcome": "Компактное использование пространства", "type": "functional"},
            ],
            "product_benefits": [
                {"benefit": "Отдельные отсеки под каждую категорию вещей",
                 "mapped_to_pain": "Долгие поиски нужной вещи в общей куче"},
                {"benefit": "Прочная форма защищает содержимое",
                 "mapped_to_pain": "Вещи мнутся/ломаются при хранении навалом"},
                {"benefit": "Аккуратный внешний вид на полке/в шкафу",
                 "mapped_to_pain": "Постоянный визуальный беспорядок раздражает"},
            ],
            "likely_objections": [
                {"objection": "Не влезет в мой шкаф/ящик по размеру",
                 "response_angle": "Показать размеры и варианты установки"},
                {"objection": "Хватит ли отсеков под мои вещи",
                 "response_angle": "Показать реальное наполнение на примере"},
                {"objection": "Может выглядеть дёшево/пластиково",
                 "response_angle": "Крупный план материала и качества сборки"},
            ],
            "use_cases": [
                {"scenario": "Хранение косметики в ванной",
                 "why_product_fits": "Разделение по категориям, всё на виду"},
                {"scenario": "Детские игрушки/канцелярия",
                 "why_product_fits": "Быстрая уборка -- всё по местам за минуту"},
                {"scenario": "Гараж/кладовка с инструментами",
                 "why_product_fits": "Компактное хранение мелких деталей"},
            ],
            "hook_angles": [
                {"angle_type": "pain", "hook": "Каждое утро 5 минут ищешь одну и ту же вещь в этом бардаке",
                 "why_it_should_work": "Узнаваемая бытовая раздражающая ситуация"},
                {"angle_type": "demo", "hook": "Разбираем полный хаос за 60 секунд",
                 "why_it_should_work": "Сатисфакция от before/after организации"},
                {"angle_type": "comparison", "hook": "Ящик до и после органайзера",
                 "why_it_should_work": "Визуальный контраст -- сильный триггер"},
                {"angle_type": "problem_solution", "hook": "Как перестать терять мелкие вещи дома",
                 "why_it_should_work": "Прямое обещание решения"},
                {"angle_type": "ugc", "hook": "Показываю свою систему хранения, которая реально работает",
                 "why_it_should_work": "Формат из уст обычного человека вызывает доверие"},
            ],
            "video_message_angles": [
                {"angle": "Хаотичный ящик превращается в организованное пространство",
                 "viewer_thought_to_trigger": "У меня точно такой же бардак, надо навести порядок",
                 "recommended_scene_direction": "До: свалка вещей крупным планом. После: аккуратные "
                                                "отсеки, всё разложено"},
            ],
            "recommended_content_mix": {"pain_problem": 20, "problem_solution": 20, "demo": 30,
                                        "recipe_or_use_case": 15, "ugc_style": 10, "meme_style": 5},
            "positioning_mode": "pain",
            "ad_strategy_options": [
                {"strategy_id": "pain_problem", "title": "Через боль",
                 "main_message": "Показываем проблему покупателя и сразу даём решение.",
                 "viewer_thought": "Да, у меня дома тоже такой бардак.",
                 "example_hook": "Опять не могу найти нужную вещь в этом ящике?",
                 "recommended_for": "Тем, кто уже устал от беспорядка и активно ищет решение"},
                {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
                 "main_message": "Показываем товар в действии: как он используется и чем помогает.",
                 "viewer_thought": "Понятно, как это организовать.",
                 "example_hook": "Вот как я навела порядок в ящике за 60 секунд.",
                 "recommended_for": "Тем, кто хочет сначала увидеть результат вживую"},
                {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
                 "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                                 "делает процесс приятнее.",
                 "viewer_thought": "Это удобно, надо попробовать.",
                 "example_hook": "Органайзер, после которого я перестала терять вещи.",
                 "recommended_for": "Тем, кто ценит порядок и эстетику"},
            ],
        },
    },
    "kitchen_accessory_generic": {
        "label": "кухонный аксессуар (общая категория)",
        "keywords": ("кухон", "посуда", "kitchen", "разделочная доска", "форма для выпечки",
                    "кухонный аксессуар"),
        "report": {
            "core_problem_solved": (
                "Стандартные кухонные инструменты/принадлежности неудобны в ежедневном "
                "использовании: занимают время, требуют лишних усилий или сложны в уходе."
            ),
            "secondary_problems_solved": [
                "Приходится использовать несколько разных предметов для одной задачи",
                "Уборка/мойка после использования отнимает время",
                "Хранение занимает много места на кухне",
            ],
            "ideal_customer_segments": [
                {"segment": "Люди, готовящие дома каждый день",
                 "why_this_segment_cares": "Любое неудобство повторяется ежедневно и накапливает "
                                          "раздражение", "pain_level": 4},
                {"segment": "Семьи с детьми, готовящие много и часто",
                 "why_this_segment_cares": "Нужна скорость и простота в приготовлении и уборке",
                 "pain_level": 4},
                {"segment": "Те, кто ценит порядок и компактность на кухне",
                 "why_this_segment_cares": "Хотят меньше лишних предметов на столешнице", "pain_level": 3},
            ],
            "jobs_to_be_done": [
                {"job": "Упростить повторяющийся кухонный процесс", "context": "ежедневная готовка",
                 "priority": 4},
                {"job": "Сократить время на уборку после готовки", "context": "после ужина", "priority": 4},
                {"job": "Сэкономить место на кухне", "context": "маленькая кухня/ограниченное хранение",
                 "priority": 3},
            ],
            "pain_points": [
                {"pain": "Задача занимает больше времени, чем хотелось бы",
                 "why_it_happens": "стандартный инструмент не оптимизирован под задачу", "severity": 3},
                {"pain": "После использования долго мыть/чистить",
                 "why_it_happens": "сложная форма или материал, который пачкается", "severity": 4},
                {"pain": "Инструмент/предмет занимает много места при хранении",
                 "why_it_happens": "неудобная форма/размер", "severity": 2},
            ],
            "desired_outcomes": [
                {"outcome": "Быстрее и проще выполнять привычную кухонную задачу", "type": "functional"},
                {"outcome": "Меньше уборки после готовки", "type": "practical"},
                {"outcome": "Опрятная, организованная кухня", "type": "emotional"},
            ],
            "product_benefits": [
                {"benefit": "Упрощает повторяющийся процесс на кухне",
                 "mapped_to_pain": "Задача занимает больше времени, чем хотелось бы"},
                {"benefit": "Легко моется/чистится",
                 "mapped_to_pain": "После использования долго мыть/чистить"},
                {"benefit": "Компактно хранится",
                 "mapped_to_pain": "Инструмент/предмет занимает много места при хранении"},
            ],
            "likely_objections": [
                {"objection": "Не уверен, что это действительно упростит процесс",
                 "response_angle": "Показать реальное сравнение времени/усилий до и после"},
                {"objection": "У меня уже есть похожий инструмент",
                 "response_angle": "Подчеркнуть конкретное отличие/улучшение по сравнению со "
                                   "стандартным вариантом"},
                {"objection": "Насколько это качественно и долговечно",
                 "response_angle": "Показать материал крупным планом и заявленный срок службы"},
            ],
            "use_cases": [
                {"scenario": "Повседневная готовка ужина",
                 "why_product_fits": "Упрощает конкретный повторяющийся шаг процесса"},
                {"scenario": "Готовка для гостей/большой компании",
                 "why_product_fits": "Экономит время при увеличенном объёме готовки"},
            ],
            "hook_angles": [
                {"angle_type": "pain", "hook": "Вот что бесит в готовке на обычной кухне каждый день",
                 "why_it_should_work": "Узнаваемая бытовая боль"},
                {"angle_type": "demo",
                 "hook": "Показываю, как этот кухонный аксессуар упрощает привычную задачу",
                 "why_it_should_work": "Наглядная демонстрация выгоды"},
                {"angle_type": "problem_solution", "hook": "Больше не трачу лишнее время на это на кухне",
                 "why_it_should_work": "Прямое обещание экономии времени"},
            ],
            "video_message_angles": [
                {"angle": "До/после использования на кухне",
                 "viewer_thought_to_trigger": "О, у меня та же морока на кухне. Хочу так же просто.",
                 "recommended_scene_direction": "Показать привычный неудобный способ, затем с продуктом"},
            ],
            "recommended_content_mix": {"pain_problem": 25, "problem_solution": 25, "demo": 25,
                                        "recipe_or_use_case": 15, "ugc_style": 5, "meme_style": 5},
            "positioning_mode": "pain",
            "ad_strategy_options": [
                {"strategy_id": "pain_problem", "title": "Через боль",
                 "main_message": "Показываем проблему покупателя и сразу даём решение.",
                 "viewer_thought": "Да, у меня та же морока на кухне каждый день.",
                 "example_hook": "Вот что бесит в готовке на обычной кухне.",
                 "recommended_for": "Тем, кто уже сталкивается с этим неудобством регулярно"},
                {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
                 "main_message": "Показываем товар в действии: как он используется и чем помогает.",
                 "viewer_thought": "Так вот как это работает.",
                 "example_hook": "Показываю, как этот аксессуар упрощает привычную задачу.",
                 "recommended_for": "Тем, кто хочет увидеть процесс своими глазами"},
                {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
                 "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                                 "делает процесс приятнее.",
                 "viewer_thought": "Это реально экономит время, надо попробовать.",
                 "example_hook": "Маленький аксессуар, который экономит мне полчаса каждый день.",
                 "recommended_for": "Тем, кто ценит скорость и простоту на кухне"},
            ],
        },
    },
    "beauty_selfcare_accessory": {
        "label": "бьюти / уход за собой аксессуар",
        "keywords": ("массажер", "уход за кожей", "beauty", "косметич", "скраб",
                    "маска для лица", "gua sha", "уходовое средство", "роллер для лица"),
        "report": {
            "core_problem_solved": (
                "Регулярный уход за собой (кожа/тело/волосы) отнимает время или не даёт "
                "заметного результата обычными способами."
            ),
            "secondary_problems_solved": [
                "Сложно уделять уходу за собой время каждый день",
                "Результат от обычных методов ухода малозаметен",
                "Процедуры в салоне дорогие и требуют времени на запись",
            ],
            "ideal_customer_segments": [
                {"segment": "Люди, следящие за состоянием кожи/тела дома",
                 "why_this_segment_cares": "Хотят салонный результат без затрат на салон",
                 "pain_level": 4},
                {"segment": "Занятые люди с ограниченным временем на уход",
                 "why_this_segment_cares": "Нужны быстрые эффективные ритуалы ухода", "pain_level": 4},
                {"segment": "Те, кто следит за трендами в бьюти-индустрии",
                 "why_this_segment_cares": "Хотят пробовать новые эффективные инструменты",
                 "pain_level": 3},
            ],
            "jobs_to_be_done": [
                {"job": "Получить заметный результат ухода в домашних условиях",
                 "context": "вечерний/утренний ритуал ухода", "priority": 5},
                {"job": "Сэкономить время на процедуре ухода", "context": "плотный график", "priority": 4},
                {"job": "Заменить дорогие салонные процедуры домашним аналогом",
                 "context": "регулярный уход", "priority": 3},
            ],
            "pain_points": [
                {"pain": "Обычные способы ухода не дают заметного результата",
                 "why_it_happens": "недостаточная эффективность базовых средств/техник", "severity": 4},
                {"pain": "Не хватает времени на полноценный ритуал ухода",
                 "why_it_happens": "плотный график, усталость", "severity": 3},
                {"pain": "Салонные процедуры дорогие и требуют записи заранее",
                 "why_it_happens": "ограниченный бюджет и время", "severity": 3},
            ],
            "desired_outcomes": [
                {"outcome": "Видимый результат ухода за кожей/телом", "type": "functional"},
                {"outcome": "Чувство заботы о себе", "type": "emotional"},
                {"outcome": "Быстрый и простой ритуал ухода", "type": "practical"},
            ],
            "product_benefits": [
                {"benefit": "Заметный эффект уже после нескольких применений",
                 "mapped_to_pain": "Обычные способы ухода не дают заметного результата"},
                {"benefit": "Быстрое применение, не требует много времени",
                 "mapped_to_pain": "Не хватает времени на полноценный ритуал ухода"},
                {"benefit": "Экономия по сравнению с салонными процедурами",
                 "mapped_to_pain": "Салонные процедуры дорогие и требуют записи заранее"},
            ],
            "likely_objections": [
                {"objection": "Не будет ли эффекта хуже, чем в салоне",
                 "response_angle": "Показать реальные результаты до/после в динамике"},
                {"objection": "Подойдёт ли для моего типа кожи",
                 "response_angle": "Указать ограничения/противопоказания честно, показать разные "
                                   "варианты применения"},
                {"objection": "Не окажется ли это разовой покупкой без пользы",
                 "response_angle": "Показать регулярность использования и накопительный эффект"},
            ],
            "use_cases": [
                {"scenario": "Вечерний ритуал ухода перед сном",
                 "why_product_fits": "Компактно вписывается в привычную рутину"},
                {"scenario": "Подготовка к важному событию",
                 "why_product_fits": "Быстрый заметный эффект перед выходом"},
            ],
            "hook_angles": [
                {"angle_type": "curiosity",
                 "hook": "Что если результат салонной процедуры можно получить дома за 5 минут",
                 "why_it_should_work": "Интрига + обещание экономии времени/денег"},
                {"angle_type": "demo", "hook": "Наношу/использую и показываю результат сразу",
                 "why_it_should_work": "Визуальное доказательство эффекта"},
                {"angle_type": "ugc", "hook": "Мой честный опыт использования за 2 недели",
                 "why_it_should_work": "Формат отзыва вызывает больше доверия"},
            ],
            "video_message_angles": [
                {"angle": "До/после использования на коже",
                 "viewer_thought_to_trigger": "Хочу такой же результат у себя",
                 "recommended_scene_direction": "Крупный план до и после, естественное освещение"},
            ],
            "recommended_content_mix": {"pain_problem": 20, "problem_solution": 25, "demo": 30,
                                        "recipe_or_use_case": 5, "ugc_style": 15, "meme_style": 5},
            "positioning_mode": "desire",
            "ad_strategy_options": [
                {"strategy_id": "pain_problem", "title": "Через боль",
                 "main_message": "Показываем проблему покупателя и сразу даём решение.",
                 "viewer_thought": "Да, обычный уход не даёт такого результата.",
                 "example_hook": "Почему обычный уход не работает так, как хочется?",
                 "recommended_for": "Тем, кто уже пробовал обычные способы и разочаровался"},
                {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
                 "main_message": "Показываем товар в действии: как он используется и чем помогает.",
                 "viewer_thought": "Вижу результат сразу, это работает.",
                 "example_hook": "Наношу и показываю результат прямо сейчас.",
                 "recommended_for": "Тем, кто хочет увидеть эффект до покупки"},
                {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
                 "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                                 "делает процесс приятнее.",
                 "viewer_thought": "Это быстро и приятно, надо попробовать.",
                 "example_hook": "5 минут вместо похода в салон.",
                 "recommended_for": "Тем, кто ценит удобство и экономию на салонных процедурах"},
            ],
        },
    },
    "simple_home_utility": {
        "label": "простой бытовой аксессуар/держатель/органайзер для мелочей",
        "keywords": ("держатель", "подставка", "чехол", "утилит", "бытовой",
                    "органайзер для проводов", "home utility"),
        "report": {
            "core_problem_solved": (
                "Мелкий бытовой беспорядок и неудобства (провода, мелкие вещи, отсутствие "
                "удобного места для предмета) создают ежедневное раздражение."
            ),
            "secondary_problems_solved": [
                "Нужная мелочь часто теряется или лежит не на своём месте",
                "Провода/шнуры путаются и мешают",
                "Нет удобного места для хранения/использования конкретного предмета",
            ],
            "ideal_customer_segments": [
                {"segment": "Люди, работающие/учащиеся дома за столом",
                 "why_this_segment_cares": "Рабочее место должно быть удобным и опрятным ежедневно",
                 "pain_level": 4},
                {"segment": "Автомобилисты",
                 "why_this_segment_cares": "Ограниченное пространство салона требует компактных решений",
                 "pain_level": 3},
                {"segment": "Родители с детьми",
                 "why_this_segment_cares": "Мелкие бытовые неудобства повторяются каждый день",
                 "pain_level": 3},
            ],
            "jobs_to_be_done": [
                {"job": "Держать конкретный предмет/провод в удобном, предсказуемом месте",
                 "context": "рабочий стол/дом/машина", "priority": 4},
                {"job": "Избавиться от мелкого раздражающего беспорядка",
                 "context": "повседневный быт", "priority": 4},
                {"job": "Сэкономить время на поиске/настройке нужной вещи",
                 "context": "ежедневное использование", "priority": 3},
            ],
            "pain_points": [
                {"pain": "Мелкая вещь/провод постоянно теряется или путается",
                 "why_it_happens": "нет фиксированного удобного места", "severity": 3},
                {"pain": "Пространство выглядит захламлённым",
                 "why_it_happens": "отсутствие системы организации", "severity": 2},
                {"pain": "Приходится каждый раз тратить время на одно и то же неудобство",
                 "why_it_happens": "нет специального решения под задачу", "severity": 3},
            ],
            "desired_outcomes": [
                {"outcome": "Порядок и предсказуемость в мелочах", "type": "practical"},
                {"outcome": "Меньше раздражения от бытовых мелочей", "type": "emotional"},
                {"outcome": "Удобное фиксированное место для предмета", "type": "functional"},
            ],
            "product_benefits": [
                {"benefit": "Фиксированное удобное место для предмета",
                 "mapped_to_pain": "Мелкая вещь/провод постоянно теряется или путается"},
                {"benefit": "Аккуратный внешний вид пространства",
                 "mapped_to_pain": "Пространство выглядит захламлённым"},
                {"benefit": "Решает неудобство один раз и надолго",
                 "mapped_to_pain": "Приходится каждый раз тратить время на одно и то же неудобство"},
            ],
            "likely_objections": [
                {"objection": "Мелочь, можно и без неё обойтись",
                 "response_angle": "Показать накопительный эффект маленького неудобства за месяц/год"},
                {"objection": "Подойдёт ли это конкретно под мой случай",
                 "response_angle": "Показать несколько вариантов применения на видео"},
                {"objection": "Не будет ли выглядеть как ненужная мелочь на столе/в машине",
                 "response_angle": "Показать компактность и аккуратный дизайн крупным планом"},
            ],
            "use_cases": [
                {"scenario": "Рабочий стол с проводами от техники",
                 "why_product_fits": "Фиксирует провода/предметы в одном месте"},
                {"scenario": "Салон автомобиля", "why_product_fits": "Компактное решение под "
                                                                    "ограниченное пространство"},
            ],
            "hook_angles": [
                {"angle_type": "pain", "hook": "Эта мелочь бесит каждый день, а решается за 2 секунды",
                 "why_it_should_work": "Узнаваемое мелкое раздражение + простое обещание решения"},
                {"angle_type": "demo",
                 "hook": "Показываю, куда обычно теряется эта вещь -- и как это исправить",
                 "why_it_should_work": "Наглядность решает лучше объяснений"},
                {"angle_type": "meme", "hook": "Когда наконец нашёл решение той самой бытовой мелочи",
                 "why_it_should_work": "Юмористический узнаваемый формат повышает вовлечённость"},
            ],
            "video_message_angles": [
                {"angle": "Повседневная мелкая проблема -> простое решение",
                 "viewer_thought_to_trigger": "У меня та же история происходит постоянно",
                 "recommended_scene_direction": "Показать привычную мелкую проблему крупным планом, "
                                                "затем решение"},
            ],
            "recommended_content_mix": {"pain_problem": 25, "problem_solution": 25, "demo": 25,
                                        "recipe_or_use_case": 10, "ugc_style": 10, "meme_style": 5},
            "positioning_mode": "pain",
            "ad_strategy_options": [
                {"strategy_id": "pain_problem", "title": "Через боль",
                 "main_message": "Показываем проблему покупателя и сразу даём решение.",
                 "viewer_thought": "Да, у меня та же мелочь постоянно теряется/мешает.",
                 "example_hook": "Эта мелочь бесит каждый день, а решается за 2 секунды.",
                 "recommended_for": "Тем, кого уже раздражает эта бытовая мелочь"},
                {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
                 "main_message": "Показываем товар в действии: как он используется и чем помогает.",
                 "viewer_thought": "Понятно, куда это девать и как использовать.",
                 "example_hook": "Показываю, куда обычно теряется эта вещь -- и как это исправить.",
                 "recommended_for": "Тем, кто хочет сразу понять, как это применить у себя"},
                {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
                 "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                                 "делает процесс приятнее.",
                 "viewer_thought": "Удобная мелочь, надо взять себе такую же.",
                 "example_hook": "Маленькая вещь, которая экономит нервы каждый день.",
                 "recommended_for": "Тем, кто ценит порядок в мелочах"},
            ],
        },
    },
}

GENERIC_FALLBACK_TEMPLATE = {
    "label": "неизвестная категория (общая гипотеза)",
    "report": {
        "core_problem_solved": (
            "Недостаточно данных для точного определения проблемы -- ниже приведена общая "
            "гипотеза на основе названия и описания товара, требует ручной проверки владельцем."
        ),
        "secondary_problems_solved": [
            "Гипотеза: пользователь тратит больше времени/усилий на задачу, которую решает "
            "этот товар, чем хотелось бы",
        ],
        "ideal_customer_segments": [
            {"segment": "Покупатели, ищущие решение задачи, связанной с этим товаром",
             "why_this_segment_cares": "Гипотеза на основе общей категории товара, требует уточнения",
             "pain_level": 2},
        ],
        "jobs_to_be_done": [
            {"job": "Решить задачу, для которой предназначен товар",
             "context": "неизвестно, требуется уточнение от владельца", "priority": 2},
        ],
        "pain_points": [
            {"pain": "Неизвестно точно -- недостаточно данных о товаре",
             "why_it_happens": "продукт не попал ни в одну известную эвристическую категорию",
             "severity": 1},
        ],
        "desired_outcomes": [
            {"outcome": "Получить пользу, заявленную в описании товара", "type": "functional"},
        ],
        "product_benefits": [
            {"benefit": "См. описание товара продавца",
             "mapped_to_pain": "Неизвестно точно -- недостаточно данных о товаре"},
        ],
        "likely_objections": [
            {"objection": "Неизвестно, насколько товар решает мою задачу",
             "response_angle": "Владельцу нужно вручную заполнить positioning-поля (who_is_this_for, "
                               "what_problem_does_it_usually_solve и т.д.) для точного анализа"},
        ],
        "use_cases": [
            {"scenario": "Общее использование по назначению товара",
             "why_product_fits": "Требуется уточнение от владельца"},
        ],
        "hook_angles": [
            {"angle_type": "curiosity",
             "hook": "[Требует ручного заполнения] -- сформулируйте боль/интригу самостоятельно",
             "why_it_should_work": "Автоматический движок не нашёл уверенного паттерна для этого товара"},
        ],
        "video_message_angles": [
            {"angle": "[Требует ручного заполнения]",
             "viewer_thought_to_trigger": "неизвестно без дополнительных данных",
             "recommended_scene_direction": "Заполните positioning-поля в форме товара для точной гипотезы"},
        ],
        "recommended_content_mix": {"pain_problem": 15, "problem_solution": 15, "demo": 20,
                                    "recipe_or_use_case": 15, "ugc_style": 20, "meme_style": 15},
        "positioning_mode": "pain",
        "ad_strategy_options": [
            {"strategy_id": "pain_problem", "title": "Через боль",
             "main_message": "Показываем проблему покупателя и сразу даём решение.",
             "viewer_thought": "неизвестно без дополнительных данных",
             "example_hook": "[Требует ручного заполнения]",
             "recommended_for": "Требуется уточнение от владельца"},
            {"strategy_id": "demo_use_case", "title": "Через демонстрацию",
             "main_message": "Показываем товар в действии: как он используется и чем помогает.",
             "viewer_thought": "неизвестно без дополнительных данных",
             "example_hook": "[Требует ручного заполнения]",
             "recommended_for": "Требуется уточнение от владельца"},
            {"strategy_id": "benefit_convenience", "title": "Через выгоду / удобство",
             "main_message": "Показываем, как товар экономит время, упрощает жизнь или "
                             "делает процесс приятнее.",
             "viewer_thought": "неизвестно без дополнительных данных",
             "example_hook": "[Требует ручного заполнения]",
             "recommended_for": "Требуется уточнение от владельца"},
        ],
    },
}

# every hook angle defaults to enabled=True so the owner can toggle
# individual angles off later (TASK 4 manual override)
for _spec in list(CATEGORY_TEMPLATES.values()) + [GENERIC_FALLBACK_TEMPLATE]:
    for _hook in _spec["report"]["hook_angles"]:
        _hook.setdefault("enabled", True)


def _match_category(search_text: str):
    text_l = search_text.lower()
    best_id, best_hits = None, 0
    for cat_id, spec in CATEGORY_TEMPLATES.items():
        hits = sum(1 for kw in spec["keywords"] if kw in text_l)
        if hits > best_hits:
            best_id, best_hits = cat_id, hits
    if best_id is None:
        return "generic_fallback", 0
    return best_id, best_hits


def _apply_manual_overrides(report: dict, product_data: dict) -> None:
    problem = (product_data.get("what_problem_does_it_usually_solve") or "").strip()
    who = (product_data.get("who_is_this_for") or "").strip()
    benefits = _as_list(product_data.get("top_3_benefits"))
    use_cases = _as_list(product_data.get("use_cases"))
    questions = _as_list(product_data.get("common_questions"))
    objections = _as_list(product_data.get("objections"))
    avoid = _as_list(product_data.get("what_should_not_be_claimed"))
    tone = (product_data.get("tone_preference") or "").strip()

    if problem:
        report["core_problem_solved"] = problem
        report["match_confidence"] = "high"
        report["match_confidence_score"] = max(report.get("match_confidence_score", 0), 0.95)

    if who:
        why = (product_data.get("why_people_buy_it") or
              "Продавец указал эту аудиторию как основную").strip()
        report["ideal_customer_segments"].insert(0, {
            "segment": who, "why_this_segment_cares": why, "pain_level": 5,
        })

    for b in reversed(benefits):
        report["product_benefits"].insert(0, {"benefit": b, "mapped_to_pain": "Указано продавцом вручную"})

    for u in reversed(use_cases):
        report["use_cases"].insert(0, {"scenario": u, "why_product_fits": "Указано продавцом вручную"})

    for q in questions:
        report["likely_objections"].append({
            "objection": q,
            "response_angle": "Частый вопрос от продавца -- ответить на него заранее в статье/видео/описании",
        })

    for o in objections:
        report["likely_objections"].append({
            "objection": o,
            "response_angle": "Указано продавцом вручную -- подготовьте ответ заранее",
        })

    if avoid:
        report["claims_to_avoid"] = avoid

    if tone:
        report["tone_preference"] = tone

    report["manual_override_present"] = bool(
        problem or who or benefits or use_cases or questions or objections or avoid or tone)


def analyze_product_intelligence(product_data: dict) -> dict:
    """Fail-closed: requires a non-empty product_name. Zero network calls --
    pure local rule-based matching. Always returns needs_owner_review=True;
    never presents a hypothesis as verified fact."""
    if not isinstance(product_data, dict):
        raise ProductIntelligenceError("INVALID_PRODUCT_DATA", "product_data must be a dict")

    product_name = (product_data.get("product_name") or "").strip()
    if not product_name:
        raise ProductIntelligenceError(
            "MISSING_PRODUCT_NAME",
            "product_name is required to run product intelligence analysis")

    search_text = " ".join(filter(None, [
        product_data.get("product_name", ""),
        product_data.get("category", ""),
        product_data.get("product_description", ""),
        product_data.get("marketplace_title", ""),
    ]))
    category_id, hits = _match_category(search_text)
    template = CATEGORY_TEMPLATES.get(category_id, GENERIC_FALLBACK_TEMPLATE)
    report = copy.deepcopy(template["report"])

    if hits >= 3:
        confidence_label, confidence_score = "high", 0.85
    elif hits >= 1:
        confidence_label, confidence_score = "medium", 0.6
    else:
        confidence_label, confidence_score = "low", 0.25

    report["matched_category"] = category_id
    report["match_confidence"] = confidence_label
    report["match_confidence_score"] = confidence_score
    if category_id == "generic_fallback":
        report["confidence_notes"] = (
            "Совпадений по ключевым словам не найдено -- это общая гипотеза с низкой "
            "уверенностью, а не проверенный факт. Заполните positioning-поля вручную "
            "(who_is_this_for, what_problem_does_it_usually_solve и т.д.) или отредактируйте "
            "гипотезу перед использованием в контенте."
        )
    else:
        report["confidence_notes"] = (
            f"Гипотеза основана на совпадении по ключевым словам с категорией "
            f"'{template['label']}' ({hits} совпадени(й)). Это эвристика, а не точный факт -- "
            f"проверьте и одобрите вручную перед использованием в контенте."
        )
    report["needs_owner_review"] = True
    # MVP default recommendation: test all three ad-strategy angles rather than
    # committing to one -- owner can pick a single angle later via set_ad_strategy.
    report.setdefault("selected_ad_strategy", "multi_angle_test")

    _apply_manual_overrides(report, product_data)

    used_fields = [k for k in (
        "product_name", "category", "product_description", "marketplace_title",
        *MANUAL_POSITIONING_FIELDS,
    ) if product_data.get(k)]
    report["source_fields_used"] = used_fields

    return report


# -- storage -------------------------------------------------------------------

def intelligence_path(client_id: str, product_id: str, repo_root: str = ".") -> Path:
    return st.product_dir(client_id, product_id, repo_root) / "product-intelligence.json"


def _save_envelope(envelope: dict, client_id: str, product_id: str, repo_root: str = ".") -> Path:
    path = intelligence_path(client_id, product_id, repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_product_intelligence(client_id: str, product_id: str, repo_root: str = ".",
                               product_data: dict = None, approved_by_owner: bool = False,
                               approval_notes: str = "") -> dict:
    """Runs the engine against the product's own product.json (optionally
    merged with extra override fields), writes product-intelligence.json,
    returns the stored envelope."""
    product = st.load_product(client_id, product_id, repo_root)
    base_data = asdict(product)
    if product_data:
        base_data.update({k: v for k, v in product_data.items() if v})

    report = analyze_product_intelligence(base_data)
    envelope = {
        "generated_at": utcnow_iso(),
        "source_fields_used": report.pop("source_fields_used", []),
        "manual_override_present": report.pop("manual_override_present", False),
        "approved_by_owner": approved_by_owner,
        "approval_notes": approval_notes,
        "report": report,
    }
    _save_envelope(envelope, client_id, product_id, repo_root)
    return envelope


def load_product_intelligence(client_id: str, product_id: str, repo_root: str = "."):
    path = intelligence_path(client_id, product_id, repo_root)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_or_error(client_id: str, product_id: str, repo_root: str) -> dict:
    envelope = load_product_intelligence(client_id, product_id, repo_root)
    if envelope is None:
        raise ProductIntelligenceError(
            "INTELLIGENCE_NOT_FOUND",
            "no product-intelligence.json to update -- generate it first")
    return envelope


def approve_product_intelligence(client_id: str, product_id: str, repo_root: str = ".",
                                 approval_notes: str = "") -> dict:
    envelope = _load_or_error(client_id, product_id, repo_root)
    envelope["approved_by_owner"] = True
    envelope["approval_notes"] = approval_notes
    _save_envelope(envelope, client_id, product_id, repo_root)
    return envelope


def regenerate_product_intelligence(client_id: str, product_id: str, repo_root: str = ".") -> dict:
    """Re-runs the engine from the CURRENT product.json. Resets
    approved_by_owner=False since the underlying content changed -- never
    silently keeps a stale approval on regenerated content."""
    return write_product_intelligence(client_id, product_id, repo_root,
                                      approved_by_owner=False, approval_notes="")


def set_primary_problem(client_id: str, product_id: str, repo_root: str = ".",
                        problem_text: str = "") -> dict:
    problem_text = (problem_text or "").strip()
    if not problem_text:
        raise ProductIntelligenceError("EMPTY_PRIMARY_PROBLEM", "problem_text must not be empty")
    envelope = _load_or_error(client_id, product_id, repo_root)
    envelope["report"]["core_problem_solved"] = problem_text
    envelope["manual_override_present"] = True
    _save_envelope(envelope, client_id, product_id, repo_root)
    return envelope


def set_positioning_mode(client_id: str, product_id: str, repo_root: str = ".",
                         mode: str = "") -> dict:
    if mode not in POSITIONING_MODES:
        raise ProductIntelligenceError("UNKNOWN_POSITIONING_MODE",
                                       f"mode must be one of {POSITIONING_MODES}, got {mode!r}")
    envelope = _load_or_error(client_id, product_id, repo_root)
    envelope["report"]["positioning_mode"] = mode
    envelope["manual_override_present"] = True
    _save_envelope(envelope, client_id, product_id, repo_root)
    return envelope


def set_ad_strategy(client_id: str, product_id: str, repo_root: str = ".",
                    strategy_id: str = "") -> dict:
    if strategy_id not in AD_STRATEGY_IDS:
        raise ProductIntelligenceError("UNKNOWN_AD_STRATEGY",
                                       f"strategy_id must be one of {AD_STRATEGY_IDS}, "
                                       f"got {strategy_id!r}")
    envelope = _load_or_error(client_id, product_id, repo_root)
    envelope["report"]["selected_ad_strategy"] = strategy_id
    envelope["manual_override_present"] = True
    _save_envelope(envelope, client_id, product_id, repo_root)
    return envelope


def toggle_hook_angle(client_id: str, product_id: str, repo_root: str = ".",
                      index: int = -1, enabled: bool = True) -> dict:
    envelope = _load_or_error(client_id, product_id, repo_root)
    hooks = envelope["report"]["hook_angles"]
    if index < 0 or index >= len(hooks):
        raise ProductIntelligenceError("HOOK_ANGLE_INDEX_OUT_OF_RANGE",
                                       f"index {index} out of range for {len(hooks)} hook angles")
    hooks[index]["enabled"] = bool(enabled)
    envelope["manual_override_present"] = True
    _save_envelope(envelope, client_id, product_id, repo_root)
    return envelope
