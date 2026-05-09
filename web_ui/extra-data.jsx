// Default values for settings UI. All keys here are backed by a real TOML key
// in cfg/ and round-trip through /api/config/{file}.

const DEFAULT_SETTINGS = {
  // ── Runtime / general_config.toml ────────────────────────────
  currentEmulator: 'Others',
  emulatorPort: 5555,
  cpuOrGpu: 'auto',           // auto | directml | cuda | openvino | cpu
  directmlDeviceId: 'auto',
  maxIps: 24,
  scrcpyMaxFps: 30,
  // scrcpy frame width — drives ALL spatial pixel-count thresholds (super/
  // gadget/hyper). 1280 is a good balance: enough resolution for HSV button
  // detection to fire without hammering CPU/GPU. Below ~960 the bot may
  // fail to register charged supers (the Play._ability_threshold scaling
  // floors at 0.25, but a tiny ROI can still under-shoot).
  scrcpyMaxWidth: 1280,
  scrcpyBitrate: 3000000,
  onnxCpuThreads: 4,
  usedThreads: 4,
  runForMinutes: 600,
  trophiesMultiplier: 1,
  brawlStarsPackage: 'com.supercell.brawlstars',
  apiBaseUrl: 'default',
  longPressStarDrop: false,

  // ── Vision / bot_config.toml ────────────────────────────────
  entityDetectionConfidence: 0.75,
  wallDetectionConfidence: 0.8,
  superPixelsMinimum: 2400,
  gadgetPixelsMinimum: 1300,
  hyperchargePixelsMinimum: 2000,
  idlePixelsMinimum: 3000,

  // ── Movement / bot_config.toml ──────────────────────────────
  minimumMovementDelay: 0.1,
  attackCooldown: 0.16,
  gadgetCooldown: 1.0,
  superCooldown: 1.0,
  unstuckMovementDelay: 3.0,
  unstuckMovementHoldTime: 1.2,
  wallStuckEnabled: true,
  wallStuckTimeout: 3.0,
  wallStuckIgnoreRadius: 150,
  wallStuckMinWalls: 3,
  escapeRetreatDuration: 0.4,
  escapeArcDuration: 1.2,
  escapeArcDegrees: 135.0,

  // ── Match / bot_config.toml ─────────────────────────────────
  botUsesGadgets: true,
  playAgainOnWin: false,
  trioGroupingEnabled: true,
  teammateFollowMinDistance: 180,
  teammateFollowMaxDistance: 520,
  teammateCombatRegroupDistance: 650,
  teammateCombatBias: 0.35,
  secondsToHoldAttackAfterReachingMax: 1.5,

  // ── Timing / time_tresholds.toml ────────────────────────────
  timeStateCheck: 1.5,
  timeNoDetections: 10,
  timeGameStart: 0,
  timeIdle: 5,
  timeGadget: 0.1,
  timeHypercharge: 0.1,
  timeSuper: 0.1,
  timeWallDetection: 0.25,
  timeNoDetectionProceed: 6.5,
  timeCrashCheck: 10,
  timeEndScreenDismiss: 0.35,

  // ── Recovery / general_config.toml + time_tresholds.toml ────
  watchdogEnabled: false,
  watchdogTimeoutS: 120,
  watchdogPollS: 30,
  maxReconnectsPerWindow: 3,
  reconnectWindowS: 300,
  // emulator paths/profile (general_config)
  emulatorAutorestart: true,
  emulatorProfileIndex: 'auto',
  emulatorLaunchCommand: '',
  mumuManagerPath: '',
  ldplayerConsolePath: '',
  // watchdog timing (time_tresholds)
  visualFreezeCheckInterval: 1.0,
  visualFreezeRestart: 45,
  visualFreezeDiffThreshold: 0.35,
  lobbyStartRetry: 8,
  lobbyStuckRestart: 120,
  lowIpsRecoveryThreshold: 4.0,
  lowIpsStartupGraceSeconds: 120,
  lowIpsMatchGraceSeconds: 20,
  lowIpsRecoverySeconds: 60,
  lowIpsRecoveryCooldown: 45,
  lowIpsAppRestartAfter: 3,
  lowIpsEmulatorRestartAfter: 6,
  foregroundFailureRestartThreshold: 4,
  emulatorRestartCooldown: 180,

  // ── Discord / webhook_config.toml + general_config.toml ─────
  webhookUrl: '',
  discordId: '',
  discordUsername: 'PylaAI',
  discordNotifyOnError: false,
  discordMilestoneWins: 0,
  discordMilestoneGames: 0,
  discordSendMatchSummary: false,
  discordIncludeScreenshot: true,
  discordPingWhenStuck: false,
  discordPingWhenTargetReached: false,
  discordPingEveryXMatch: 0,
  discordPingEveryXMinutes: 0,

  // ── Brawl Stars API / brawl_stars_api.toml ──────────────────
  bsapiToken: '',
  bsapiTag: '',
  bsapiTimeout: 15,
  bsapiAutoRefresh: false,
  bsapiEmail: '',
  bsapiPassword: '',
  bsapiDeleteAll: false,

  // ── Debug / general_config.toml ─────────────────────────────
  visualDebug: false,
  superDebug: false,
  wallStuckDebug: false,
  terminalLogging: false,
  captureBadVisionFrames: false,
  badVisionCaptureInterval: 2.0,
  badVisionCaptureMax: 500,
  visualDebugScale: 0.6,
  visualDebugMaxFps: 10,
  visualDebugMaxBoxes: 120,
  ocrScaleDownFactor: 0.5,

  // ── Combat AI / bot_config.toml (v1.1.5+) ───────────────────
  currentPlaystyle: 'default.pyla',
  matchWarmupSeconds: 4.0,
  adaptiveBrainEnabled: true,
  adaptiveBrainWindow: 20,
  strafeWhileAttacking: true,
  strafeInterval: 1.6,
  strafeBlend: 0.55,
  leadShots: true,
  aimedAttacks: false,
  projectileSpeedPxS: 900.0,
};

Object.assign(window, { DEFAULT_SETTINGS });
