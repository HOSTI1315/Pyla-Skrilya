// Mock data for PylaAI — a Brawl Stars auto-player bot

const BRAWLERS = [
  { id: 'shelly',  name: 'Shelly',   rarity: 'Starting',  trophies: 412, color: '#F8B733', icon: 'S', wr: 58 },
  { id: 'colt',    name: 'Colt',     rarity: 'Rare',      trophies: 389, color: '#2D7DD2', icon: 'C', wr: 54 },
  { id: 'bull',    name: 'Bull',     rarity: 'Rare',      trophies: 356, color: '#E85D75', icon: 'B', wr: 61 },
  { id: 'nita',    name: 'Nita',     rarity: 'Rare',      trophies: 341, color: '#8E6D3C', icon: 'N', wr: 52 },
  { id: 'elprimo', name: 'El Primo', rarity: 'Super Rare',trophies: 402, color: '#D13B3B', icon: 'P', wr: 63 },
  { id: 'barley',  name: 'Barley',   rarity: 'Super Rare',trophies: 298, color: '#8FB339', icon: 'B', wr: 49 },
  { id: 'poco',    name: 'Poco',     rarity: 'Super Rare',trophies: 367, color: '#C36CD6', icon: 'P', wr: 56 },
  { id: 'rosa',    name: 'Rosa',     rarity: 'Super Rare',trophies: 378, color: '#5FAD56', icon: 'R', wr: 59 },
  { id: 'jessie',  name: 'Jessie',   rarity: 'Super Rare',trophies: 324, color: '#F7A928', icon: 'J', wr: 53 },
  { id: 'dynamike',name: 'Dynamike', rarity: 'Epic',      trophies: 287, color: '#D97441', icon: 'D', wr: 47 },
  { id: 'tick',    name: 'Tick',     rarity: 'Epic',      trophies: 256, color: '#6EBAA7', icon: 'T', wr: 45 },
  { id: '8bit',    name: '8-Bit',    rarity: 'Epic',      trophies: 201, color: '#4E4B87', icon: '8', wr: 50 },
];

// `botConfig` maps each UI mode to what gets written into bot_config.toml.
// The bot only distinguishes brawlball / showdown / "other" for 3-orientation
// modes (matches the legacy tkinter hub). Generic 3v3 modes share the
// "other" gamemode key — refine later if the bot grows mode-specific logic.
const GAME_MODES = [
  { id: 'gemgrab',   name: 'Gem Grab',    type: '3v3', color: '#B45EE8', active: true,  botConfig: { gamemode: 'other',     gamemode_type: 3 } },
  { id: 'showdown',  name: 'Showdown',    type: 'Solo',color: '#64A33B', active: false, botConfig: { gamemode: 'showdown',  gamemode_type: 3 } },
  { id: 'brawlball', name: 'Brawl Ball',  type: '3v3', color: '#5B8DEF', active: false, botConfig: { gamemode: 'brawlball', gamemode_type: 3 } },
  { id: 'bounty',    name: 'Bounty',      type: '3v3', color: '#F2A33A', active: false, botConfig: { gamemode: 'other',     gamemode_type: 3 } },
  { id: 'heist',     name: 'Heist',       type: '3v3', color: '#E25858', active: false, botConfig: { gamemode: 'other',     gamemode_type: 3 } },
  { id: 'hotzone',   name: 'Hot Zone',    type: '3v3', color: '#E56BAF', active: false, botConfig: { gamemode: 'other',     gamemode_type: 3 } },
];

// Live log lines — represent bot decisions & actions
const LOG_LINES = [
  { t: '00:00:02', lvl: 'info',   msg: 'Session started · target range 300–400 🏆' },
  { t: '00:00:03', lvl: 'info',   msg: 'Detected screen: main_menu' },
  { t: '00:00:04', lvl: 'action', msg: 'tap(event=play_button, pos=540,1180)' },
  { t: '00:00:06', lvl: 'info',   msg: 'Queue enter · mode=gem_grab' },
  { t: '00:00:21', lvl: 'info',   msg: 'Match found · loading…' },
  { t: '00:00:28', lvl: 'info',   msg: 'YOLOv8 vision init · fps=30 conf=0.72' },
  { t: '00:00:29', lvl: 'action', msg: 'move(joystick, θ=-42°, mag=0.88)' },
  { t: '00:00:33', lvl: 'action', msg: 'attack(target=enemy_colt, d=3.2m)' },
  { t: '00:00:34', lvl: 'warn',   msg: 'Low HP (28%) · retreating to bush' },
  { t: '00:00:42', lvl: 'action', msg: 'super(aim=enemy_crowd, hits=2)' },
  { t: '00:00:58', lvl: 'info',   msg: 'Gem count: 7/10 · holding position' },
  { t: '00:01:12', lvl: 'ok',     msg: 'Victory · +8 🏆 · time=1:34' },
  { t: '00:01:15', lvl: 'info',   msg: 'Returning to menu…' },
  { t: '00:01:18', lvl: 'action', msg: 'tap(event=continue)' },
  { t: '00:01:22', lvl: 'info',   msg: 'Shelly → 412 🏆 · threshold OK, continuing' },
  { t: '00:01:30', lvl: 'action', msg: 'tap(event=play_button)' },
  { t: '00:01:48', lvl: 'info',   msg: 'Match found · loading…' },
  { t: '00:02:02', lvl: 'action', msg: 'move(joystick, θ=88°, mag=1.00)' },
  { t: '00:02:19', lvl: 'warn',   msg: 'Defeat · –7 🏆 · time=2:02' },
  { t: '00:02:22', lvl: 'info',   msg: 'Shelly → 405 🏆 · within target range' },
];

// Session history
const SESSIONS = [
  { d: 'Today',     games: 47, w: 24, l: 23, net: '+14', dur: '3h 12m' },
  { d: 'Yesterday', games: 82, w: 41, l: 41, net: '–8',  dur: '5h 41m' },
  { d: 'Mon 04/14', games: 61, w: 33, l: 28, net: '+42', dur: '4h 05m' },
  { d: 'Sun 04/13', games: 38, w: 19, l: 19, net: '+6',  dur: '2h 30m' },
  { d: 'Sat 04/12', games: 74, w: 36, l: 38, net: '–12', dur: '5h 10m' },
];

// 60-point trophy timeline sample for the chart
const TROPHY_CURVE = [
  380,384,388,385,389,393,397,401,398,402,406,410,408,412,
  415,411,407,403,406,410,414,418,415,412,408,404,407,411,
  414,418,421,419,415,411,414,418,420,417,413,410,406,403,
  400,397,394,397,401,405,409,412,415,418,414,411,408,411,
  414,417,420,423
];

Object.assign(window, { BRAWLERS, GAME_MODES, LOG_LINES, SESSIONS, TROPHY_CURVE });
