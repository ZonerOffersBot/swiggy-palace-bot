from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import db
from utils import is_admin

router = Router()
class ThemeFSM(StatesGroup):
    waiting_image = State()
    waiting_category_image = State()

THEMES = {"user_menu_image":"User Main Menu","admin_menu_image":"Admin Menu","shop_menu_image":"Shop Banner"}

@router.callback_query(F.data == "admin:theme_home")
async def theme_home(cb: CallbackQuery):
    if not await is_admin(cb.from_user.id):
        await cb.answer("Admin only.", show_alert=True); return
    kb=InlineKeyboardBuilder()
    for key,label in THEMES.items():
        current=await db().fetchval("SELECT value FROM bot_settings WHERE key=$1",key)
        kb.button(text=("🖼 " if current else "➕ ")+label,callback_data="theme:set:"+key)
    cats=await db().fetch("SELECT id,label,image_file_id FROM inventory_categories ORDER BY position,id")
    for row in cats:
        kb.button(text=("🖼 " if row["image_file_id"] else "➕ ")+"Product: "+row["label"][:22],callback_data="theme:category:"+str(row["id"]))
    kb.button(text="⬅️ Admin Home",callback_data="admin:home"); kb.adjust(1)
    await cb.answer()
    await cb.message.answer("🎨 <b>Theme Manager</b>\nAlag-alag screens aur product categories ke liye photo upload karein. Telegram button colors platform-controlled hain.",reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("theme:set:"))
async def theme_set(cb: CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    key=cb.data.split(":",2)[2]
    if key not in THEMES: await cb.answer("Invalid screen.",show_alert=True); return
    await state.set_state(ThemeFSM.waiting_image); await state.update_data(theme_key=key)
    await cb.answer(); await cb.message.answer("Image/photo bhejein. Cancel: /cancel")

@router.message(ThemeFSM.waiting_image)
async def theme_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if msg.text and msg.text.strip()=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    if not msg.photo: await msg.answer("Telegram photo bhejein."); return
    key=(await state.get_data())["theme_key"]
    await db().execute("INSERT INTO bot_settings(key,value,updated_at) VALUES($1,$2,NOW()) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()",key,msg.photo[-1].file_id)
    await state.clear(); await msg.answer("✅ Theme image save ho gayi.")

@router.callback_query(F.data.startswith("theme:category:"))
async def category_image_start(cb:CallbackQuery,state:FSMContext):
    if not await is_admin(cb.from_user.id): await cb.answer("Admin only.",show_alert=True); return
    try: cid=int(cb.data.rsplit(":",1)[1])
    except ValueError: await cb.answer("Invalid category.",show_alert=True); return
    if not await db().fetchval("SELECT EXISTS(SELECT 1 FROM inventory_categories WHERE id=$1)",cid): await cb.answer("Category nahi mili.",show_alert=True); return
    await state.set_state(ThemeFSM.waiting_category_image); await state.update_data(category_id=cid)
    await cb.answer(); await cb.message.answer("Product/category card image bhejein. Cancel: /cancel")

@router.message(ThemeFSM.waiting_category_image)
async def category_image_save(msg:Message,state:FSMContext):
    if not await is_admin(msg.from_user.id): await state.clear(); return
    if msg.text and msg.text.strip()=="/cancel": await state.clear(); await msg.answer("Cancelled."); return
    if not msg.photo: await msg.answer("Photo bhejein."); return
    cid=(await state.get_data())["category_id"]
    await db().execute("UPDATE inventory_categories SET image_file_id=$1 WHERE id=$2",msg.photo[-1].file_id,cid)
    await state.clear(); await msg.answer("✅ Product/category image save ho gayi.")
