import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputMediaPhoto,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BOT_TOKEN = "BOT_TOKEN"
ADMIN_IDS = [5078387190]
PAYMENT_PHONE = "+7 904 244 1770"
STAR_PRICE = 1.47
MIN_STARS = 50
MAX_STARS = 100000

STAR_OPTIONS = [50, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500, 5000, 10000, 25000]

PREMIUM_PLANS = {
    "3m":  {"months": 3,  "price": 1230, "label": "3 месяца"},
    "6m":  {"months": 6,  "price": 1859, "label": "6 месяцев"},
    "12m": {"months": 12, "price": 3329, "label": "12 месяцев"},
}

START_PHOTO_URL = "https://i.ibb.co/zWbKBYyf/image.png"
PHOTO_ORDERS    = "https://i.ibb.co/xSPCFp2f/image.png"
PHOTO_STARS     = "https://i.ibb.co/kghWKtLr/image.png"
PHOTO_PREMIUM   = "https://i.ibb.co/4whMc7qb/image.png"
PHOTO_PROFILE   = "https://i.ibb.co/Ngk3Nx4t/image.png"

logging.basicConfig(level=logging.INFO)

DIV = "━━━━━━━━━━━━━━━━━━━━"


def fmt_price_value(price: float) -> str:
    s = f"{price:,.2f}".replace(",", " ").replace(".", ",")
    s = s.rstrip("0").rstrip(",")
    return f"{s} ₽"


def fmt_price(stars: int) -> str:
    return fmt_price_value(stars * STAR_PRICE)


def fmt_num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def no_username_warning() -> str:
    return (
        "⚠️⚠️⚠️ <b>ВНИМАНИЕ</b> ⚠️⚠️⚠️\n"
        f"{DIV}\n"
        "🔴 <b><u>У ВАС НЕ УСТАНОВЛЕН USERNAME!</u></b> 🔴\n"
        f"{DIV}\n\n"
        "❌ <b>БЕЗ USERNAME ПОКУПКА НЕВОЗМОЖНА!</b>\n\n"
        "Для покупки у вас <b>ОБЯЗАТЕЛЬНО</b> должен быть\n"
        "установлен <b>@username</b> в настройках Telegram.\n\n"
        f"{DIV}\n"
        "📱 <b>КАК УСТАНОВИТЬ USERNAME:</b>\n\n"
        "1️⃣ Откройте <b>Настройки</b> Telegram\n"
        "2️⃣ Нажмите на свой <b>номер телефона</b>\n"
        "3️⃣ Выберите <b>«Имя пользователя»</b>\n"
        "4️⃣ Придумайте и установите <b>@username</b>\n"
        "5️⃣ Вернитесь в бота и нажмите /start\n"
        f"{DIV}\n"
        "🔴 <b><u>БЕЗ USERNAME ПОКУПКА НЕВОЗМОЖНА!</u></b> 🔴"
    )


def check_username(user) -> bool:
    return bool(user.username)


orders: dict[int, "Order"] = {}
order_counter = 0
maintenance_mode = False

users_by_username: dict[str, int] = {}
users_by_id: dict[int, str] = {}


def register_user(user_id: int, username: Optional[str]) -> None:
    users_by_id[user_id] = username or ""
    if username:
        users_by_username[username.lower().lstrip("@")] = user_id


def find_user_id(username: str) -> Optional[int]:
    clean_username = username.lstrip("@").lower()
    return users_by_username.get(clean_username)


@dataclass
class Order:
    order_id: int
    user_id: int
    username: str
    recipient_username: str
    recipient_id: Optional[int]
    is_gift: bool
    product_type: str
    stars_count: int = 0
    premium_plan: str = ""
    total_price: float = 0.0
    screenshot_file_id: Optional[str] = None
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%d.%m.%Y %H:%M"))

    @property
    def product_label(self) -> str:
        if self.product_type == "premium":
            plan = PREMIUM_PLANS.get(self.premium_plan, {})
            return f"💎 Telegram Premium — {plan.get('label', '?')}"
        return f"⭐ {fmt_num(self.stars_count)} звёзд"


def create_order(user_id: int, username: str, recipient_username: str,
                 recipient_id: Optional[int], is_gift: bool, product_type: str,
                 stars_count: int = 0, premium_plan: str = "", total_price: float = 0.0) -> Order:
    global order_counter
    order_counter += 1
    order = Order(
        order_id=order_counter,
        user_id=user_id,
        username=username,
        recipient_username=recipient_username,
        recipient_id=recipient_id,
        is_gift=is_gift,
        product_type=product_type,
        stars_count=stars_count,
        premium_plan=premium_plan,
        total_price=round(total_price, 2),
    )
    orders[order_counter] = order
    return order


def get_pending_orders():
    return [o for o in orders.values() if o.status == "pending"]


def accept_order(order_id: int) -> bool:
    if order_id in orders and orders[order_id].status == "pending":
        orders[order_id].status = "accepted"
        del orders[order_id]
        return True
    return False


def reject_order(order_id: int) -> bool:
    if order_id in orders and orders[order_id].status == "pending":
        orders[order_id].status = "rejected"
        del orders[order_id]
        return True
    return False


def clear_all_orders() -> int:
    count = len(orders)
    orders.clear()
    return count


def get_order(order_id: int) -> Optional[Order]:
    return orders.get(order_id)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


class OrderStates(StatesGroup):
    choosing_stars = State()
    choosing_premium = State()
    waiting_for_recipient = State()
    waiting_for_custom_amount = State()
    waiting_for_screenshot = State()


# ───────────────────── БЕЗОПАСНОЕ РЕДАКТИРОВАНИЕ ─────────────────────

async def safe_edit(
    message: Message,
    text: str,
    reply_markup=None,
    photo: Optional[str] = None,
) -> None:
    """Безопасно редактирует сообщение: текст ↔ фото, без падений."""
    has_photo = bool(message.photo)
    try:
        if photo:
            if has_photo:
                await message.edit_media(
                    media=InputMediaPhoto(media=photo, caption=text),
                    reply_markup=reply_markup,
                )
            else:
                await message.delete()
                await message.answer_photo(photo, caption=text, reply_markup=reply_markup)
        else:
            if has_photo:
                await message.delete()
                await message.answer(text, reply_markup=reply_markup)
            else:
                await message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        if photo:
            await message.answer_photo(photo, caption=text, reply_markup=reply_markup)
        else:
            await message.answer(text, reply_markup=reply_markup)


# ───────────────────── КЛАВИАТУРЫ ─────────────────────

def user_reply_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="⭐ Купить звёзды")
    kb.button(text="💎 Купить Premium")
    kb.button(text="📋 Мои заявки")
    kb.button(text="👤 Профиль")
    kb.button(text="ℹ️ Помощь")
    kb.adjust(2, 2, 1)
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="Выберите действие 👇")


def admin_reply_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="📋 Активные заявки")
    kb.button(text="🔧 Тех. работы")
    kb.button(text="🗑 Очистить всё")
    kb.button(text="📊 Статус")
    kb.button(text="🛠 Админ-панель")
    kb.button(text="👤 Режим пользователя")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup(resize_keyboard=True, input_field_placeholder="Админ-панель 👇")


def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ Купить звёзды", callback_data="buy_stars")
    kb.button(text="💎 Купить Premium", callback_data="buy_premium")
    kb.button(text="📋 Мои заявки", callback_data="my_orders")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="ℹ️ Помощь", callback_data="help")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def buy_type_kb(product: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="⭐ Купить себе", callback_data=f"{product}_self")
    kb.button(text="🎁 Подарить другу", callback_data=f"{product}_gift")
    kb.button(text="⬅️ Назад", callback_data="main_menu")
    kb.adjust(2, 1)
    return kb.as_markup()


def stars_grid_kb():
    kb = InlineKeyboardBuilder()
    for amount in STAR_OPTIONS:
        kb.button(
            text=f"{fmt_num(amount)} ⭐ · {fmt_price(amount)}",
            callback_data=f"stars:{amount}",
        )
    kb.button(text="⚙️ Своё количество", callback_data="stars:custom")
    kb.button(text="⬅️ Назад", callback_data="buy_stars")
    kb.adjust(2)
    return kb.as_markup()


def premium_grid_kb():
    kb = InlineKeyboardBuilder()
    for key, plan in PREMIUM_PLANS.items():
        kb.button(
            text=f"💎 {plan['label']} · {fmt_price_value(plan['price'])}",
            callback_data=f"premium:{key}",
        )
    kb.button(text="⬅️ Назад", callback_data="buy_premium")
    kb.adjust(1)
    return kb.as_markup()


def back_to_main_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 В главное меню", callback_data="main_menu")
    return kb.as_markup()


def admin_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Активные заявки", callback_data="admin_list_orders")
    kb.button(text="🔧 Тех. работы: вкл/выкл", callback_data="admin_toggle_maintenance")
    kb.button(text="🗑 Отменить все заявки", callback_data="admin_clear_all")
    kb.button(text="📊 Статус бота", callback_data="admin_status")
    kb.adjust(1)
    return kb.as_markup()


def order_actions_kb(order_id: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"admin_accept:{order_id}")
    kb.button(text="❌ Отклонить", callback_data=f"admin_reject:{order_id}")
    kb.adjust(2)
    return kb.as_markup()


def back_to_admin_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад в админ-панель", callback_data="admin_back")
    return kb.as_markup()


user_router = Router()
admin_router = Router()


# ───────────────────── ПОЛЬЗОВАТЕЛЬ ─────────────────────

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user.id, message.from_user.username)

    if is_admin(message.from_user.id):
        await message.answer(
            f"🛠 <b>С возвращением, администратор!</b>\n{DIV}\n"
            f"Используйте панель ниже 👇 или команду /ahelp",
            reply_markup=admin_reply_kb(),
        )
        return

    if maintenance_mode:
        await message.answer(
            f"🔧 <b>Технические работы</b>\n{DIV}\n"
            f"Бот временно недоступен.\n"
            f"Пожалуйста, попробуйте позже 🙏",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await message.answer_photo(
        photo=START_PHOTO_URL,
        caption=(
            f"✨ <b>Добро пожаловать в Miller Stars!</b>\n"
            f"{DIV}\n"
            f"🌟 Покупайте звёзды и Telegram Premium\n"
            f"быстро и безопасно.\n\n"
            f"💎 <b>Курс звёзд:</b> {STAR_PRICE} ₽ за 1 звезду\n"
            f"📦 <b>Минимум:</b> {MIN_STARS} звёзд\n"
            f"📱 <b>Оплата:</b> по номеру телефона\n"
            f"{DIV}\n"
            f"Выберите действие в меню ниже 👇"
        ),
        reply_markup=user_reply_kb(),
    )


@user_router.message(F.text == "⭐ Купить звёзды")
async def rb_buy_stars(message: Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user.id, message.from_user.username)
    if maintenance_mode and not is_admin(message.from_user.id):
        await message.answer("🔧 Бот на тех. обслуживании. Попробуйте позже.")
        return

    if not check_username(message.from_user):
        await message.answer(no_username_warning(), reply_markup=user_reply_kb())
        return

    await message.answer_photo(
        photo=PHOTO_STARS,
        caption=(
            f"⭐ <b>Покупка звёзд</b>\n{DIV}\n"
            f"Выберите, кому хотите купить звёзды 👇"
        ),
        reply_markup=buy_type_kb("stars"),
    )


@user_router.message(F.text == "💎 Купить Premium")
async def rb_buy_premium(message: Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user.id, message.from_user.username)
    if maintenance_mode and not is_admin(message.from_user.id):
        await message.answer("🔧 Бот на тех. обслуживании. Попробуйте позже.")
        return

    if not check_username(message.from_user):
        await message.answer(no_username_warning(), reply_markup=user_reply_kb())
        return

    await message.answer_photo(
        photo=PHOTO_PREMIUM,
        caption=(
            f"💎 <b>Покупка Telegram Premium</b>\n{DIV}\n"
            f"Выберите, кому хотите купить Premium 👇"
        ),
        reply_markup=buy_type_kb("premium"),
    )


@user_router.message(F.text == "📋 Мои заявки")
async def rb_my_orders(message: Message):
    register_user(message.from_user.id, message.from_user.username)
    user_orders = [o for o in orders.values() if o.user_id == message.from_user.id]

    if not user_orders:
        await message.answer_photo(
            photo=PHOTO_ORDERS,
            caption=(
                f"📋 <b>Мои заявки</b>\n{DIV}\n"
                f"У вас пока нет активных заявок 🗂"
            ),
        )
        return

    text = f"📋 <b>Мои заявки</b>\n{DIV}\n\n"
    for o in user_orders:
        gift = f"\n   🎁 Подарок: @{o.recipient_username}" if o.is_gift else ""
        text += (
            f"🆔 <b>Заявка №{o.order_id}</b>\n"
            f"   {o.product_label} · {fmt_price_value(o.total_price)}{gift}\n"
            f"   🕐 {o.created_at}\n\n"
        )

    await message.answer_photo(photo=PHOTO_ORDERS, caption=text)


@user_router.message(F.text == "👤 Профиль")
async def rb_profile(message: Message):
    register_user(message.from_user.id, message.from_user.username)
    user = message.from_user
    user_orders = [o for o in orders.values() if o.user_id == user.id]
    total_stars = sum(o.stars_count for o in user_orders)
    total_spent = sum(o.total_price for o in user_orders)

    await message.answer_photo(
        photo=PHOTO_PROFILE,
        caption=(
            f"👤 <b>Профиль</b>\n{DIV}\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"📛 Имя: {user.full_name}\n"
            f"🔗 Юзернейм: @{user.username or '—'}\n"
            f"{DIV}\n"
            f"📦 Активных заявок: <b>{len(user_orders)}</b>\n"
            f"⭐ Всего звёзд: <b>{fmt_num(total_stars)}</b>\n"
            f"💰 На сумму: <b>{fmt_price_value(total_spent)}</b>"
        ),
    )


@user_router.message(F.text == "ℹ️ Помощь")
async def rb_help(message: Message):
    register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"ℹ️ <b>Помощь</b>\n{DIV}\n"
        f"<b>Как купить:</b>\n"
        f"1️⃣ Нажмите «⭐ Купить звёзды» или «💎 Купить Premium»\n"
        f"2️⃣ Выберите «Купить себе» или «Подарить»\n"
        f"3️⃣ Укажите количество/план\n"
        f"4️⃣ Переведите сумму на номер:\n"
        f"    <code>{PAYMENT_PHONE}</code>\n"
        f"5️⃣ Отправьте скриншот перевода боту\n"
        f"6️⃣ Ожидайте зачисления ⏳\n"
        f"{DIV}\n"
        f"💎 <b>Звёзды:</b> {STAR_PRICE} ₽ за 1 шт\n"
        f"💎 <b>Premium 3 мес:</b> {fmt_price_value(1230)}\n"
        f"💎 <b>Premium 6 мес:</b> {fmt_price_value(1859)}\n"
        f"💎 <b>Premium 12 мес:</b> {fmt_price_value(3329)}\n"
        f"{DIV}\n"
        f"❓ По вопросам — обратитесь к администратору."
    )


@user_router.callback_query(F.data == "main_menu")
async def main_menu(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    await state.clear()
    await safe_edit(
        call.message,
        f"🏠 <b>Главное меню</b>\n{DIV}\n"
        f"⭐ Звёзды: <b>{STAR_PRICE} ₽</b> за 1 шт\n"
        f"💎 Premium: <b>от 1 230 ₽</b>\n"
        f"📱 Оплата: <code>{PAYMENT_PHONE}</code>",
        reply_markup=main_menu_kb(),
    )
    await call.answer()


@user_router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery):
    register_user(call.from_user.id, call.from_user.username)
    user = call.from_user
    user_orders = [o for o in orders.values() if o.user_id == user.id]
    total_stars = sum(o.stars_count for o in user_orders)
    total_spent = sum(o.total_price for o in user_orders)

    await safe_edit(
        call.message,
        f"👤 <b>Профиль</b>\n{DIV}\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"📛 Имя: {user.full_name}\n"
        f"🔗 Юзернейм: @{user.username or '—'}\n"
        f"{DIV}\n"
        f"📦 Активных заявок: <b>{len(user_orders)}</b>\n"
        f"⭐ Всего звёзд: <b>{fmt_num(total_stars)}</b>\n"
        f"💰 На сумму: <b>{fmt_price_value(total_spent)}</b>",
        reply_markup=back_to_main_kb(),
        photo=PHOTO_PROFILE,
    )
    await call.answer()


@user_router.callback_query(F.data == "help")
async def cb_help(call: CallbackQuery):
    register_user(call.from_user.id, call.from_user.username)
    await safe_edit(
        call.message,
        f"ℹ️ <b>Помощь</b>\n{DIV}\n"
        f"<b>Как купить:</b>\n"
        f"1️⃣ Нажмите «⭐ Купить звёзды» или «💎 Купить Premium»\n"
        f"2️⃣ Выберите «Купить себе» или «Подарить»\n"
        f"3️⃣ Укажите количество/план\n"
        f"4️⃣ Переведите сумму на номер:\n"
        f"    <code>{PAYMENT_PHONE}</code>\n"
        f"5️⃣ Отправьте скриншот перевода боту\n"
        f"6️⃣ Ожидайте зачисления ⏳\n"
        f"{DIV}\n"
        f"💎 <b>Звёзды:</b> {STAR_PRICE} ₽ за 1 шт\n"
        f"💎 <b>Premium 3 мес:</b> {fmt_price_value(1230)}\n"
        f"💎 <b>Premium 6 мес:</b> {fmt_price_value(1859)}\n"
        f"💎 <b>Premium 12 мес:</b> {fmt_price_value(3329)}\n"
        f"{DIV}\n"
        f"❓ По вопросам — обратитесь к администратору.",
        reply_markup=back_to_main_kb(),
    )
    await call.answer()


@user_router.callback_query(F.data == "buy_stars")
async def buy_stars(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    await state.clear()
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    if not check_username(call.from_user):
        await safe_edit(call.message, no_username_warning(), reply_markup=back_to_main_kb())
        await call.answer("❗ Установите @username!", show_alert=True)
        return

    await safe_edit(
        call.message,
        f"⭐ <b>Покупка звёзд</b>\n{DIV}\n"
        f"Выберите, кому хотите купить звёзды 👇",
        reply_markup=buy_type_kb("stars"),
        photo=PHOTO_STARS,
    )
    await call.answer()


@user_router.callback_query(F.data == "buy_premium")
async def buy_premium(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    await state.clear()
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    if not check_username(call.from_user):
        await safe_edit(call.message, no_username_warning(), reply_markup=back_to_main_kb())
        await call.answer("❗ Установите @username!", show_alert=True)
        return

    await safe_edit(
        call.message,
        f"💎 <b>Покупка Telegram Premium</b>\n{DIV}\n"
        f"Выберите, кому хотите купить Premium 👇",
        reply_markup=buy_type_kb("premium"),
        photo=PHOTO_PREMIUM,
    )
    await call.answer()


def grid_text_stars(recipient_display: str) -> str:
    return (
        f"⭐ <b>Покупка звёзд</b>\n"
        f"{DIV}\n"
        f"👤 Получатель: <b>{recipient_display}</b>\n"
        f"{DIV}\n"
        f"📉 Минимум: {MIN_STARS} звёзд\n"
        f"📈 Максимум: {fmt_num(MAX_STARS)} звёзд\n"
        f"💎 Курс: {STAR_PRICE} ₽ / звезда\n"
        f"{DIV}\n"
        f"🔍 Выберите количество звёзд 👇"
    )


def grid_text_premium(recipient_display: str) -> str:
    return (
        f"💎 <b>Покупка Telegram Premium</b>\n"
        f"{DIV}\n"
        f"👤 Получатель: <b>{recipient_display}</b>\n"
        f"{DIV}\n"
        f"📦 Доступные планы:\n"
        f"   💎 3 месяца — {fmt_price_value(1230)}\n"
        f"   💎 6 месяцев — {fmt_price_value(1859)}\n"
        f"   💎 12 месяцев — {fmt_price_value(3329)}\n"
        f"{DIV}\n"
        f"🔍 Выберите план 👇"
    )


async def _start_product_flow(call: CallbackQuery, state: FSMContext, product: str):
    user = call.from_user
    display = f"@{user.username}" if user.username else user.full_name

    await state.set_state(
        OrderStates.choosing_stars if product == "stars" else OrderStates.choosing_premium
    )
    await state.update_data(
        product_type=product,
        recipient_username=user.username or "",
        recipient_id=user.id,
        is_gift=False,
        recipient_display=display,
    )

    text = grid_text_stars(display) if product == "stars" else grid_text_premium(display)
    markup = stars_grid_kb() if product == "stars" else premium_grid_kb()

    await safe_edit(call.message, text, reply_markup=markup)
    await call.answer()


@user_router.callback_query(F.data == "stars_self")
async def stars_self(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    if not check_username(call.from_user):
        await safe_edit(call.message, no_username_warning(), reply_markup=back_to_main_kb())
        await call.answer("❗ Установите @username!", show_alert=True)
        return

    await _start_product_flow(call, state, "stars")


@user_router.callback_query(F.data == "premium_self")
async def premium_self(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    if not check_username(call.from_user):
        await safe_edit(call.message, no_username_warning(), reply_markup=back_to_main_kb())
        await call.answer("❗ Установите @username!", show_alert=True)
        return

    await _start_product_flow(call, state, "premium")


@user_router.callback_query(F.data == "stars_gift")
async def stars_gift(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    if not check_username(call.from_user):
        await safe_edit(call.message, no_username_warning(), reply_markup=back_to_main_kb())
        await call.answer("❗ Установите @username!", show_alert=True)
        return

    await state.update_data(product_type="stars")
    await state.set_state(OrderStates.waiting_for_recipient)
    await safe_edit(
        call.message,
        f"🎁 <b>Подарить звёзды</b>\n{DIV}\n"
        f"🔎 Введите юзернейм пользователя,\n"
        f"которому будем дарить звёзды:\n\n"
        f"📌 <i>Пример:</i> <code>@username</code>\n"
        f"{DIV}\n"
        f"⚠️ Пользователь должен был запустить бота."
    )
    await call.answer()


@user_router.callback_query(F.data == "premium_gift")
async def premium_gift(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    if not check_username(call.from_user):
        await safe_edit(call.message, no_username_warning(), reply_markup=back_to_main_kb())
        await call.answer("❗ Установите @username!", show_alert=True)
        return

    await state.update_data(product_type="premium")
    await state.set_state(OrderStates.waiting_for_recipient)
    await safe_edit(
        call.message,
        f"🎁 <b>Подарить Premium</b>\n{DIV}\n"
        f"🔎 Введите юзернейм пользователя,\n"
        f"которому будем дарить Premium:\n\n"
        f"📌 <i>Пример:</i> <code>@username</code>\n"
        f"{DIV}\n"
        f"⚠️ Пользователь должен был запустить бота."
    )
    await call.answer()


@user_router.message(OrderStates.waiting_for_recipient)
async def process_recipient(message: Message, state: FSMContext):
    register_user(message.from_user.id, message.from_user.username)
    if maintenance_mode and not is_admin(message.from_user.id):
        await message.answer("🔧 Бот на тех. обслуживании. Попробуйте позже.")
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("❌ Введите @username пользователя.")
        return

    username = text if text.startswith("@") else "@" + text
    username_clean = username.lstrip("@")

    if len(username_clean) < 3:
        await message.answer(
            f"❌ <b>Неверный формат юзернейма</b>\n"
            f"Введите, например: <code>@username</code>"
        )
        return

    recipient_id = find_user_id(username_clean)

    if recipient_id is None:
        await message.answer(
            f"❌ <b>Пользователь не найден</b>\n{DIV}\n"
            f"Пользователь <b>{username}</b> не найден в базе бота.\n\n"
            f"💡 Попросите его запустить бота командой /start\n"
            f"и попробуйте снова."
        )
        return

    if recipient_id == message.from_user.id:
        await message.answer(
            f"❌ <b>Нельзя подарить самому себе</b>\n"
            f"Используйте кнопку «Купить себе»."
        )
        return

    data = await state.get_data()
    product = data.get("product_type", "stars")

    await state.update_data(
        recipient_username=username_clean,
        recipient_id=recipient_id,
        is_gift=True,
        recipient_display=username,
    )

    if product == "stars":
        await state.set_state(OrderStates.choosing_stars)
        await message.answer(grid_text_stars(username), reply_markup=stars_grid_kb())
    else:
        await state.set_state(OrderStates.choosing_premium)
        await message.answer(grid_text_premium(username), reply_markup=premium_grid_kb())


def payment_text(stars_count: int = 0, premium_plan: str = "", recipient_display: str = "",
                 is_gift: bool = False, total_price: float = 0.0) -> str:
    gift_line = f"\n🎁 Подарок для: <b>{recipient_display}</b>" if is_gift else ""
    if premium_plan:
        plan = PREMIUM_PLANS[premium_plan]
        product_line = f"💎 Telegram Premium — <b>{plan['label']}</b>"
    else:
        product_line = f"⭐ Количество: <b>{fmt_num(stars_count)}</b> звёзд"

    return (
        f"🧾 <b>Заявка на покупку</b>{gift_line}\n"
        f"{DIV}\n"
        f"{product_line}\n"
        f"💰 К оплате: <b>{fmt_price_value(total_price)}</b>\n"
        f"{DIV}\n"
        f"📱 <b>Реквизиты для перевода:</b>\n"
        f"<code>{PAYMENT_PHONE}</code>\n"
        f"{DIV}\n"
        f"<b>Инструкция:</b>\n"
        f"1️⃣ Переведите точную сумму по номеру выше\n"
        f"2️⃣ Сделайте скриншот перевода\n"
        f"3️⃣ Отправьте скриншот сюда в чат 📸\n"
        f"{DIV}\n"
        f"⚠️ <i>Без скриншота заявка не будет создана.</i>"
    )


@user_router.callback_query(F.data.startswith("stars:"))
async def select_stars(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    data = await state.get_data()
    if not data or "recipient_display" not in data:
        await call.answer("⚠️ Сессия истекла. Начните заново.", show_alert=True)
        await safe_edit(
            call.message,
            f"⚠️ <b>Сессия истекла</b>\n{DIV}\n"
            f"Пожалуйста, начните заново.",
            reply_markup=back_to_main_kb(),
        )
        return

    value = call.data.split(":", 1)[1]

    if value == "custom":
        await state.set_state(OrderStates.waiting_for_custom_amount)
        await safe_edit(
            call.message,
            f"⚙️ <b>Своё количество</b>\n{DIV}\n"
            f"Введите количество звёзд:\n"
            f"от <b>{MIN_STARS}</b> до <b>{fmt_num(MAX_STARS)}</b>",
        )
        await call.answer()
        return

    stars_count = int(value)
    total = round(stars_count * STAR_PRICE, 2)

    await state.update_data(stars_count=stars_count, total_price=total)
    await state.set_state(OrderStates.waiting_for_screenshot)

    await safe_edit(
        call.message,
        payment_text(
            stars_count=stars_count,
            recipient_display=data.get("recipient_display", "—"),
            is_gift=data.get("is_gift", False),
            total_price=total,
        ),
    )
    await call.answer()


@user_router.callback_query(F.data.startswith("premium:"))
async def select_premium(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user.id, call.from_user.username)
    if maintenance_mode and not is_admin(call.from_user.id):
        await call.answer("🔧 Бот на тех. обслуживании", show_alert=True)
        return

    data = await state.get_data()
    if not data or "recipient_display" not in data:
        await call.answer("⚠️ Сессия истекла. Начните заново.", show_alert=True)
        await safe_edit(
            call.message,
            f"⚠️ <b>Сессия истекла</b>\n{DIV}\n"
            f"Пожалуйста, начните заново.",
            reply_markup=back_to_main_kb(),
        )
        return

    plan_key = call.data.split(":", 1)[1]
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        await call.answer("❌ Неизвестный план", show_alert=True)
        return

    total = float(plan["price"])

    await state.update_data(premium_plan=plan_key, total_price=total)
    await state.set_state(OrderStates.waiting_for_screenshot)

    await safe_edit(
        call.message,
        payment_text(
            premium_plan=plan_key,
            recipient_display=data.get("recipient_display", "—"),
            is_gift=data.get("is_gift", False),
            total_price=total,
        ),
    )
    await call.answer()


@user_router.message(OrderStates.waiting_for_custom_amount)
async def process_custom_amount(message: Message, state: FSMContext):
    register_user(message.from_user.id, message.from_user.username)
    if maintenance_mode and not is_admin(message.from_user.id):
        await message.answer("🔧 Бот на тех. обслуживании. Попробуйте позже.")
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("❌ Пожалуйста, введите целое число.")
        return

    stars_count = int(text)
    if stars_count < MIN_STARS or stars_count > MAX_STARS:
        await message.answer(
            f"❌ Введите число от {MIN_STARS} до {fmt_num(MAX_STARS)}."
        )
        return

    data = await state.get_data()
    total = round(stars_count * STAR_PRICE, 2)

    await state.update_data(stars_count=stars_count, total_price=total)
    await state.set_state(OrderStates.waiting_for_screenshot)

    await message.answer(
        payment_text(
            stars_count=stars_count,
            recipient_display=data.get("recipient_display", "—"),
            is_gift=data.get("is_gift", False),
            total_price=total,
        ),
    )


@user_router.message(OrderStates.waiting_for_screenshot, F.photo)
async def process_screenshot(message: Message, state: FSMContext, bot: Bot):
    register_user(message.from_user.id, message.from_user.username)
    data = await state.get_data()
    product_type = data.get("product_type", "stars")
    stars_count = data.get("stars_count", 0)
    premium_plan = data.get("premium_plan", "")
    total_price = data.get("total_price", 0.0)
    recipient_username = data.get("recipient_username") or ""
    recipient_id = data.get("recipient_id")
    recipient_display = data.get("recipient_display", "—")
    is_gift = data.get("is_gift", False)

    if not total_price:
        await message.answer("⚠️ Сессия истекла. Введите /start.")
        await state.clear()
        return

    screenshot_file_id = message.photo[-1].file_id

    order = create_order(
        user_id=message.from_user.id,
        username=message.from_user.username or message.from_user.full_name,
        recipient_username=recipient_username,
        recipient_id=recipient_id,
        is_gift=is_gift,
        product_type=product_type,
        stars_count=stars_count,
        premium_plan=premium_plan,
        total_price=total_price,
    )
    order.screenshot_file_id = screenshot_file_id

    gift_line = f"\n🎁 Подарок для: <b>{recipient_display}</b>" if is_gift else ""

    await message.answer(
        f"✅ <b>Заявка №{order.order_id} создана!</b>{gift_line}\n"
        f"{DIV}\n"
        f"{order.product_label}\n"
        f"💰 Сумма: <b>{fmt_price_value(order.total_price)}</b>\n"
        f"{DIV}\n"
        f"⏳ <i>Ожидайте выполнения.\n"
        f"Администратор проверит вашу заявку\n"
        f"в ближайшее время.</i>",
    )

    gift_admin = f"\n🎁 Подарок для: {recipient_display}" if is_gift else ""

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id,
                photo=screenshot_file_id,
                caption=(
                    f"🆕 <b>Новая заявка №{order.order_id}</b>\n"
                    f"{DIV}\n"
                    f"📦 Товар: {order.product_label}\n"
                    f"👤 Покупатель: @{order.username}\n"
                    f"🆔 ID: <code>{order.user_id}</code>{gift_admin}\n"
                    f"💰 Сумма: <b>{fmt_price_value(order.total_price)}</b>\n"
                    f"🕐 Время: {order.created_at}\n"
                    f"{DIV}\n"
                    f"✅ <code>/accept {order.order_id}</code>\n"
                    f"❌ <code>/reject {order.order_id}</code>"
                ),
            )
        except Exception:
            pass

    await state.clear()


@user_router.message(OrderStates.waiting_for_screenshot)
async def wrong_screenshot(message: Message):
    register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"❌ <b>Нужен скриншот</b>\n{DIV}\n"
        f"Пожалуйста, отправьте <b>фото</b> перевода.\n"
        f"Если вы передумали — введите /start."
    )


@user_router.callback_query(F.data == "my_orders")
async def my_orders(call: CallbackQuery):
    register_user(call.from_user.id, call.from_user.username)
    user_orders = [o for o in orders.values() if o.user_id == call.from_user.id]

    if not user_orders:
        await safe_edit(
            call.message,
            f"📋 <b>Мои заявки</b>\n{DIV}\n"
            f"У вас пока нет активных заявок 🗂",
            reply_markup=back_to_main_kb(),
            photo=PHOTO_ORDERS,
        )
        await call.answer()
        return

    text = f"📋 <b>Мои заявки</b>\n{DIV}\n\n"
    for o in user_orders:
        gift = f"\n   🎁 Подарок: @{o.recipient_username}" if o.is_gift else ""
        text += (
            f"🆔 <b>Заявка №{o.order_id}</b>\n"
            f"   {o.product_label} · {fmt_price_value(o.total_price)}{gift}\n"
            f"   🕐 {o.created_at}\n\n"
        )

    await safe_edit(call.message, text, reply_markup=back_to_main_kb(), photo=PHOTO_ORDERS)
    await call.answer()


# ───────────────────── АДМИН ─────────────────────

AHELP_TEXT = (
    f"🛠 <b>Админ-панель Miller Stars</b>\n"
    f"{DIV}\n"
    f"📋 <b>Основные:</b>\n"
    f"/ahelp — справка (это сообщение)\n"
    f"/apanel — инлайн-панель с кнопками\n"
    f"/aorders — список активных заявок\n"
    f"/status — статус бота\n"
    f"{DIV}\n"
    f"🔧 <b>Тех. работы:</b>\n"
    f"/maintenance — вкл/выкл тех. работы\n"
    f"{DIV}\n"
    f"✅ <b>Обработка заявок:</b>\n"
    f"/accept &lt;id&gt; — принять (напр. <code>/accept 5</code>)\n"
    f"/reject &lt;id&gt; — отклонить (напр. <code>/reject 5</code>)\n"
    f"{DIV}\n"
    f"🗑 <b>Массовые:</b>\n"
    f"/clearall — отменить ВСЕ заявки\n"
    f"{DIV}\n"
    f"👤 /user — режим пользователя\n"
    f"🛠 /admin — вернуться в админ-режим\n"
    f"{DIV}\n"
    f"💡 <i>Удобные кнопки — на клавиатуре внизу 👇</i>"
)


@admin_router.message(Command("ahelp"))
async def ahelp_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    await message.answer(AHELP_TEXT, reply_markup=admin_reply_kb())


@admin_router.message(Command("apanel"))
@admin_router.message(F.text == "🛠 Админ-панель")
async def apanel_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    status = "🔧 ВКЛ" if maintenance_mode else "✅ ВЫКЛ"
    await message.answer(
        f"🛠 <b>Админ-панель Miller Stars</b>\n"
        f"{DIV}\n"
        f"🔧 Тех. работы: <b>{status}</b>\n"
        f"📋 Активных заявок: <b>{len(get_pending_orders())}</b>\n"
        f"💎 Курс звёзд: <b>{STAR_PRICE} ₽</b> / шт\n"
        f"📱 Реквизиты: <code>{PAYMENT_PHONE}</code>\n"
        f"{DIV}\n"
        f"💡 Все команды: /ahelp",
        reply_markup=admin_menu_kb(),
    )


@admin_router.message(Command("user"))
@admin_router.message(F.text == "👤 Режим пользователя")
async def user_mode(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    await message.answer(
        f"👤 <b>Режим пользователя</b>\n{DIV}\n"
        f"Вы переключились в пользовательский режим.\n"
        f"Для возврата в админ — /admin",
        reply_markup=user_reply_kb(),
    )


@admin_router.message(Command("admin"))
@admin_router.message(F.text == "🛠 Вернуться в админ")
async def admin_mode(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    await message.answer(
        f"🛠 <b>Админ-режим включён</b>\n{DIV}\n"
        f"Используйте кнопки ниже 👇",
        reply_markup=admin_reply_kb(),
    )


@admin_router.message(Command("aorders"))
@admin_router.message(F.text == "📋 Активные заявки")
async def aorders_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    pending = get_pending_orders()
    if not pending:
        await message.answer(
            f"📋 <b>Активные заявки</b>\n{DIV}\n"
            f"Список пуст 🗂",
            reply_markup=admin_menu_kb(),
        )
        return

    text = f"📋 <b>Активные заявки ({len(pending)})</b>\n{DIV}\n\n"
    for o in pending:
        gift = f"\n   🎁 → @{o.recipient_username}" if o.is_gift else ""
        text += (
            f"🆔 <b>№{o.order_id}</b>\n"
            f"   📦 {o.product_label}\n"
            f"   💰 {fmt_price_value(o.total_price)}\n"
            f"   👤 @{o.username} (<code>{o.user_id}</code>){gift}\n"
            f"   🕐 {o.created_at}\n"
            f"   ✅ <code>/accept {o.order_id}</code>\n"
            f"   ❌ <code>/reject {o.order_id}</code>\n\n"
        )
    await message.answer(text, reply_markup=admin_menu_kb())


@admin_router.message(Command("maintenance"))
@admin_router.message(F.text == "🔧 Тех. работы")
async def maintenance_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    global maintenance_mode
    maintenance_mode = not maintenance_mode
    status = "🔧 ВКЛ" if maintenance_mode else "✅ ВЫКЛ"

    await message.answer(
        f"🔧 <b>Режим тех. работ: {status}</b>\n{DIV}\n"
        + (
            "🚫 Пользователи временно не могут\nоформлять новые заказы."
            if maintenance_mode
            else "✅ Бот снова принимает заказы."
        ),
        reply_markup=admin_menu_kb(),
    )


@admin_router.message(Command("status"))
@admin_router.message(F.text == "📊 Статус")
async def status_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    status = "🔧 ВКЛ" if maintenance_mode else "✅ ВЫКЛ"
    await message.answer(
        f"📊 <b>Статус бота</b>\n{DIV}\n"
        f"🔧 Тех. работы: <b>{status}</b>\n"
        f"📋 Активных заявок: <b>{len(get_pending_orders())}</b>\n"
        f"💎 Курс звёзд: <b>{STAR_PRICE} ₽</b> / шт\n"
        f"📱 Реквизиты: <code>{PAYMENT_PHONE}</code>\n"
        f"👥 Пользователей в базе: <b>{len(users_by_id)}</b>",
        reply_markup=admin_menu_kb(),
    )


@admin_router.message(Command("accept"))
async def accept_cmd(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            f"❌ <b>Использование:</b> <code>/accept &lt;id&gt;</code>\n"
            f"Например: <code>/accept 5</code>"
        )
        return

    order_id = int(parts[1])
    order = get_order(order_id)
    if not order:
        await message.answer(f"❌ Заявка №{order_id} не найдена или уже обработана.")
        return

    buyer_id = order.user_id
    recipient_id = order.recipient_id
    is_gift = order.is_gift
    label = order.product_label
    accept_order(order_id)

    try:
        await bot.send_message(
            buyer_id,
            f"🎉 <b>Заявка №{order_id} принята!</b>\n{DIV}\n"
            f"{label}\n"
            f"⏳ Будет выполнено в ближайшее время.\n"
            f"{DIV}\n"
            f"💛 Спасибо за покупку!",
        )
    except Exception:
        pass

    if is_gift and recipient_id and recipient_id != buyer_id:
        try:
            await bot.send_message(
                recipient_id,
                f"🎁 <b>Вам сделали подарок!</b>\n{DIV}\n"
                f"{label}\n"
                f"⏳ Будет зачислено в ближайшее время.",
            )
        except Exception:
            pass

    await message.answer(
        f"✅ <b>Заявка №{order_id} принята</b>\n"
        f"и удалена из списка.",
        reply_markup=admin_menu_kb(),
    )


@admin_router.message(Command("reject"))
async def reject_cmd(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            f"❌ <b>Использование:</b> <code>/reject &lt;id&gt;</code>\n"
            f"Например: <code>/reject 5</code>"
        )
        return

    order_id = int(parts[1])
    order = get_order(order_id)
    if not order:
        await message.answer(f"❌ Заявка №{order_id} не найдена или уже обработана.")
        return

    buyer_id = order.user_id
    reject_order(order_id)

    try:
        await bot.send_message(
            buyer_id,
            f"❌ <b>Заявка №{order_id} отклонена.</b>\n{DIV}\n"
            f"Если вы считаете это ошибкой —\n"
            f"свяжитесь с администратором.",
        )
    except Exception:
        pass

    await message.answer(
        f"❌ <b>Заявка №{order_id} отклонена</b>\n"
        f"и удалена из списка.",
        reply_markup=admin_menu_kb(),
    )


@admin_router.message(Command("clearall"))
@admin_router.message(F.text == "🗑 Очистить всё")
async def clearall_cmd(message: Message, bot: Bot):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    pending = get_pending_orders()
    if not pending:
        await message.answer(
            f"📋 Нет активных заявок для отмены.",
            reply_markup=admin_menu_kb(),
        )
        return

    count = len(pending)
    for order in pending:
        try:
            await bot.send_message(
                order.user_id,
                f"❌ <b>Заявка №{order.order_id} отменена.</b>\n{DIV}\n"
                f"Если вы считаете это ошибкой —\n"
                f"свяжитесь с администратором.",
            )
        except Exception:
            pass

    clear_all_orders()

    await message.answer(
        f"🗑 <b>Все заявки ({count} шт.)</b>\n"
        f"отменены и удалены.",
        reply_markup=admin_menu_kb(),
    )


@admin_router.callback_query(F.data == "admin_back")
async def admin_back(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    status = "🔧 ВКЛ" if maintenance_mode else "✅ ВЫКЛ"
    await safe_edit(
        call.message,
        f"🛠 <b>Админ-панель Miller Stars</b>\n"
        f"{DIV}\n"
        f"🔧 Тех. работы: <b>{status}</b>\n"
        f"📋 Активных заявок: <b>{len(get_pending_orders())}</b>\n"
        f"{DIV}\n"
        f"💡 Все команды: /ahelp",
        reply_markup=admin_menu_kb(),
    )
    await call.answer()


@admin_router.callback_query(F.data == "admin_status")
async def admin_status_cb(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    status = "🔧 ВКЛ" if maintenance_mode else "✅ ВЫКЛ"
    await safe_edit(
        call.message,
        f"📊 <b>Статус бота</b>\n{DIV}\n"
        f"🔧 Тех. работы: <b>{status}</b>\n"
        f"📋 Активных заявок: <b>{len(get_pending_orders())}</b>\n"
        f"💎 Курс звёзд: <b>{STAR_PRICE} ₽</b> / шт\n"
        f"📱 Реквизиты: <code>{PAYMENT_PHONE}</code>\n"
        f"👥 Пользователей: <b>{len(users_by_id)}</b>",
        reply_markup=back_to_admin_kb(),
    )
    await call.answer()


@admin_router.callback_query(F.data == "admin_list_orders")
async def admin_list_orders(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    pending = get_pending_orders()
    if not pending:
        await safe_edit(
            call.message,
            f"📋 <b>Активные заявки</b>\n{DIV}\n"
            f"Список пуст 🗂",
            reply_markup=back_to_admin_kb(),
        )
        await call.answer()
        return

    await safe_edit(
        call.message,
        f"📋 <b>Активные заявки ({len(pending)})</b>\n{DIV}",
        reply_markup=back_to_admin_kb(),
    )

    for order in pending:
        gift_line = f"\n🎁 Подарок для: @{order.recipient_username}" if order.is_gift else ""
        caption = (
            f"🆔 <b>Заявка №{order.order_id}</b>\n"
            f"{DIV}\n"
            f"📦 Товар: {order.product_label}\n"
            f"👤 Покупатель: @{order.username}\n"
            f"🆔 ID: <code>{order.user_id}</code>{gift_line}\n"
            f"💰 Сумма: <b>{fmt_price_value(order.total_price)}</b>\n"
            f"🕐 Создана: {order.created_at}"
        )

        if order.screenshot_file_id:
            try:
                await bot.send_photo(
                    call.from_user.id,
                    photo=order.screenshot_file_id,
                    caption=caption,
                    reply_markup=order_actions_kb(order.order_id),
                )
            except Exception:
                await bot.send_message(
                    call.from_user.id,
                    caption + "\n\n⚠️ <i>Скриншот недоступен</i>",
                    reply_markup=order_actions_kb(order.order_id),
                )
        else:
            await bot.send_message(
                call.from_user.id,
                caption + "\n\n⚠️ <i>Скриншот отсутствует</i>",
                reply_markup=order_actions_kb(order.order_id),
            )

    await call.answer()


@admin_router.callback_query(F.data.startswith("admin_accept:"))
async def admin_accept(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    order = get_order(order_id)
    if not order:
        await call.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
        return

    buyer_id = order.user_id
    recipient_id = order.recipient_id
    is_gift = order.is_gift
    label = order.product_label
    accept_order(order_id)

    try:
        await bot.send_message(
            buyer_id,
            f"🎉 <b>Заявка №{order_id} принята!</b>\n{DIV}\n"
            f"{label}\n"
            f"⏳ Будет выполнено в ближайшее время.\n"
            f"{DIV}\n"
            f"💛 Спасибо за покупку!",
        )
    except Exception:
        pass

    if is_gift and recipient_id and recipient_id != buyer_id:
        try:
            await bot.send_message(
                recipient_id,
                f"🎁 <b>Вам сделали подарок!</b>\n{DIV}\n"
                f"{label}\n"
                f"⏳ Будет зачислено в ближайшее время.",
            )
        except Exception:
            pass

    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + f"\n{DIV}\n✅ <b>ПРИНЯТА</b>")
    else:
        await call.message.edit_text(text=(call.message.text or "") + f"\n{DIV}\n✅ <b>ПРИНЯТА</b>")
    await call.answer("✅ Заявка принята")


@admin_router.callback_query(F.data.startswith("admin_reject:"))
async def admin_reject(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    order_id = int(call.data.split(":")[1])
    order = get_order(order_id)
    if not order:
        await call.answer("❌ Заявка не найдена или уже обработана", show_alert=True)
        return

    buyer_id = order.user_id
    reject_order(order_id)

    try:
        await bot.send_message(
            buyer_id,
            f"❌ <b>Заявка №{order_id} отклонена.</b>\n{DIV}\n"
            f"Если вы считаете это ошибкой —\n"
            f"свяжитесь с администратором.",
        )
    except Exception:
        pass

    if call.message.caption:
        await call.message.edit_caption(caption=call.message.caption + f"\n{DIV}\n❌ <b>ОТКЛОНЕНА</b>")
    else:
        await call.message.edit_text(text=(call.message.text or "") + f"\n{DIV}\n❌ <b>ОТКЛОНЕНА</b>")
    await call.answer("❌ Заявка отклонена")


@admin_router.callback_query(F.data == "admin_toggle_maintenance")
async def admin_toggle_maintenance(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    global maintenance_mode
    maintenance_mode = not maintenance_mode
    status = "🔧 ВКЛ" if maintenance_mode else "✅ ВЫКЛ"

    await safe_edit(
        call.message,
        f"🛠 <b>Админ-панель Miller Stars</b>\n"
        f"{DIV}\n"
        f"🔧 Тех. работы: <b>{status}</b>\n"
        f"📋 Активных заявок: <b>{len(get_pending_orders())}</b>\n"
        f"{DIV}\n"
        f"💡 Все команды: /ahelp",
        reply_markup=admin_menu_kb(),
    )
    await call.answer(f"Режим тех. работ: {status}")


@admin_router.callback_query(F.data == "admin_clear_all")
async def admin_clear_all(call: CallbackQuery, bot: Bot):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return

    pending = get_pending_orders()
    count = len(pending)

    if count == 0:
        await call.answer("📋 Нет активных заявок для отмены", show_alert=True)
        return

    for order in pending:
        try:
            await bot.send_message(
                order.user_id,
                f"❌ <b>Заявка №{order.order_id} отменена.</b>\n{DIV}\n"
                f"Если вы считаете это ошибкой —\n"
                f"свяжитесь с администратором.",
            )
        except Exception:
            pass

    cleared = clear_all_orders()

    await safe_edit(
        call.message,
        f"🗑 <b>Все заявки ({cleared} шт.)</b>\n"
        f"отменены и удалены.",
        reply_markup=back_to_admin_kb(),
    )
    await call.answer(f"Удалено заявок: {cleared}")


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_router)
    dp.include_router(user_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())