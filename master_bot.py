import asyncio
import json
import logging
import random

from telegram import Bot, ReactionTypeEmoji, Update
from telegram.error import TelegramError
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

    Emoji assignment per post:
      emoji[0] -> workers 1,2,3,4  (x4 reactions)
      emoji[1] -> workers 5,6      (x2 reactions)
      emoji[2] -> worker 7 + master bot (x2 reactions)

    All 8 reactions are spread over 2-3 minutes with random delays.
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

    async def _dispatch_reactions(self, chat_id, message_id: int):
        """
        Fixed emoji assignments:
          emoji[0] -> workers 0,1,2,3  (x4)
          emoji[1] -> workers 4,5      (x2)
          emoji[2] -> worker 6 + master bot (x2)
        All fire at random delays between 5 and 180 seconds.
        """
        reactions = self.config["reactions"]
        if len(reactions) < 3:
            logger.warning("Need at least 3 reactions configured -- skipping.")
            return

        emoji1, emoji2, emoji3 = reactions[0], reactions[1], reactions[2]

        worker_emoji = [
            emoji1, emoji1, emoji1, emoji1,
            emoji2, emoji2,
            emoji3,
        ]

        delays = []
        t = 300  # first reaction after 5 minutes
        for _ in range(8):
            delays.append(t)
            t += random.uniform(180, 240)  # each next reaction 3–4 minutes later

        tasks = [
            worker.react(
                chat_id=chat_id,
                message_id=message_id,
                reaction_pool=[worker_emoji[i]],
                delay=delays[i],
            )
            for i, worker in enumerate(self.workers)
        ]

        tasks.append(
            self._master_react(chat_id, message_id, emoji3, delay=delays[7])
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
            "8 total reactions per post:\n"
            "Emoji 1 x4 | Emoji 2 x2 | Emoji 3 x2\n"
            "All spread over 2-3 minutes randomly.\n\n"
            "Commands:\n"
            "/setreactions emoji1 emoji2 emoji3\n"
            "/listreactions\n"
            "/status"
        )

    async def cmd_set_reactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        if not context.args or len(context.args) < 3:
            await update.message.reply_text(
                "Send exactly 3 emojis:\n/setreactions emoji1 emoji2 emoji3\n\n"
                "Emoji 1 = x4 | Emoji 2 = x2 | Emoji 3 = x2"
            )
            return

        self.config["reactions"] = list(context.args)
        self._save_config()

        e1, e2, e3 = self.config["reactions"][0], self.config["reactions"][1], self.config["reactions"][2]
        await update.message.reply_text(
            f"Updated!\n\n{e1} x4\n{e2} x2\n{e3} x2"
        )

    async def cmd_list_reactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        reactions = self.config["reactions"]
        if len(reactions) < 3:
            await update.message.reply_text("Need at least 3 reactions. Use /setreactions.")
            return

        e1, e2, e3 = reactions[0], reactions[1], reactions[2]
        await update.message.reply_text(
            f"Current setup:\n\n{e1} x4 (workers 1-4)\n{e2} x2 (workers 5-6)\n{e3} x2 (worker 7 + master)\n\nAll random within 2-3 minutes."
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

        logger.info("Master bot is running and listening for channel posts...")
        app.run_polling(allowed_updates=["message", "channel_post"])
