"""Tests for PromptManager and ReplyGenerator."""

from pathlib import Path
from app.ai.prompt_manager import PromptManager, VALID_STYLES
from app.ai.reply_generator import ReplyGenerator
from app.ai.provider import LocalRuleProvider
from app.config import AppConfig


def test_prompt_manager_styles():
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    assert pm.style == "casual"

    # Test changing styles
    assert pm.set_style("concise") is True
    assert pm.style == "concise"
    assert "brief" in pm.system_instructions.lower()

    assert pm.set_style("formal") is True
    assert pm.style == "formal"
    assert "professional" in pm.system_instructions.lower()

    assert pm.set_style("humorous") is True
    assert pm.style == "humorous"

    assert pm.set_style("invalid_style") is False
    assert pm.style == "humorous"


def test_prompt_manager_conversation_history():
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    history = [
        {"sender": "You", "text": "Hey are you coming?"},
        {"sender": "Alice", "text": "Yes, leaving now."},
    ]
    prompt = pm.build_user_prompt(
        sender_name="Alice",
        incoming_text="Where should we meet?",
        conversation_history=history,
    )
    assert "Recent conversation context:" in prompt
    assert 'You: "Hey are you coming?"' in prompt
    assert 'Alice: "Yes, leaving now."' in prompt
    assert 'Where should we meet?' in prompt


def test_prompt_clean_reply_and_anti_robotic():
    pm = PromptManager(prompt_file=None, owner_name="Kaif")

    # Strips robotic openings
    assert pm.clean_reply("Certainly! Let's meet at 5.") == "Let's meet at 5."
    assert pm.clean_reply("Sure thing! On my way.") == "On my way."
    assert pm.clean_reply("Here is a draft: sounds good!") == "sounds good!"

    # Strips robotic closers
    assert pm.clean_reply("I will be there. Hope this helps!") == "I will be there."

    # Strips URLs strictly
    assert "http" not in pm.clean_reply("Check this out https://spam.com/invite")
    assert "t.me" not in pm.clean_reply("Join t.me/joinchat/123456")

    # Strips name prefixes
    assert pm.clean_reply("Kaif: haan bhai") == "haan bhai"
    assert pm.clean_reply("AI: I am on it") == "I am on it"


def test_reply_generator_with_history(tmp_path: Path):
    cfg = AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        data_dir=tmp_path,
        ai_enabled=False,  # Uses LocalRuleProvider
    )
    generator = ReplyGenerator(cfg, provider=LocalRuleProvider())
    assert generator.style == "casual"
    generator.set_style("concise")
    assert generator.style == "concise"

    history = [{"sender": "Bob", "text": "Hey"}]
    reply = generator.generate("Bob", "hello", conversation_history=history)
    assert len(reply) > 0


def test_language_customization():
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    # English is default
    assert pm.language == "english"

    prompt_en = pm.build_user_prompt(sender_name="Alex", incoming_text="kya haal hai")
    assert "reply ONLY in English" in prompt_en

    pm.set_language("dynamic")
    assert pm.language == "dynamic"
    prompt_dyn = pm.build_user_prompt(sender_name="Alex", incoming_text="hello")
    assert "Match the exact language" in prompt_dyn

    pm.set_language("hindi")
    assert pm.language == "hindi"
    prompt_hi = pm.build_user_prompt(sender_name="Alex", incoming_text="how are you")
    assert "reply ONLY in Hindi" in prompt_hi


def test_anti_code_and_formatting_scrubbing():
    pm = PromptManager(prompt_file=None, owner_name="Kaif")

    # Strips code paths like /etc, /var, /usr
    cleaned = pm.clean_reply("Check /etc/passwd and /var/log/syslog bro")
    assert "/etc" not in cleaned
    assert "/var" not in cleaned

    # Strips brackets [] and braces {}
    bracket_cleaned = pm.clean_reply("[Note: replying casually] {metadata: null} hey bro!")
    assert "[" not in bracket_cleaned
    assert "]" not in bracket_cleaned
    assert "{" not in bracket_cleaned
    assert "}" not in bracket_cleaned
    assert "hey bro!" in bracket_cleaned

    # Strips markdown bold, italic, and backticks
    md_cleaned = pm.clean_reply("**bold statement** and *italic* with `inline code`")
    assert "**" not in md_cleaned
    assert "*" not in md_cleaned
    assert "`" not in md_cleaned
    assert "bold statement and italic with inline code" == md_cleaned


def test_system_prompt_word_limit():
    prompt_path = Path("system_prompt.txt")
    assert prompt_path.exists()
    content = prompt_path.read_text(encoding="utf-8")
    words = [w for w in content.split() if not w.startswith("#")]
    # Sweet spot is under 350 words to avoid instruction dilution
    assert len(words) <= 350
    assert "BREVITY" in content
    assert "HUMAN ALIBI" in content


def test_openai_provider_candidate_models_and_fallback():
    from unittest.mock import MagicMock, patch
    from app.ai.provider import OpenAIProvider

    provider = OpenAIProvider(
        api_key="test_key",
        model="non_existent_model",
        base_url="https://api.inceptionlabs.ai/v1",
    )
    candidates = provider.get_candidate_models()
    assert "non_existent_model" in candidates
    assert "mercury-3" in candidates
    assert "mercury-3-preview-1014" in candidates

    # Simulate first model failing with 404, second model succeeding
    call_count = 0

    def mock_urlopen(req, timeout=15):
        nonlocal call_count
        call_count += 1
        data = json.loads(req.data.decode("utf-8"))
        if data["model"] == "non_existent_model":
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        # Success for mercury-3
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Fallback reply from mercury-3"}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    import json
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = provider.generate_reply("Hi", "Be brief")
        assert result == "Fallback reply from mercury-3"
        # Verified provider switched active model to the working fallback
        assert provider.model == "mercury-3"
        assert call_count == 2


def test_max_tokens_defaults_to_provider_native():
    """Verify max_tokens defaults to None (let provider decide) and is omitted from payload to prevent token starvation."""
    import json
    from unittest.mock import MagicMock, patch
    from app.ai.provider import OpenAIProvider

    provider = OpenAIProvider(api_key="test_key", model="mercury-3")
    assert provider.max_tokens is None

    sent_payload = None
    def mock_urlopen(req, timeout=15):
        nonlocal sent_payload
        sent_payload = json.loads(req.data.decode("utf-8"))
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        provider.generate_reply("Hi", "Be brief")
        assert "max_tokens" not in sent_payload

    # When user explicitly sets max_tokens
    provider.max_tokens = 500
    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        provider.generate_reply("Hi", "Be brief")
        assert sent_payload.get("max_tokens") == 500



def test_custom_prompt_wrapping_and_anti_ai_guardrails():
    """Verify custom persona from Telegram wraps inside unbreakable anti-AI guardrails."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    # Setting custom persona
    pm.custom_prompt = "I am a crypto trader and gamer who talks sarcastically"
    instructions = pm.system_instructions

    # Custom persona is present
    assert "crypto trader and gamer" in instructions
    # Core anti-AI guardrails are strictly preserved
    assert "BREVITY & ENERGY MATCHING" in instructions
    assert "HUMAN ALIBI" in instructions
    assert "SLANG" in instructions
    assert "NO CODE" in instructions

    # Resetting custom persona
    pm.reset_custom_prompt()
    assert pm.custom_prompt == ""
    assert "crypto trader" not in pm.system_instructions
    assert "BREVITY & ENERGY MATCHING" in pm.system_instructions


def test_ai_confession_interception():
    """Verify that any accidental AI admission is intercepted and replaced with human alibi banter."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")

    bot_output = "As an AI language model, I cannot fulfill this request."
    cleaned = pm.clean_reply(bot_output)
    assert "as an ai" not in cleaned.lower()
    assert any(h in cleaned for h in ("it's me lol", "think I am not real", "typing from my phone", "bot lol"))

    bot_output2 = "I am a virtual assistant created to help you."
    cleaned2 = pm.clean_reply(bot_output2)
    assert "virtual assistant" not in cleaned2.lower()
    assert any(h in cleaned2 for h in ("it's me lol", "think I am not real", "typing from my phone", "bot lol"))


def test_conversational_engagement_instruction_in_prompt():
    """Verify build_user_prompt instructs natural conversational engagement instead of blunt 1-word shortcuts."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    prompt = pm.build_user_prompt(sender_name="Alex", incoming_text="hii")
    assert "Engagement Rule" in prompt
    assert "conversational, natural, and engaging" in prompt
    assert "no robotic 1-word shortcuts" in prompt


def test_fallback_reply_mechanism():
    """Verify get_fallback_reply produces engaging human responses without blunt word-shortcut dictionaries."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    greeting_fb = pm.get_fallback_reply("hi")
    assert any(h in greeting_fb for h in ("kya chal raha", "caught up", "batao aur", "tell me"))

    alibi_fb = pm.get_fallback_reply("are you a bot?")
    assert "lol" in alibi_fb or "real" in alibi_fb


def test_never_use_question_marks():
    """Verify question marks are completely stripped from replies and barred in instructions."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    raw = "What are you doing? Is everything ok? Let me know!"
    cleaned = pm.clean_reply(raw)
    assert "?" not in cleaned
    assert "What are you doing" in cleaned

    prompt = pm.build_user_prompt("Bob", "sup")
    assert "NEVER use question marks" in prompt


def test_emojis_preserved_naturally_middle_or_end():
    """Verify emojis are preserved naturally whether in the middle or at the end of messages."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    # Natural emoji at the end
    cleaned1 = pm.clean_reply("all good bro 😂")
    assert "😂" in cleaned1
    assert "all good bro" in cleaned1

    # Natural emoji in the middle
    cleaned2 = pm.clean_reply("haan 😂 bro was thinking the same")
    assert "😂" in cleaned2
    assert "haan" in cleaned2


def test_permanent_context_in_prompt():
    """Verify permanent chat background and pinned info are included in prompt."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    perm = "Pinned Rule: No spam. Group Topic: AI development."
    prompt = pm.build_user_prompt(
        sender_name="Alex",
        incoming_text="what's the update",
        permanent_context=perm,
    )
    assert "PERMANENT CHAT BACKGROUND & PINNED INFO" in prompt
    assert "Pinned Rule: No spam" in prompt
    assert "AI development" in prompt


def test_strict_default_english_language_everywhere():
    """Verify English is strictly enforced everywhere (DMs and groups) unless user explicitly configures another language."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    assert pm.language == "english"

    # 1. English group context
    prompt_en_group = pm.build_user_prompt(
        sender_name="Alex",
        incoming_text="what is the release timeline for the project",
        is_group=True,
    )
    assert "CRITICAL LANGUAGE RULE (English Only)" in prompt_en_group
    assert "NEVER use Hindi" in prompt_en_group

    # 2. Hindi text in group STILL enforces English by default
    prompt_hi_input = pm.build_user_prompt(
        sender_name="Rahul",
        incoming_text="kya haal hai bhai sab theek",
        is_group=True,
    )
    assert "CRITICAL LANGUAGE RULE (English Only)" in prompt_hi_input
    assert "NEVER use Hindi" in prompt_hi_input

    # 3. Only when user explicitly changes language from Telegram (e.g. /lang hindi or /lang dynamic)
    pm.set_language("hindi")
    prompt_custom_hi = pm.build_user_prompt(
        sender_name="Rahul",
        incoming_text="kya haal hai bhai sab theek",
        is_group=True,
    )
    assert "User configured language is Hindi" in prompt_custom_hi
    assert "You MUST reply ONLY in Hindi" in prompt_custom_hi

    pm.set_language("dynamic")
    prompt_dyn = pm.build_user_prompt(
        sender_name="Rahul",
        incoming_text="kya haal hai bhai sab theek",
        is_group=True,
    )
    assert "Match the exact language and writing style of the sender" in prompt_dyn


def test_clean_reply_suppresses_none_and_word_repetition():
    """Verify clean_reply handles literal None and cleans consecutive duplicate words."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")

    # None and empty variations return empty string
    assert pm.clean_reply("None") == ""
    assert pm.clean_reply("none.") == ""
    assert pm.clean_reply("null") == ""
    assert pm.clean_reply("undefined") == ""

    # Immediate word repetitions are condensed
    assert pm.clean_reply("bro bro was thinking the same") == "bro was thinking the same"
    assert pm.clean_reply("haan haan sahi hai") == "haan sahi hai"
    assert pm.clean_reply("cool cool cool") == "cool"


def test_top_common_emojis_and_active_group_engagement():
    """Verify minimum 5 commonly used emojis and active group engagement instructions are in prompt."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    prompt = pm.build_user_prompt(sender_name="Alex", incoming_text="anyone working on the bot", is_group=True)

    # Minimum 5 commonly used emojis present
    top_emojis = ["😂", "👍", "🔥", "👀", "🤝", "💀", "💯", "❤️"]
    found_emojis = [em for em in top_emojis if em in prompt]
    assert len(found_emojis) >= 5

    # Active group engagement instruction present
    assert "active Telegram user" in prompt
    assert "understand discussions" in prompt or "chime in naturally" in prompt


def test_strict_word_limits_and_hard_cap():
    """Verify clean_reply enforces strict 15-word ceiling."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")

    # Short message stays intact
    short_msg = "lol true 😂"
    assert pm.clean_reply(short_msg) == short_msg

    # 10-word message stays intact
    ten_words = "one two three four five six seven eight nine ten"
    assert pm.clean_reply(ten_words) == ten_words

    # 15-word message stays intact
    fifteen_words = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen"
    assert pm.clean_reply(fifteen_words) == fifteen_words

    # >15-word message is cleanly capped to 15 words
    twenty_words = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
    cleaned = pm.clean_reply(twenty_words)
    words = cleaned.split()
    assert len(words) == 15
    assert words[-1] == "fifteen"


def test_ist_time_awareness_and_brevity_instructions_in_prompt():
    """Verify prompt includes IST time-of-day awareness and strict brevity rule."""
    pm = PromptManager(prompt_file=None, owner_name="Kaif")
    prompt = pm.build_user_prompt(sender_name="Alex", incoming_text="good morning")

    assert "Time Context:" in prompt
    assert "IST (" in prompt
    assert any(period in prompt for period in ("morning", "afternoon", "evening", "night"))

    assert "Brevity Rule:" in prompt
    assert "Cap replies strictly to max 10 words" in prompt
    assert "10 to 15 words" in prompt
    assert "NEVER exceed 15 words" in prompt


