"""The Gemini layer, tested with a fake client (no network, no cost)."""
from types import SimpleNamespace as NS

from google.genai import errors, types

from bot.ai import SORRY, UNAVAILABLE, Reply, SupportAI, estimate_cost, to_contents
from bot.config import load_config
from bot.db import Doc


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_client(**kw):
    models = FakeModels(**kw)
    return NS(aio=NS(models=models)), models


def response(reply: Reply | None, text: str = "", finish=types.FinishReason.STOP, block=None):
    usage = NS(prompt_token_count=2100, candidates_token_count=40, thoughts_token_count=60,
               cached_content_token_count=2000)
    return NS(parsed=reply, text=reply.model_dump_json() if reply else text,
              candidates=[NS(finish_reason=finish)], prompt_feedback=NS(block_reason=block) if block else None,
              usage_metadata=usage)


DOCS = [Doc(id=1, title="Delivery", content="Tartu: 1–2 days, €4.90.")]
HISTORY = [{"role": "user", "content": "Do you deliver to Tartu?"}]
CFG = load_config(business_name="Nordic Home", model="gemini-test", fallback_models=())


async def test_request_shape_and_answer():
    client, models = fake_client(response=response(Reply(answer="Yes, €4.90.", needs_human=False)))
    result = await SupportAI(CFG, client).reply(DOCS, HISTORY)  # type: ignore[arg-type]
    assert result.ok and result.answer == "Yes, €4.90." and not result.needs_human
    assert result.usage == {"input_tokens": 2100, "output_tokens": 100, "cache_read_tokens": 2000,
                            "cache_write_tokens": 0}

    req = models.calls[0]
    assert req["model"] == "gemini-test"
    cfg = req["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_schema is Reply
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert "Nordic Home" in cfg.system_instruction
    assert '<document title="Delivery">' in cfg.system_instruction and "€4.90" in cfg.system_instruction
    assert req["contents"][0].role == "user" and req["contents"][0].parts[0].text == "Do you deliver to Tartu?"


async def test_json_text_used_when_parsed_missing():
    resp = response(None, text='{"answer": "Hi!", "needs_human": true}')
    client, _ = fake_client(response=resp)
    result = await SupportAI(CFG, client).reply(DOCS, HISTORY)  # type: ignore[arg-type]
    assert result.ok and result.answer == "Hi!" and result.needs_human


async def test_safety_block_offers_human():
    for resp in (response(None, finish=types.FinishReason.SAFETY), response(None, block="SAFETY")):
        client, _ = fake_client(response=resp)
        result = await SupportAI(CFG, client).reply(DOCS, HISTORY)  # type: ignore[arg-type]
        assert not result.ok and result.needs_human and result.answer == SORRY


async def test_broken_output_is_handled():
    client, _ = fake_client(response=response(None, text="not json", finish=types.FinishReason.MAX_TOKENS))
    result = await SupportAI(CFG, client).reply(DOCS, HISTORY)  # type: ignore[arg-type]
    assert not result.ok and result.answer == SORRY


async def test_api_errors_become_friendly_text():
    errs = [errors.ClientError(403, {"error": {"message": "bad key"}}),
            errors.ClientError(429, {"error": {"message": "quota"}}),
            errors.ServerError(503, {"error": {"message": "overloaded"}}),
            ConnectionError("offline")]
    for err in errs:
        client, _ = fake_client(error=err)
        result = await SupportAI(CFG, client).reply(DOCS, HISTORY)  # type: ignore[arg-type]
        assert not result.ok and result.answer == UNAVAILABLE, type(err)


class ScriptedModels:
    """Each call takes the next outcome: an exception to raise or a response to return."""
    def __init__(self, outcomes):
        self.outcomes, self.models = list(outcomes), []

    async def generate_content(self, model, **kwargs):
        self.models.append(model)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


async def test_falls_back_when_model_is_busy():
    cfg = load_config(model="main", fallback_models=("backup1", "backup2"))
    ok = response(Reply(answer="From backup", needs_human=False))
    models = ScriptedModels([errors.ServerError(503, {"error": {"message": "busy"}}),
                             errors.ClientError(404, {"error": {"message": "retired"}}), ok])
    result = await SupportAI(cfg, NS(aio=NS(models=models))).reply(DOCS, HISTORY)  # type: ignore[arg-type]
    assert result.answer == "From backup" and models.models == ["main", "backup1", "backup2"]


async def test_bad_key_does_not_try_fallbacks():
    cfg = load_config(model="main", fallback_models=("backup1",))
    models = ScriptedModels([errors.ClientError(403, {"error": {"message": "bad key"}})])
    result = await SupportAI(cfg, NS(aio=NS(models=models))).reply(DOCS, HISTORY)  # type: ignore[arg-type]
    assert result.answer == UNAVAILABLE and models.models == ["main"]


def test_history_roles_and_merging():
    contents = to_contents([
        {"role": "user", "content": "a"}, {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"}, {"role": "user", "content": "d"},
    ])
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [p.text for p in contents[0].parts] == ["a", "b"]


def test_empty_knowledge_base_is_explicit():
    client, _ = fake_client()
    assert "empty" in SupportAI(CFG, client).system([])  # type: ignore[arg-type]


def test_cost_estimate_only_with_prices():
    t = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_tokens": 0, "cache_write_tokens": 0}
    assert estimate_cost(CFG, t) is None
    priced = load_config(price_input=0.3, price_output=2.5)
    assert estimate_cost(priced, t) == 2.8
