# pylaai-op-xxz

> [Русская версия](README.ru.md)

A semi-independent Brawl Stars bot fork focused on **Showdown (trio)**. Originally branched from xxz's source-code fork of PylaAI, but a large part of this tree is now original work — a custom FastAPI + React-style web UI, Brawl Stars API plumbing for trophy lookup and Push All, a wall-based unstuck detector, MuMu emulator support, and an experimental performance-profile system.

## Credits

This project would not exist without:

- **PylaAI** — the original bot — https://github.com/PylaAI/PylaAI (devs: Iyordanov, AngelFire)
- **PylaAi-XXZ** — the source-code fork this tree branched from — https://github.com/xxz-888/PylaAi-XXZ

Everything Showdown-specific (analog joystick movement, trio team spacing, fog avoidance, semicircle escape), the entire `web_ui/` + `backend/` stack, the Brawl Stars API plumbing, and the MuMu support are local additions on top of those upstreams.

> **Note.** This is a developer-oriented source build. For a stable, supported binary, use the official PylaAI release distributed via the Pyla Discord — not this repository.

## What's in this fork

### Showdown (trio) gameplay
- **Analog joystick movement** — continuous angle output instead of WASD taps; smoother pathing and dodging.
- **Teammate following with hysteresis** — when no enemy is in range, follows a chosen teammate without ping-ponging between two nearby ones.
- **Trio team spacing** — avoids stacking on teammates, orbits when grouped, biases back toward the team instead of chasing alone.
- **Passive roam** when alone and safe.
- **Poison fog avoidance** — detects fog mass; if a trusted mass enters the flee radius, overrides movement to escape the opposite way.
- **Wall-based unstuck + semicircle escape** — if surrounding walls stop moving while the bot is commanding movement, retreats from the obstacle and sweeps a semicircular arc around it. Arc side alternates between triggers.
- **Place-based trophy tracking** — recognizes 1st/2nd/3rd/4th end screens.

### Web UI (`web_ui/` + `backend/`)
A FastAPI backend serves a single-page panel that replaces the legacy Tkinter Hub for everyday use.

- Live dashboard: trophy / WR / streak stats, per-brawler goal queue (independent target per brawler).
- **Push All** with a configurable trophy threshold — sets one common goal across every brawler under the threshold via the Brawl Stars API.
- Stats and match history pages backed by `cfg/match_log.jsonl`.
- Settings page for Brawl Stars API token / auto-refresh, Discord webhook, performance profiles, language (EN/RU).

Backend entry points: [backend/server.py](backend/server.py) (FastAPI + WS), [backend/bot_runner.py](backend/bot_runner.py) (runs the same `Main` loop as `pyla_main`), [backend/lobby_scanner.py](backend/lobby_scanner.py) (OCR over the brawler-selection screen). [sessions.py](sessions.py) persists per-session metadata.

### Recovery & supervision
- Relaunches Brawl Stars if it closes or another window is in front.
- Presses **Reload** on the Idle Disconnect dialog (works on both LDPlayer's bright overlay and MuMu's dark overlay).
- Restarts the scrcpy feed instead of the game when the video stream freezes.
- A small `Pyla Control` window lets you pause/resume movement safely while the bot is running.

### Emulator support
- LDPlayer (default) and **MuMu 12 / older MuMu** — fast 50 ms TCP probing brings ADB connection time from ~54 s down to ~2 s and respects the chosen emulator (a running LDPlayer no longer masks a MuMu connection).

## Installation

There is **no `setup.exe`** in this fork — installation is the standard Python flow.

1. Install **Python 3.11 (64-bit)** and Git.
2. Clone the repository and `cd` into it.
3. Run `python setup.py install` to pull all required Python packages and pick a working ONNX Runtime build (GPU when possible, otherwise CPU).
4. Start your Android emulator (LDPlayer or MuMu) and open Brawl Stars.
5. Set the emulator resolution to **1920×1080** for best results.
6. Run `python main.py` (or double-click [run.bat](run.bat)).
7. In the web UI: pick the emulator, configure brawlers, press **Start**.

### Launch flags
- `python main.py` — opens the web UI at `http://127.0.0.1:8765`.
- `python main.py --legacy` — falls back to the original Tk hub.
- `--host`, `--port`, `--no-browser` — standard server flags.

## Brawl Stars API (Push All + manual trophy lookup)

1. Create a developer account at https://developer.brawlstars.com/.
2. Open [cfg/brawl_stars_api.toml](cfg/brawl_stars_api.toml) and fill in:
   ```toml
   player_tag = "#YOURTAG"
   developer_email = "YOUR_DEVELOPER_EMAIL"
   developer_password = "YOUR_DEVELOPER_PASSWORD"
   ```
3. The player tag can also be set in the web UI Settings page.

Behavior:
- **Push All** (see below) reads trophies through the API to decide which brawlers to queue.
- **Auto-refresh** logs into the official developer portal, detects the current public IP, deletes old PylaAI-created keys, creates a fresh key for that IP, and saves the token locally.
- Keep `delete_all_tokens = false` unless you really want every key on the developer account wiped.
- **Never** commit a filled `brawl_stars_api.toml` — keep tokens, email, and password blank in commits.

> **Heads-up.** Per-brawler "Current Trophies" auto-fill from the API is **not reliable yet**, especially when running multiple instances — fields may stay empty or stale. Treat trophy fields as something you set manually for now; only Push All depends on the API and works.

### Push All
- Fill `cfg/brawl_stars_api.toml` first.
- Open Brawl Stars on the lobby screen.
- Web UI: enter a trophy target next to **Push All** on the dashboard and click. The bot queues every brawler under that threshold (sorted ascending by trophies) with `push_until = target`.
- Legacy Tk: use `Push All 1k` (1000-cap alias) or the new push-all dialog with a custom target.

## Performance

> Performance profiles are **experimental** — they exist in [performance_profile.py](performance_profile.py) and the CLI works, but tuning hasn't been finalized. Treat them as a starting point, not a guaranteed fix, and verify IPS after applying one.

If the bot drops to 1–3 IPS while Python CPU usage is low, try the safe capture profile and restart:

```
python tools/apply_performance_profile.py --profile balanced
```

Use `--profile low-end` for older laptops that overheat or throttle.

### Troubleshooting checklist
- Run [tools/performance_check.py](tools/performance_check.py).
  - If it reports `CPUExecutionProvider`, re-run `python setup.py install` or set `cpu_or_gpu = "directml"` in `cfg/general_config.toml`.
  - If `1–2 IPS` with low CPU, check the `scrcpy frame FPS` line — low FPS means the emulator/ADB feed is the bottleneck, not the model.
- Laptops with two GPUs: set Windows Graphics settings for `python.exe` and the emulator to **High performance**.
- DirectML active but slow: try `directml_device_id = "1"` in `cfg/general_config.toml`, then restart.
- Turn off Windows Efficiency mode for the emulator (it can cap frame delivery and stick the bot at 2–5 IPS).
- For LDPlayer / MuMu, pick the matching emulator in the UI or set `current_emulator = "LDPlayer"` / `"MuMu"` in `cfg/general_config.toml`. Use 1920×1080 landscape, emulator FPS = 60, disable any low-FPS / eco mode.
- Keep some free RAM. Above ~85% memory usage, close Discord/browsers/other games.
- Enable **Debug Screen** in Additional Settings for a live overlay (player, teammate, enemy, wall, fog, range).

## Wall model improvement

Active model: [models/tileDetector.onnx](models/tileDetector.onnx).

```
python tools/capture_wall_samples.py --seconds 300 --start-match
python tools/create_wall_dataset.py
# Label in YOLO format: 0 wall, 1 bush, 2 close_bush
python tools/train_wall_model.py --device 0
python tools/install_vision_model.py --source runs/wall_train/pylaai_wall/weights/best.onnx --target models/tileDetector.onnx
```

## Tests

```
python -m unittest discover
```

## Notes

- This is the **localhost** build — login, online stats tracking, auto brawler-list updates, auto icon updates, and auto wall-model updates are disabled. To go online, change the base API URL in [utils.py](utils.py) and re-implement the corresponding endpoints.
- A `.pt` version of the AI vision model is available at https://github.com/AngelFireLA/BrawlStarsBotMaking.
- This repository **will not** ship early-access features before they're released publicly upstream.
- Please respect the **non-commercial** clause of the license — see [LICENSE](LICENSE) (CC BY-NC 4.0).

## Contributing

Issues and Pull Requests are welcome. For upstream PylaAI discussion, the official Discord is:
https://discord.gg/xUusk3fw4A

Idea / to-fix list (upstream): https://trello.com/b/SAz9J6AA/public-pyla-trello
