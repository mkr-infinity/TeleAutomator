def enable_auto_replies(manager, *chat_ids):
    """Give transport tests the same prerequisites as real automatic delivery."""
    manager.set_mode("restricted_auto")
    manager.safety.set_auto_authorization(True)
    manager.db.set_state("quiet_hours_enabled", "0")
    manager.db.set_state("ownreact_enabled", "0")
    manager.db.set_state("spontaneous_followup_enabled", "0")
    for chat_id in chat_ids:
        manager.privacy.allow_chat(chat_id)
