PylaAI — sharing build for testing
====================================

This zip is a clean copy of PylaAI without my personal data, without the
bundled ~1 GB Python runtime, and without local logs / sessions.

QUICK INSTALL (Windows)
------------------------

1. Install Python 3.11 from https://www.python.org/downloads/release/python-3119/
   (CHECK "Add Python to PATH" during install).

2. Install LDPlayer 9 from https://www.ldplayer.net (or use any android
   emulator with ADB on a known port).

3. Open a terminal in the extracted PylaAI folder and run:

       py -3.11 -m pip install --upgrade pip wheel setuptools
       py -3.11 setup.py install

   The setup script auto-detects your GPU and installs the matching torch /
   onnxruntime build (NVIDIA → CUDA, AMD/Intel → DirectML, otherwise CPU).

4. Open cfg/general_config.toml and adjust:
       current_emulator = "LDPlayer"
       emulator_port    = 5555     (5555 for LD instance #0, 5557 for #1, …)

   (Optional) For the Brawl Stars API trophy auto-fill, drop your own token
   into cfg/brawl_stars_api.toml — I removed mine.

5. Start the bot:

       run.bat

   Browser opens at http://127.0.0.1:8765 → choose a brawler → Start.

MULTI-EMULATOR (the new feature)
---------------------------------

After it boots, go to the "Инстансы" tab → "+ Добавить инстанс" → pick
LDPlayer → click "🔎 Найти LDPlayer-инстансы" to auto-discover your VMs.
Each instance runs as its own subprocess and can have its own brawler/target
through the "✎ Сессия" button on its card. The Dashboard "Run on:" panel
broadcasts a single click to all selected instances.

WHAT'S NOT INCLUDED
--------------------

- _internal/  — 932 MB PyInstaller runtime that backs setup.exe. Not needed
                if you have Python 3.11 installed; setup.py installs deps via
                pip directly.
- logs/       — my local log history.
- instances/  — my local per-emulator state.
- cfg/match_log.jsonl, cfg/adaptive_state.json — my personal stats.

SECRETS
--------

I scrubbed:
  - cfg/brawl_stars_api.toml (token, dev email/password, player tag)
  - cfg/webhook_config.toml  (Discord webhook URL)
  - cfg/general_config.toml  (personal_webhook, player_tag, last_public_ip)

You'll need to fill these in for yourself if you want trophy autofill or
Discord notifications.
