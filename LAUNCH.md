# 🚀 Запуск бота — турнкей-чеклист (≈15 мин)

Делай по порядку. Значения, которые можно, уже подставлены.

## 1. Канал + бот (Telegram)
- [ ] Создай канал (публичный, с @username), запиши ссылку `https://t.me/ТВОЙ_КАНАЛ`
- [ ] @BotFather → `/newbot` → скопируй **токен** (это секрет!)
- [ ] Добавь бота **админом** канала (право «Публикация сообщений»)

## 2. Залить код на GitHub
Создай пустой репозиторий на github.com (напр. `airfryer-bot`), затем в терминале:
```bash
cd D:\OzonGrowthProject\telegram-bot
git remote add origin https://github.com/ТВОЙ_ЛОГИН/airfryer-bot.git
git push -u origin main
```
(репозиторий уже инициализирован и закоммичен — нужен только remote + push)

## 3. Деплой на Railway
- [ ] [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → выбери `airfryer-bot`
- [ ] Вкладка **Variables** → добавь переменные (вставь блок ниже, подставь свои токен и канал):

```
BOT_TOKEN=ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER
CHANNEL_ID=@ТВОЙ_КАНАЛ
OZON_ARTIKUL=1931921872
OZON_LINK=https://www.ozon.ru/product/1931921872/
TG_CHANNEL_LINK=https://t.me/ТВОЙ_КАНАЛ
POST_TIMES=10:00
TZ=Europe/Moscow
CTA_EVERY=4
```
- [ ] Railway сам соберёт и запустит (Dockerfile). В разделе **Deployments/Logs** должно появиться `Бот запущен (long-polling).`

## 4. Смоук-тест (проверь, что живой)
- [ ] Открой своего бота в Telegram → `/start` → пришёл файл с 50 рецептами ✅ (выдача работает)
- [ ] Чтобы проверить автопостинг сразу: временно поставь `POST_TIMES` на ближайшую минуту (напр. текущее время +2 мин по Москве), сохрани → дождись поста в канале → верни `10:00`
- [ ] Если пост не пришёл — проверь, что бот **админ канала** и `CHANNEL_ID` верный (см. Logs)

## Готово ✅
Дальше бот сам: выдаёт рецепты по `/start` и постит в канал ежедневно с CTA на Ozon.
Свои рецепты добавляй в `recipes.json` → `git push` → Railway передеплоит автоматически.
