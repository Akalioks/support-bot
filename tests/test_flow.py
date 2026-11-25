"""End-to-end dialogs through a fake Telegram and a fake AI."""
from aiogram.methods import SendMessage

from bot import texts
from bot.ai import UNAVAILABLE, AIResult


async def test_question_goes_to_ai_with_knowledge_and_history(make_env):
    env = await make_env()
    anna = env.person(1, "Anna")
    await anna.say("/start")
    assert "assistant of <b>Nordic Home</b>" in anna.last_text

    await anna.say("Do you deliver to Tartu?")
    assert anna.last_text == "Delivery to Tartu takes 1–2 days."
    assert anna.last.parse_mode is None  # AI text is sent as plain text, never parsed as HTML
    docs, history = env.ai.calls[-1]
    assert any("Tartu" in d.content for d in docs)  # seeded Nordic Home FAQ
    assert history == [{"role": "user", "content": "Do you deliver to Tartu?"}]

    await anna.say("And to Pärnu?")
    _, history = env.ai.calls[-1]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]

    await anna.say("/reset")
    await anna.say("Hi")
    _, history = env.ai.calls[-1]
    assert history == [{"role": "user", "content": "Hi"}]


async def test_full_handoff_cycle(make_env):
    env = await make_env()
    anna, manager = env.person(1, "Anna"), env.person(99, "Manager")

    env.ai.next = AIResult("I don't know your order status, but a manager can check.", True)
    await anna.say("Where is my order 1234?")
    assert texts.HANDOFF_OFFER in anna.buttons()

    await anna.press("Connect me with a manager")
    assert "I've called a manager" in anna.last_text
    note, _ = manager.find("Request #1")
    assert "Where is my order 1234?" in note.text and "Anna" in note.text

    # while the request is open, the client talks to the manager, not the AI
    ai_calls = len(env.ai.calls)
    await anna.say("It was ordered on Monday")
    assert len(env.ai.calls) == ai_calls
    _, relayed_id = manager.find("It was ordered on Monday")

    await manager.say("Your parcel is at the Tartu locker <today>", reply_to=relayed_id)
    assert "Manager:</b> Your parcel is at the Tartu locker &lt;today&gt;" in anna.last_text
    assert manager.last_text == "✓ Delivered"

    await manager.press("Close #1")
    assert texts.TICKET_CLOSED_CLIENT in anna.last_text

    env.ai.next = AIResult("You're welcome!", False)
    await anna.say("Thanks!")
    _, history = env.ai.calls[-1]
    assert any(m["content"].startswith("[Manager] Your parcel") for m in history)  # AI sees what the manager said


async def test_client_can_return_to_bot_and_no_double_tickets(make_env):
    env = await make_env()
    anna, manager = env.person(1, "Anna"), env.person(99, "Manager")
    await anna.say(texts.BTN_HUMAN)
    await anna.say(texts.BTN_HUMAN)
    assert anna.last_text == texts.HANDOFF_ALREADY
    assert len(await env.repo.open_tickets()) == 1
    await anna.say("/bot")
    assert texts.TICKET_CLOSED_CLIENT in anna.last_text
    assert "closed by the client" in manager.last_text
    assert await env.repo.open_tickets() == []


async def test_manager_own_questions_still_reach_ai(make_env):
    env = await make_env()
    manager = env.person(99, "Manager")
    await manager.say("Do you ship to Finland?")
    assert len(env.ai.calls) == 1


async def test_no_managers_configured(make_env):
    env = await make_env(admin_ids=frozenset())
    anna = env.person(1, "Anna")
    env.ai.next = AIResult("I can't help with that.", True)
    await anna.say("Refund please")
    assert anna.buttons() == []  # no hand-off button when nobody can take it
    await anna.say(texts.BTN_HUMAN)
    assert anna.last_text == texts.NO_MANAGERS


async def test_limits_protect_the_api_bill(make_env):
    env = await make_env(user_hourly_limit=2)
    anna = env.person(1, "Anna")
    for q in ("q1", "q2", "q3"):
        await anna.say(q)
    assert len(env.ai.calls) == 2 and anna.last_text == texts.USER_LIMIT

    env2 = await make_env(daily_ai_limit=1)
    a, b = env2.person(1, "A"), env2.person(2, "B")
    await a.say("q")
    await b.say("q")
    assert len(env2.ai.calls) == 1 and b.last_text == texts.DAILY_LIMIT


async def test_ai_failure_is_not_saved_to_history(make_env):
    env = await make_env()
    anna = env.person(1, "Anna")
    env.ai.next = AIResult(UNAVAILABLE, True, ok=False)
    await anna.say("hello?")
    assert anna.last_text == UNAVAILABLE
    env.ai.next = AIResult("Hi!", False)
    await anna.say("hello again")
    _, history = env.ai.calls[-1]
    assert [m["role"] for m in history] == ["user", "user"]


async def test_demo_visitor_panel_is_read_only(make_env):
    env = await make_env()
    bob = env.person(2, "Bob")
    await bob.say("/admin")
    assert "Support panel" in bob.last_text and "Demo mode" in bob.last_text
    assert "➕ Add document" not in bob.buttons()
    await bob.press("Knowledge base")
    await bob.press("Nordic Home")
    assert "Telliskivi" in bob.last_text and "🗑 Delete" not in bob.buttons()


async def test_non_admin_without_demo_cannot_open_panel(make_env):
    env = await make_env(demo_mode=False)
    bob = env.person(2, "Bob")
    await bob.say("/admin")
    assert not any(isinstance(m, SendMessage) and m.chat_id == 2 for m, _ in env.session.log)


async def test_manager_edits_knowledge_base(make_env):
    env = await make_env()
    manager = env.person(99, "Manager")
    await manager.say("/admin")
    assert "1 document(s)" in manager.last_text

    await manager.press("Add document")
    await manager.say("Opening hours\nChristmas: closed 24–26 December.")
    assert "Added <b>Opening hours</b>" in manager.last_text

    await manager.press("Back")
    await manager.press("Add document")
    await manager.say(document=("prices.txt", "Linen duvet cover: €79".encode()))
    assert "Added <b>prices</b>" in manager.last_text

    await manager.press("Back")
    await manager.press("Add document")
    await manager.say(document=("photo.jpg", b"\xff\xd8"))
    assert "Please send a .txt, .md or .pdf file" in manager.last_text

    docs = await env.repo.docs()
    assert [d.title for d in docs][1:] == ["Opening hours", "prices"]

    await manager.say("/admin")
    await manager.press("Knowledge base")
    await manager.press("prices")
    await manager.press("Delete")
    await manager.press("Yes, delete")
    assert "Deleted" in manager.last_text
    assert len(await env.repo.docs()) == 2
