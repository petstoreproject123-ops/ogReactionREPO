import asyncio
import random
import logging
from telegram import Bot, ReactionTypeEmoji
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


class WorkerBot:
    """
    Represents one of the 7 worker bots.
    Each worker holds its own Bot instance and reacts
    to a given message with a random emoji from the pool.
    """

    def __init__(self, token: str, worker_id: int):
        self.token = token
        self.worker_id = worker_id
        self.bot = Bot(token=token)

    async def react(self, chat_id, message_id: int, reaction_pool: list[str], delay: float = 0.0):
        """
        Wait `delay` seconds, then apply one random reaction to the message.
        Each worker independently picks from the reaction pool.
        """
        await asyncio.sleep(delay)

        chosen = random.choice(reaction_pool)

        try:
            await self.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=chosen)],
            )
            logger.info(
                f"[Worker {self.worker_id}] Reacted with {chosen} "
                f"to message {message_id} in {chat_id}"
            )
        except TelegramError as e:
            logger.error(f"[Worker {self.worker_id}] Failed to react: {e}")

    async def get_status(self) -> dict:
        """Return a status dict — used by the /status command."""
        try:
            me = await self.bot.get_me()
            return {
                "worker_id": self.worker_id,
                "username": me.username,
                "active": True,
            }
        except TelegramError as e:
            return {
                "worker_id": self.worker_id,
                "username": "Unknown",
                "active": False,
                "error": str(e),
            }
