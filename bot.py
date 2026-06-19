"""
💰 Digital Shop Bot v2
pip install python-telegram-bot==20.7 psycopg2-binary==2.9.9
python bot.py
"""

import logging, os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    PreCheckoutQueryHandler, MessageHandler, ConversationHandler,
    filters, ContextTypes
)
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))

(
    A_MENU,
    A_ADD_NAME, A_ADD_DESC, A_ADD_PRICE, A_ADD_CONTENT, A_ADD_FILE,
    A_EDIT_FIELD, A_EDIT_VALUE,
) = range(8)

# ── Products ──────────────────────────────────────────────────────────────────

def get_products(active_only=True):
    q = "SELECT * FROM products"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY id"
    return db.fetchall(q)

def get_product(pid):
    return db.fetchone("SELECT * FROM products WHERE id=?", (pid,))

def add_product(name, desc, price, content=None, file_id=None, file_name=None):
    if db.DATABASE_URL:
        return db.execute(
            "INSERT INTO products (name,description,price_stars,content,file_id,file_name) VALUES(?,?,?,?,?,?) RETURNING id",
            (name, desc, price, content, file_id, file_name)
        )
    else:
        return db.execute(
            "INSERT INTO products (name,description,price_stars,content,file_id,file_name) VALUES(?,?,?,?,?,?)",
            (name, desc, price, content, file_id, file_name)
        )

def update_product(pid, field, value):
    allowed = {"name","description","price_stars","content","file_id","file_name","active"}
    if field not in allowed:
        return
    db.execute(f"UPDATE products SET {field}=? WHERE id=?", (value, pid))

def delete_product(pid):
    db.execute("UPDATE products SET active=0 WHERE id=?", (pid,))

# ── Sales ─────────────────────────────────────────────────────────────────────

def log_sale(user_id, product_id, stars):
    db.execute(
        "INSERT INTO sales (user_id,product_id,stars) VALUES(?,?,?)",
        (user_id, product_id, stars)
    )

def get_stats():
    total_sales = db.fetchone("SELECT COUNT(*) as c FROM sales")["c"]
    total_stars = db.fetchone("SELECT COALESCE(SUM(stars),0) as s FROM sales")["s"]
    today       = db.fetchone("SELECT COUNT(*) as c FROM sales WHERE DATE(ts)=CURRENT_DATE")["c"]
    top         = db.fetchall("""
        SELECT p.name, COUNT(*) as cnt
        FROM sales s JOIN products p ON s.product_id=p.id
        GROUP BY p.name ORDER BY cnt DESC LIMIT 3
    """)
    subs        = db.fetchone("SELECT COUNT(*) as c FROM subscriptions WHERE sub_end > CURRENT_TIMESTAMP")["c"]
    return total_sales, total_stars, today, top, subs

# ── Subscriptions ─────────────────────────────────────────────────────────────

def get_subscription(user_id):
    return db.fetchone("SELECT * FROM subscriptions WHERE user_id=?", (user_id,))

def is_subscribed(user_id):
    sub = get_subscription(user_id)
    if not sub:
        return False
    return datetime.fromisoformat(str(sub["sub_end"])) > datetime.now()

def activate_subscription(user_id, username, plan, days=30):
    sub = get_subscription(user_id)
    if sub and datetime.fromisoformat(str(sub["sub_end"])) > datetime.now():
        new_end = datetime.fromisoformat(str(sub["sub_end"])) + timedelta(days=days)
    else:
        new_end = datetime.now() + timedelta(days=days)
    db.execute("""
        INSERT INTO subscriptions (user_id, username, plan, sub_end)
        VALUES (?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=EXCLUDED.username,
            plan=EXCLUDED.plan,
            sub_end=EXCLUDED.sub_end
    """, (user_id, username or "", plan, new_end.isoformat()))
    return new_end

def get_all_subscribers():
    return db.fetchall(
        "SELECT * FROM subscriptions WHERE sub_end > CURRENT_TIMESTAMP ORDER BY sub_end"
    )

# ── Keyboards ─────────────────────────────────────────────────────────────────

def is_admin(user_id):
    return user_id == ADMIN_ID

def catalog_kb():
    products = get_products()
    kb = []
    for p in products:
        kb.append([InlineKeyboardButton(
            f"{p['name']}  ·  {p['price_stars']}⭐",
            callback_data=f"item:{p['id']}"
        )])
    kb.append([InlineKeyboardButton("🤖 Бот рассылки — купить доступ", callback_data="sub:choose")])
    kb.append([InlineKeyboardButton("🏠 Главная", callback_data="home")])
    return InlineKeyboardMarkup(kb)

def admin_main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить товар", callback_data="adm:add")],
        [InlineKeyboardButton("📋 Список товаров", callback_data="adm:list")],
        [InlineKeyboardButton("👥 Подписчики",     callback_data="adm:subs")],
        [InlineKeyboardButton("📊 Статистика",     callback_data="adm:stats")],
        [InlineKeyboardButton("❌ Закрыть",        callback_data="adm:close")],
    ])

# ── USER ──────────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("📞 Поддержка", url="https://t.me/m16el1n0")],
    ])
    await update.message.reply_text(
        "👋 Привет! Это магазин цифровых товаров.\n\nОплата — Telegram Stars ⭐",
        reply_markup=kb,
    )

async def show_catalog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🛒 *Каталог:*", reply_markup=catalog_kb(), parse_mode="Markdown")

async def show_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    p = get_product(pid)
    if not p:
        await q.edit_message_text("Товар не найден.")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"💳 Купить — {p['price_stars']}⭐", callback_data=f"buy:{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data="catalog")],
    ])
    await q.edit_message_text(f"*{p['name']}*\n\n{p['description']}", reply_markup=kb, parse_mode="Markdown")

async def buy_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[1])
    p = get_product(pid)
    if not p:
        return
    await ctx.bot.send_invoice(
        chat_id=q.from_user.id,
        title=p["name"],
        description=p["description"][:255],
        payload=f"product:{pid}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(p["name"], p["price_stars"])],
    )

async def sub_choose(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id
    sub = get_subscription(user_id)
    status_text = ""
    if sub and datetime.fromisoformat(str(sub["sub_end"])) > datetime.now():
        end = datetime.fromisoformat(str(sub["sub_end"])).strftime("%d.%m.%Y")
        status_text = f"✅ У тебя активна подписка до *{end}*\n\n"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 500⭐ + 25⭐/мес", callback_data="sub:buy:entry")],
        [InlineKeyboardButton("📅 200⭐/мес",         callback_data="sub:buy:monthly")],
        [InlineKeyboardButton("◀️ Назад",             callback_data="catalog")],
    ])
    await q.edit_message_text(
        f"{status_text}"
        f"🤖 *Бот рассылки с таблицы*\n\n"
        f"Загружаешь CSV с контактами — бот рассылает через твой Telegram аккаунт.\n\n"
        f"*🔑 Разовый взнос + ежемесячно*\n"
        f"500⭐ один раз + 25⭐ каждый месяц\n\n"
        f"*📅 Ежемесячная подписка*\n"
        f"200⭐ каждый месяц без взноса",
        reply_markup=kb, parse_mode="Markdown"
    )

async def sub_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    plan = q.data.split(":")[2]
    if plan == "entry":
        title = "Бот рассылки — разовый взнос"
        desc  = "Подключение к боту рассылки на 30 дней. Далее 25⭐/мес."
        price = 500
    else:
        title = "Бот рассылки — подписка на месяц"
        desc  = "Доступ к боту рассылки на 30 дней."
        price = 200
    await ctx.bot.send_invoice(
        chat_id=q.from_user.id,
        title=title, description=desc,
        payload=f"sub:{plan}",
        provider_token="", currency="XTR",
        prices=[LabeledPrice(title, price)],
    )

async def my_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub = get_subscription(user_id)
    if sub and datetime.fromisoformat(str(sub["sub_end"])) > datetime.now():
        end = datetime.fromisoformat(str(sub["sub_end"])).strftime("%d.%m.%Y %H:%M")
        plan_label = "Разовый взнос + ежемесячно" if sub["plan"] == "entry" else "Ежемесячная"
        await update.message.reply_text(
            f"✅ Подписка активна\n\nТариф: {plan_label}\nДо: {end}\n\n"
            f"Бот рассылки: @ТВОЙ_БОТ_РАССЫЛКИ"
        )
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Купить доступ", callback_data="sub:choose")]])
        await update.message.reply_text("❌ Подписка не активна.", reply_markup=kb)

async def pre_checkout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    payload = update.message.successful_payment.invoice_payload
    user    = update.effective_user
    stars   = update.message.successful_payment.total_amount

    if payload.startswith("sub:"):
        plan    = payload.split(":")[1]
        new_end = activate_subscription(user.id, user.username, plan, days=30)
        end_str = new_end.strftime("%d.%m.%Y")
        log_sale(user.id, 0, stars)
        renewal = "Продление — 25⭐/мес" if plan == "entry" else "Продление — 200⭐/мес"
        await update.message.reply_text(
            f"✅ Доступ открыт до *{end_str}*\n\n"
            f"🤖 Бот рассылки: @ТВОЙ_БОТ_РАССЫЛКИ\n\n"
            f"{renewal}\n/status — проверить подписку",
            parse_mode="Markdown"
        )
        await ctx.bot.send_message(
            ADMIN_ID,
            f"💰 Новая подписка!\n"
            f"Пользователь: @{user.username or user.id}\n"
            f"Тариф: {'Взнос+мес' if plan == 'entry' else 'Ежемесячная'}\n"
            f"Stars: {stars} | До: {end_str}"
        )
        return

    if payload.startswith("product:"):
        pid = int(payload.split(":")[1])
        p   = get_product(pid)
        if not p:
            await update.message.reply_text("❌ Ошибка. Напиши в поддержку.")
            return
        log_sale(user.id, pid, stars)
        await update.message.reply_text("✅ Оплата принята! Спасибо 🎉")
        if p["content"]:
            text = p["content"]
            for i in range(0, len(text), 4000):
                await update.message.reply_text(text[i:i+4000])
        if p["file_id"]:
            await update.message.reply_document(document=p["file_id"], caption="📎 Файл к товару")

async def home_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")],
        [InlineKeyboardButton("📞 Поддержка", url="https://t.me/m16el1n0")],
    ])
    await q.edit_message_text("👋 Главная:", reply_markup=kb)

# ── ADMIN ─────────────────────────────────────────────────────────────────────

async def admin_entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return ConversationHandler.END
    await update.message.reply_text("🔧 *Админ-панель*", reply_markup=admin_main_kb(), parse_mode="Markdown")
    return A_MENU

async def adm_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    total, stars, today, top, subs = get_stats()
    text = f"📊 *Статистика*\n\nПродаж: {total}\nСегодня: {today}\nStars: {stars}⭐\nАктивных подписок: {subs}\n\n"
    if top:
        text += "*Топ:*\n"
        for i, row in enumerate(top, 1):
            text += f"{i}. {row['name']} — {row['cnt']} прод.\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="adm:menu")]])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    return A_MENU

async def adm_subs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    subs = get_all_subscribers()
    if not subs:
        text = "👥 Активных подписчиков нет."
    else:
        text = f"👥 *Подписчики ({len(subs)}):*\n\n"
        for s in subs:
            end  = datetime.fromisoformat(str(s["sub_end"])).strftime("%d.%m.%Y")
            name = f"@{s['username']}" if s["username"] else str(s["user_id"])
            plan = "Взнос+мес" if s["plan"] == "entry" else "Ежемес."
            text += f"• {name} — {plan} — до {end}\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="adm:menu")]])
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    return A_MENU

async def adm_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    products = get_products(active_only=False)
    if not products:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="adm:menu")]])
        await q.edit_message_text("Товаров нет.", reply_markup=kb)
        return A_MENU
    kb = []
    for p in products:
        status = "✅" if p["active"] else "❌"
        kb.append([InlineKeyboardButton(f"{status} {p['name']} · {p['price_stars']}⭐", callback_data=f"adm:edit:{p['id']}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="adm:menu")])
    await q.edit_message_text("📋 *Товары:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    return A_MENU

async def adm_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🔧 *Админ-панель*", reply_markup=admin_main_kb(), parse_mode="Markdown")
    return A_MENU

async def adm_close(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Закрыто. /admin чтобы открыть.")
    return ConversationHandler.END

async def adm_add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["new_product"] = {}
    await q.edit_message_text("➕ *Шаг 1/4*\n\nВведи название:", parse_mode="Markdown")
    return A_ADD_NAME

async def adm_add_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_product"]["name"] = update.message.text.strip()
    await update.message.reply_text("📝 *Шаг 2/4*\n\nВведи описание (видит покупатель до оплаты):", parse_mode="Markdown")
    return A_ADD_DESC

async def adm_add_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_product"]["description"] = update.message.text.strip()
    await update.message.reply_text("💰 *Шаг 3/4*\n\nВведи цену в Stars:", parse_mode="Markdown")
    return A_ADD_PRICE

async def adm_add_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        assert price >= 1
    except:
        await update.message.reply_text("❌ Только целое число ≥ 1:")
        return A_ADD_PRICE
    ctx.user_data["new_product"]["price_stars"] = price
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Пропустить", callback_data="adm:skip_content")]])
    await update.message.reply_text(
        "📄 *Шаг 4/4*\n\nНапиши текст который покупатель получит после оплаты.\nИли пропусти:",
        parse_mode="Markdown", reply_markup=kb
    )
    return A_ADD_CONTENT

async def adm_add_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["new_product"]["content"] = update.message.text.strip()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Без файла", callback_data="adm:skip_file")]])
    await update.message.reply_text("✅ Текст сохранён! Прикрепи файл или пропусти:", reply_markup=kb)
    return A_ADD_FILE

async def adm_skip_content(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["new_product"]["content"] = None
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Без файла", callback_data="adm:skip_file")]])
    await q.edit_message_text("Отправь файл или пропусти:", reply_markup=kb)
    return A_ADD_FILE

async def adm_add_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    np  = ctx.user_data["new_product"]
    pid = add_product(np["name"], np["description"], np["price_stars"], np.get("content"), doc.file_id, doc.file_name)
    await update.message.reply_text(f"✅ Товар *#{pid}* добавлен! /admin", parse_mode="Markdown")
    return ConversationHandler.END

async def adm_skip_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q  = update.callback_query
    await q.answer()
    np = ctx.user_data["new_product"]
    pid = add_product(np["name"], np["description"], np["price_stars"], np.get("content"))
    await q.edit_message_text(f"✅ Товар *#{pid}* добавлен! /admin", parse_mode="Markdown")
    return ConversationHandler.END

async def adm_edit_item(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[2])
    p   = get_product(pid)
    ctx.user_data["edit_pid"] = pid
    has_file = f"`{p['file_name']}`" if p["file_name"] else "нет"
    has_text = f"{str(p['content'])[:40]}..." if p["content"] else "нет"
    status   = "✅ активен" if p["active"] else "❌ скрыт"
    toggle   = "🙈 Скрыть" if p["active"] else "👁 Показать"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Название",           callback_data="adm:ef:name")],
        [InlineKeyboardButton("📄 Описание",           callback_data="adm:ef:description")],
        [InlineKeyboardButton("💰 Цена",               callback_data="adm:ef:price_stars")],
        [InlineKeyboardButton("📃 Текст после оплаты", callback_data="adm:ef:content")],
        [InlineKeyboardButton("📎 Файл",               callback_data="adm:ef:file")],
        [InlineKeyboardButton(toggle,                  callback_data=f"adm:toggle:{pid}")],
        [InlineKeyboardButton("🗑 Удалить",            callback_data=f"adm:delete:{pid}")],
        [InlineKeyboardButton("◀️ Назад",              callback_data="adm:list")],
    ])
    await q.edit_message_text(
        f"✏️ *{p['name']}*\n\nЦена: {p['price_stars']}⭐\nТекст: {has_text}\nФайл: {has_file}\nСтатус: {status}",
        parse_mode="Markdown", reply_markup=kb
    )
    return A_EDIT_FIELD

async def adm_edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q     = update.callback_query
    await q.answer()
    field = q.data.split(":")[2]
    ctx.user_data["edit_field"] = field
    if field == "file":
        await q.edit_message_text("Отправь новый файл:")
        return A_EDIT_VALUE
    labels = {"name":"название","description":"описание","price_stars":"цену в Stars","content":"текст после оплаты"}
    await q.edit_message_text(f"Введи {labels.get(field, field)}:")
    return A_EDIT_VALUE

async def adm_edit_value_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    field = ctx.user_data.get("edit_field")
    pid   = ctx.user_data.get("edit_pid")
    value = update.message.text.strip()
    if field == "price_stars":
        try:
            value = int(value)
            assert value >= 1
        except:
            await update.message.reply_text("❌ Только число ≥ 1:")
            return A_EDIT_VALUE
    update_product(pid, field, value)
    await update.message.reply_text("✅ Обновлено! /admin")
    return ConversationHandler.END

async def adm_edit_value_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pid = ctx.user_data.get("edit_pid")
    doc = update.message.document
    update_product(pid, "file_id",   doc.file_id)
    update_product(pid, "file_name", doc.file_name)
    await update.message.reply_text("✅ Файл обновлён! /admin")
    return ConversationHandler.END

async def adm_toggle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[2])
    p   = get_product(pid)
    new_status = 0 if p["active"] else 1
    update_product(pid, "active", new_status)
    await q.edit_message_text(f"✅ {'Показан' if new_status else 'Скрыт'}. /admin")
    return ConversationHandler.END

async def adm_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    await q.answer()
    pid = int(q.data.split(":")[2])
    delete_product(pid)
    await q.edit_message_text("🗑 Удалён. /admin")
    return ConversationHandler.END

async def adm_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено. /admin")
    return ConversationHandler.END

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    db.db_init()

    app = Application.builder().token(BOT_TOKEN).build()

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_entry)],
        states={
            A_MENU: [
                CallbackQueryHandler(adm_add_start, pattern="^adm:add$"),
                CallbackQueryHandler(adm_stats,     pattern="^adm:stats$"),
                CallbackQueryHandler(adm_subs,      pattern="^adm:subs$"),
                CallbackQueryHandler(adm_list,      pattern="^adm:list$"),
                CallbackQueryHandler(adm_menu,      pattern="^adm:menu$"),
                CallbackQueryHandler(adm_close,     pattern="^adm:close$"),
                CallbackQueryHandler(adm_edit_item, pattern="^adm:edit:\\d+$"),
                CallbackQueryHandler(adm_toggle,    pattern="^adm:toggle:\\d+$"),
                CallbackQueryHandler(adm_delete,    pattern="^adm:delete:\\d+$"),
            ],
            A_ADD_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_name)],
            A_ADD_DESC:    [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_desc)],
            A_ADD_PRICE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_price)],
            A_ADD_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_add_content),
                CallbackQueryHandler(adm_skip_content, pattern="^adm:skip_content$"),
            ],
            A_ADD_FILE: [
                MessageHandler(filters.Document.ALL, adm_add_file),
                CallbackQueryHandler(adm_skip_file,  pattern="^adm:skip_file$"),
            ],
            A_EDIT_FIELD: [
                CallbackQueryHandler(adm_edit_field, pattern="^adm:ef:"),
                CallbackQueryHandler(adm_toggle,     pattern="^adm:toggle:\\d+$"),
                CallbackQueryHandler(adm_delete,     pattern="^adm:delete:\\d+$"),
                CallbackQueryHandler(adm_list,       pattern="^adm:list$"),
            ],
            A_EDIT_VALUE: [
                MessageHandler(filters.Document.ALL,            adm_edit_value_file),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_edit_value_text),
            ],
        },
        fallbacks=[
            CommandHandler("admin",  admin_entry),
            CommandHandler("cancel", adm_cancel),
        ],
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(admin_conv)
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("status", my_status))
    app.add_handler(CallbackQueryHandler(show_catalog, pattern="^catalog$"))
    app.add_handler(CallbackQueryHandler(show_item,    pattern="^item:\\d+$"))
    app.add_handler(CallbackQueryHandler(buy_item,     pattern="^buy:\\d+$"))
    app.add_handler(CallbackQueryHandler(sub_choose,   pattern="^sub:choose$"))
    app.add_handler(CallbackQueryHandler(sub_buy,      pattern="^sub:buy:"))
    app.add_handler(CallbackQueryHandler(home_cb,      pattern="^home$"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    logger.info("🚀 Shop Bot запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
