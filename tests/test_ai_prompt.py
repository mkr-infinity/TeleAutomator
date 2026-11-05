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
    assert pm.language == "dynamic"

    prompt_dyn = pm.build_user_prompt(sender_name="Alex", incoming_text="hello")
    assert "Match the exact language" in prompt_dyn

    pm.set_language("english")
    assert pm.language == "english"
    prompt_en = pm.build_user_prompt(sender_name="Alex", incoming_text="kya haal hai")
    assert "reply ONLY in English" in prompt_en

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
