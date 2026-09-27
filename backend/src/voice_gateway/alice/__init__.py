"""Alice skill adapter: durable queue, auth, webhook and dialogue.

The adapter is an add-on inside the existing voice gateway: Yandex Alice
brings her own STT/TTS, the gateway keeps the shared text processor
(:mod:`backend.src.voice_gateway.text_turns`). Nothing here touches the
device audio protocol or the firmware (plan tasks 3–5).
"""
