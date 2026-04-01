import asyncio
import json
import logging
import random

from telegram import Bot, ReactionTypeEmoji, Update
from telegram.error import TelegramError, Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from worker_bot import WorkerBot

logger = logging.getLogger(__name__)


class MasterBot:
    """
    The master bot controls all 7 worker bots.

    Reactions per post = exactly 8 slots (7 workers + 1 master).
    Emoji distribution is fully customizable via /setreactions.
    All 8 reactions are spread over ~25 minutes with random delays.
    """

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.workers: list[WorkerBot] = self._init_workers()

    def _load_config(self) -> dict:
        import os
        with open(self.config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        if os.getenv("MASTER_TOKEN"):
            config["master_token"] = os.getenv("MASTER_TOKEN")
            config["worker_tokens"] = [
                os.getenv(f"WORKER_{i}") for i in range(1, 8)
            ]
            config["channel_id"] = os.getenv("CHANNEL_ID", config["channel_id"])
            config["owner_id"] = int(os.getenv("OWNER_ID", config["owner_id"]))
        return config

    def _save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def _init_workers(self) -> list[WorkerBot]:
        return [
            WorkerBot(token=token, worker_id=i + 1)
            for i, token in enumerate(self.config["worker_tokens"])
        ]

    def _is_owner(self, user_id: int) -> bool:
        return user_id == self.config["owner_id"]

    def _is_target_channel(self, chat) -> bool:
        cfg = str(self.config["channel_id"])
        return str(chat.id) == cfg or (
            hasattr(chat, "username")
            and chat.username
            and f"@{chat.username}" == cfg
        )

    def _slots_summary(self, slots: list) -> str:
        summary = {}
        for e in slots:
            summary[e] = summary.get(e, 0) + 1
        return "\n".join(f"{e} x{c}" for e, c in summary.items())

    async def _dispatch_reactions(self, chat_id, message_id: int):
        """
        Reads 8 emoji slots from config and assigns one per worker + master.
        Delays are staggered randomly, starting at 5 minutes, each next
        reaction 3-4 minutes later.
        """
        slots = self.config.get("reactions", [])
        if len(slots) != 8:
            logger.warning("Need exactly 8 reaction slots configured -- skipping.")
            return

        delays = []
        t = 300  # first reaction after 5 minutes
        for _ in range(8):
            delays.append(t)
            t += random.uniform(180, 240)

        tasks = [
            worker.react(
                chat_id=chat_id,
                message_id=message_id,
                reaction_pool=[slots[i]],
                delay=delays[i],
            )
            for i, worker in enumerate(self.workers)
        ]

        tasks.append(
            self._master_react(chat_id, message_id, slots[7], delay=delays[7])
        )

        await asyncio.gather(*tasks)

    async def _master_react(self, chat_id, message_id: int, emoji: str, delay: float):
        await asyncio.sleep(delay)
        try:
            bot = Bot(token=self.config["master_token"])
            await bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
            logger.info(f"[Master] Reacted with {emoji} to message {message_id}")
        except TelegramError as e:
            logger.error(f"[Master] Failed to react: {e}")

    async def handle_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        post = update.channel_post
        if post and self._is_target_channel(post.chat):
            logger.info(f"New post detected (id={post.message_id}). Dispatching workers...")
            asyncio.create_task(
                self._dispatch_reactions(post.chat.id, post.message_id)
            )

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return
        await update.message.reply_text(
            "Reaction Master Bot\n\n"
            "8 total reactions per post, spread over ~25 minutes.\n\n"
            "Commands:\n"
            "/setreactions emoji count [emoji count ...]\n"
            "  e.g. /setreactions ❤️ 4 😭 2 🙏 2\n"
            "  e.g. /setreactions ❤️ 8\n"
            "  e.g. /setreactions ❤️ 5 😭 2 🔥 1\n"
            "  Total must always equal 8.\n\n"
            "/listreactions\n"
            "/status"
        )

    async def cmd_set_reactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        args = context.args or []
        if len(args) < 2 or len(args) % 2 != 0:
            await update.message.reply_text(
                "Usage: /setreactions emoji count [emoji count ...]\n\n"
                "Examples:\n"
                "  /setreactions ❤️ 4 😭 2 🙏 2\n"
                "  /setreactions ❤️ 8\n"
                "  /setreactions ❤️ 5 😭 2 🔥 1\n\n"
                "Total reactions must equal 8."
            )
            return

        slots = []
        try:
            for i in range(0, len(args), 2):
                emoji = args[i]
                count = int(args[i + 1])
                if count < 1:
                    raise ValueError("Count must be at least 1.")
                slots.extend([emoji] * count)
        except (ValueError, IndexError):
            await update.message.reply_text(
                "Each emoji must be followed by a positive whole number.\n"
                "Example: /setreactions ❤️ 4 😭 2 🙏 2"
            )
            return

        if len(slots) != 8:
            await update.message.reply_text(
                f"Total must be exactly 8 reactions (got {len(slots)}).\n"
                "Example: /setreactions ❤️ 4 😭 2 🙏 2"
            )
            return

        self.config["reactions"] = slots
        self._save_config()

        await update.message.reply_text(
            f"Updated!\n\n{self._slots_summary(slots)}"
        )

    async def cmd_list_reactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        slots = self.config.get("reactions", [])
        if len(slots) != 8:
            await update.message.reply_text(
                "Reactions not configured yet. Use /setreactions."
            )
            return

        await update.message.reply_text(
            f"Current setup (8 total):\n\n{self._slots_summary(slots)}"
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        await update.message.reply_text("Checking all worker bots...")
        statuses = await asyncio.gather(*[w.get_status() for w in self.workers])

        lines = []
        for s in statuses:
            icon = "OK" if s["active"] else "FAIL"
            name = f"@{s['username']}" if s["active"] else f"Error: {s.get('error', 'Unknown')}"
            lines.append(f"[{icon}] Worker {s['worker_id']}: {name}")

        await update.message.reply_text("\n".join(lines))

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        if isinstance(context.error, Conflict):
            logger.critical(
                "Conflict error: another bot instance is already running. "
                "Shut down duplicate instances on Railway."
            )
        else:
            logger.error(f"Unhandled error: {context.error}", exc_info=context.error)

    def run(self):
        app = (
            Application.builder()
            .token(self.config["master_token"])
            .build()
        )

        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("setreactions", self.cmd_set_reactions))
        app.add_handler(CommandHandler("listreactions", self.cmd_list_reactions))
        app.add_handler(CommandHandler("status", self.cmd_status))

        app.add_handler(
            MessageHandler(filters.UpdateType.CHANNEL_POSTS, self.handle_channel_post)
        )

        app.add_error_handler(self.error_handler)

        logger.info("Master bot is running and listening for channel posts...")
        app.run_polling(
            allowed_updates=["message", "channel_post"],
            drop_pending_updates=True,
        )
