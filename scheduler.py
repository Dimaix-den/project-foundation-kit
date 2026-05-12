"""
Планировщик автопубликации.
Каждые 5 минут читает Google Sheets, публикует посты
со статусом 'На публикацию' у которых время пришло.
"""
import logging
from telegram import Bot
from telegram.constants import ParseMode
import config
from storage.sheets import get_posts_to_publish, mark_published

logger = logging.getLogger(__name__)


async def check_and_publish(bot: Bot):
    """Проверяет и публикует готовые посты. Вызывается планировщиком."""
    if not config.PUBLISH_CHANNEL:
        return

    posts = get_posts_to_publish()
    if not posts:
        return

    logger.info(f"[Scheduler] Найдено {len(posts)} постов к публикации")

    channel = config.PUBLISH_CHANNEL
    try:
        channel = int(channel)
    except (ValueError, TypeError):
        pass

    for post in posts:
        text = post.get("text", "").strip()
        if not text:
            logger.warning(f"[Scheduler] Пост #{post['id']} без текста, пропускаю")
            continue
        try:
            await bot.send_message(
                chat_id=channel,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
            mark_published(post["_row"])
            logger.info(f"[Scheduler] Пост #{post['id']} опубликован")
        except Exception as e:
            logger.error(f"[Scheduler] Ошибка публикации поста #{post['id']}: {e}")
