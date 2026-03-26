import asyncio
import json
import logging
import random

from telegram import Update
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
    - Listens for every new channel post
    - Dispatches all 7 workers to react with staggered delays
    - Exposes commands for the owner to manage the reaction pool
    """

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.workers: list[WorkerBot] = self._init_workers()

    # ── Config helpers ─────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        with open(self.config_path, "r", encoding="utf-8") as f:
            return json.load(f)

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
        """Check if the post came from the configured channel."""
        cfg = str(self.config["channel_id"])
        return str(chat.id) == cfg or (
            hasattr(chat, "username")
            and chat.username
            and f"@{chat.username}" == cfg
        )

    # ── Core dispatch ──────────────────────────────────────────────────────────

    async def _dispatch_reactions(self, chat_id, message_id: int):
        """
        Fire all 7 workers concurrently with random staggered delays
        so reactions appear naturally over a few seconds.
        """
        reactions = self.config["reactions"]
        if not reactions:
            logger.warning("Reaction pool is empty — skipping.")
            return

        tasks = [
            worker.react(
                chat_id=chat_id,
                message_id=message_id,
                reaction_pool=reactions,
                delay=i * random.uniform(1.0, 3.0),   # 1–3 s apart per worker
            )
            for i, worker in enumerate(self.workers)
        ]
        await asyncio.gather(*tasks)

    # ── Channel post handler ───────────────────────────────────────────────────

    async def handle_channel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        post = update.channel_post
        if post and self._is_target_channel(post.chat):
            logger.info(f"New post detected (id={post.message_id}). Dispatching workers…")
            # Run in background so the handler returns immediately
            asyncio.create_task(
                self._dispatch_reactions(post.chat.id, post.message_id)
            )

    # ── Commands ───────────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return
        await update.message.reply_text(
            "👋 *Reaction Master Bot*\n\n"
            "I control 7 worker bots that react to every new post in your channel.\n\n"
            "*Commands:*\n"
            "`/setreactions 👍 🔥 ❤️` — Set the reaction pool\n"
            "`/listreactions` — View current pool\n"
            "`/status` — Check all 7 worker bots\n",
            parse_mode="Markdown",
        )

    async def cmd_set_reactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        if not context.args:
            await update.message.reply_text(
                "Usage: `/setreactions 👍 🔥 ❤️ 😂`\n"
                "Send the emojis separated by spaces.",
                parse_mode="Markdown",
            )
            return

        self.config["reactions"] = list(context.args)
        self._save_config()

        pool = " ".join(self.config["reactions"])
        await update.message.reply_text(
            f"✅ Reaction pool updated ({len(self.config['reactions'])} emojis):\n{pool}"
        )

    async def cmd_list_reactions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        reactions = self.config["reactions"]
        if not reactions:
            await update.message.reply_text("⚠️ Reaction pool is empty. Use /setreactions to add some.")
            return

        pool = " ".join(reactions)
        await update.message.reply_text(
            f"*Current reaction pool* ({len(reactions)} emojis):\n{pool}",
            parse_mode="Markdown",
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_owner(update.effective_user.id):
            return

        await update.message.reply_text("🔍 Checking all worker bots…")
        statuses = await asyncio.gather(*[w.get_status() for w in self.workers])

        lines = []
        for s in statuses:
            icon = "✅" if s["active"] else "❌"
            name = f"@{s['username']}" if s["active"] else f"Error: {s.get('error', 'Unknown')}"
            lines.append(f"{icon} Worker {s['worker_id']}: {name}")

        await update.message.reply_text("\n".join(lines))

    # ── Entry point ────────────────────────────────────────────────────────────

    def run(self):
        app = (
            Application.builder()
            .token(self.config["master_token"])
            .build()
        )

        # Owner commands
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("setreactions", self.cmd_set_reactions))
        app.add_handler(CommandHandler("listreactions", self.cmd_list_reactions))
        app.add_handler(CommandHandler("status", self.cmd_status))

        # Channel post listener
        app.add_handler(
            MessageHandler(filters.UpdateType.CHANNEL_POSTS, self.handle_channel_post)
        )

        logger.info("Master bot is running and listening for channel posts…")
        app.run_polling(allowed_updates=["message", "channel_post"])
