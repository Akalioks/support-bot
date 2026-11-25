"""Every fixed text the bot sends. AI answers come from Gemini."""
from html import escape

BTN_HUMAN = "👤 Talk to a human"


def welcome(name: str, business: str, demo: bool) -> str:
    text = (f"👋 Hi, {escape(name)}! I'm the assistant of <b>{escape(business)}</b>.\n\n"
            "Ask me anything about delivery, payment, returns or our products — I reply instantly, "
            "in English, Russian or Estonian. If you need a person, tap <b>👤 Talk to a human</b>.")
    if demo:
        text += ("\n\n🧪 <i>Demo bot for a fictional home-goods store. Try: “Do you deliver to Tartu?”, "
                 "“Как вернуть товар?”, “Kas saab osamaksetega maksta?”. Send /admin to see the owner's panel.</i>")
    return text


RESET_DONE = "🧹 Done — I've forgotten our previous conversation."
HANDOFF_OFFER = "👤 Connect me with a manager"
NON_TEXT = "I can read text messages only. Please type your question 🙂"
USER_LIMIT = "You've sent a lot of messages in the last hour. Please try again a bit later, or ask for a manager."
DAILY_LIMIT = "The assistant is resting for today. Please ask for a manager — they'll help you."
NO_MANAGERS = "Sorry, no managers are available in this demo. Please continue with me 🙂"


def handoff_client(hours: str) -> str:
    return ("👤 <b>I've called a manager.</b> They'll reply right here in this chat "
            f"(working hours: {escape(hours)}). You can keep writing — everything goes to them.")


HANDOFF_ALREADY = "👤 A manager already has your request — just keep writing here."
TICKET_CLOSED_CLIENT = "✅ The manager has finished the conversation. I'm back — ask me anything!"


def manager_new_ticket(ticket_id: int, name: str, username: str | None, transcript: str) -> str:
    uname = f" @{escape(username)}" if username else ""
    return (f"🆘 <b>Request #{ticket_id}</b> from {escape(name)}{uname}\n\n"
            f"<b>Recent conversation:</b>\n{transcript}\n\n"
            "↩️ <i>Reply to this message (swipe left) to answer the client.</i>")


def manager_client_message(name: str, text: str) -> str:
    return f"💬 <b>{escape(name)}:</b>\n{escape(text)}"
