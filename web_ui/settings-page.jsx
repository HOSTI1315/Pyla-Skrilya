// PylaAI — Settings page
// Every control in this file round-trips through PylaAPI.putConfig / getConfig.
// No UI-only / localStorage-only settings here; if a field isn't in cfg/*.toml,
// it doesn't belong here.

const { useState: useStateSettings } = React;

// yes/no boolean shim — general_config.toml stores booleans as "yes" | "no"
// strings, bot_config.toml too. Accepts both real booleans and the legacy
// string form so re-reads after save don't get confused.
const toYesNo = (v) => (v ? 'yes' : 'no');
const fromYesNo = (v, fallback = false) => {
  if (typeof v === 'boolean') return v;
  if (typeof v === 'string') {
    const s = v.trim().toLowerCase();
    if (s === 'yes' || s === 'true' || s === '1') return true;
    if (s === 'no'  || s === 'false'|| s === '0') return false;
  }
  return fallback;
};
const num = (v, fallback) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

function SettingsPage() {
  const [s, setS] = useLocalState('pyla.settings', DEFAULT_SETTINGS);
  const [section, setSection] = useStateSettings('runtime');
  const [dirty, setDirty] = useStateSettings(false);
  const [saveState, setSaveState] = useStateSettings('');
  const [bsapiTest, setBsapiTest] = useStateSettings({ status:'', msg:'' });
  const [playstyles, setPlaystyles] = useStateSettings([]);
  const [perfProfiles, setPerfProfiles] = useStateSettings([]);
  const [perfApply, setPerfApply] = useStateSettings({ status:'', msg:'' });
  const [psBusy, setPsBusy] = useStateSettings({ status:'', msg:'' });
  const [psPreview, setPsPreview] = useStateSettings(null);  // { file, text, meta } | null
  const psFileRef = React.useRef(null);

  async function refreshPlaystyles() {
    try {
      const r = await window.PylaAPI.listPlaystyles();
      setPlaystyles(r.playstyles || []);
    } catch (_) { /* ignore */ }
  }

  async function onPickPlaystyleFile(e) {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.pyla')) {
      setPsBusy({ status:'fail', msg: t('settings.f.psUploadBadExt') });
      e.target.value = '';
      return;
    }
    const existing = (playstyles || []).find(p => p.file.toLowerCase() === f.name.toLowerCase());
    let overwrite = false;
    if (existing) {
      if (!window.confirm(t('settings.f.psOverwriteConfirm').replace('{name}', f.name))) {
        e.target.value = '';
        return;
      }
      overwrite = true;
    }
    setPsBusy({ status:'loading', msg: t('settings.f.psUploading') });
    try {
      const r = await window.PylaAPI.uploadPlaystyle(f, overwrite);
      await refreshPlaystyles();
      setPsBusy({ status:'ok', msg: t('settings.f.psUploadOk').replace('{name}', r.file || f.name) });
      // Auto-select the just-uploaded playstyle for convenience.
      upd('currentPlaystyle', r.file || f.name);
    } catch (err) {
      setPsBusy({ status:'fail', msg: t('settings.f.psUploadFail').replace('{err}', err.message || String(err)) });
    } finally {
      e.target.value = '';
    }
  }

  async function onDeletePlaystyle(file) {
    if (!file || file === 'default.pyla') return;
    if (!window.confirm(t('settings.f.psDeleteConfirm').replace('{name}', file))) return;
    setPsBusy({ status:'loading', msg: t('settings.f.psDeleting') });
    try {
      await window.PylaAPI.deletePlaystyle(file);
      await refreshPlaystyles();
      setPsBusy({ status:'ok', msg: t('settings.f.psDeleteOk').replace('{name}', file) });
      // If deleted entry was selected, fall back to default.
      if (s.currentPlaystyle === file) upd('currentPlaystyle', 'default.pyla');
    } catch (err) {
      setPsBusy({ status:'fail', msg: t('settings.f.psDeleteFail').replace('{err}', err.message || String(err)) });
    }
  }

  async function onPreviewPlaystyle(file) {
    setPsBusy({ status:'loading', msg: t('settings.f.psLoading') });
    try {
      const r = await window.PylaAPI.getPlaystyleSource(file);
      setPsPreview({ file: r.file, text: r.text, meta: r.meta || {} });
      setPsBusy({ status:'', msg:'' });
    } catch (err) {
      setPsBusy({ status:'fail', msg: t('settings.f.psPreviewFail').replace('{err}', err.message || String(err)) });
    }
  }

  // ── hydrate from backend ────────────────────────────────────────
  React.useEffect(() => {
    (async () => {
      try {
        const [general, bot, time, bsapi, webhook] = await Promise.all([
          window.PylaAPI.getConfig('general').catch(() => ({})),
          window.PylaAPI.getConfig('bot').catch(() => ({})),
          window.PylaAPI.getConfig('time').catch(() => ({})),
          window.PylaAPI.getConfig('brawl_stars_api').catch(() => ({})),
          window.PylaAPI.getConfig('webhook').catch(() => ({})),
        ]);
        setS(prev => ({
          ...prev,
          // runtime / general
          currentEmulator: general.current_emulator || prev.currentEmulator,
          emulatorPort: num(general.emulator_port, prev.emulatorPort),
          cpuOrGpu: general.cpu_or_gpu || prev.cpuOrGpu,
          directmlDeviceId: general.directml_device_id != null ? String(general.directml_device_id) : prev.directmlDeviceId,
          maxIps: num(general.max_ips, prev.maxIps),
          scrcpyMaxFps: num(general.scrcpy_max_fps, prev.scrcpyMaxFps),
          scrcpyMaxWidth: num(general.scrcpy_max_width, prev.scrcpyMaxWidth),
          scrcpyBitrate: num(general.scrcpy_bitrate, prev.scrcpyBitrate),
          onnxCpuThreads: general.onnx_cpu_threads != null ? String(general.onnx_cpu_threads) : prev.onnxCpuThreads,
          usedThreads: general.used_threads != null ? String(general.used_threads) : prev.usedThreads,
          runForMinutes: num(general.run_for_minutes, prev.runForMinutes),
          trophiesMultiplier: num(general.trophies_multiplier, prev.trophiesMultiplier),
          brawlStarsPackage: general.brawl_stars_package || prev.brawlStarsPackage,
          apiBaseUrl: general.api_base_url || prev.apiBaseUrl,
          longPressStarDrop: fromYesNo(general.long_press_star_drop, prev.longPressStarDrop),

          // vision / bot
          entityDetectionConfidence: num(bot.entity_detection_confidence, prev.entityDetectionConfidence),
          wallDetectionConfidence: num(bot.wall_detection_confidence, prev.wallDetectionConfidence),
          superPixelsMinimum: num(bot.super_pixels_minimum, prev.superPixelsMinimum),
          gadgetPixelsMinimum: num(bot.gadget_pixels_minimum, prev.gadgetPixelsMinimum),
          hyperchargePixelsMinimum: num(bot.hypercharge_pixels_minimum, prev.hyperchargePixelsMinimum),
          idlePixelsMinimum: num(bot.idle_pixels_minimum, prev.idlePixelsMinimum),

          // movement / bot
          minimumMovementDelay: num(bot.minimum_movement_delay, prev.minimumMovementDelay),
          attackCooldown: num(bot.attack_cooldown, prev.attackCooldown),
          gadgetCooldown: num(bot.gadget_cooldown, prev.gadgetCooldown),
          superCooldown: num(bot.super_cooldown, prev.superCooldown),
          unstuckMovementDelay: num(bot.unstuck_movement_delay, prev.unstuckMovementDelay),
          unstuckMovementHoldTime: num(bot.unstuck_movement_hold_time, prev.unstuckMovementHoldTime),
          wallStuckEnabled: fromYesNo(bot.wall_stuck_enabled, prev.wallStuckEnabled),
          wallStuckTimeout: num(bot.wall_stuck_timeout, prev.wallStuckTimeout),
          wallStuckIgnoreRadius: num(bot.wall_stuck_ignore_radius, prev.wallStuckIgnoreRadius),
          wallStuckMinWalls: num(bot.wall_stuck_min_walls, prev.wallStuckMinWalls),
          escapeRetreatDuration: num(bot.escape_retreat_duration, prev.escapeRetreatDuration),
          escapeArcDuration: num(bot.escape_arc_duration, prev.escapeArcDuration),
          escapeArcDegrees: num(bot.escape_arc_degrees, prev.escapeArcDegrees),

          // match / bot
          botUsesGadgets: fromYesNo(bot.bot_uses_gadgets, prev.botUsesGadgets),
          playAgainOnWin: fromYesNo(bot.play_again_on_win, prev.playAgainOnWin),
          trioGroupingEnabled: fromYesNo(bot.trio_grouping_enabled, prev.trioGroupingEnabled),
          teammateFollowMinDistance: num(bot.teammate_follow_min_distance, prev.teammateFollowMinDistance),
          teammateFollowMaxDistance: num(bot.teammate_follow_max_distance, prev.teammateFollowMaxDistance),
          teammateCombatRegroupDistance: num(bot.teammate_combat_regroup_distance, prev.teammateCombatRegroupDistance),
          teammateCombatBias: num(bot.teammate_combat_bias, prev.teammateCombatBias),
          secondsToHoldAttackAfterReachingMax: num(bot.seconds_to_hold_attack_after_reaching_max, prev.secondsToHoldAttackAfterReachingMax),

          // timing / time_tresholds
          timeStateCheck: num(time.state_check, prev.timeStateCheck),
          timeNoDetections: num(time.no_detections, prev.timeNoDetections),
          timeGameStart: num(time.game_start, prev.timeGameStart),
          timeIdle: num(time.idle, prev.timeIdle),
          timeGadget: num(time.gadget, prev.timeGadget),
          timeHypercharge: num(time.hypercharge, prev.timeHypercharge),
          timeSuper: num(time.super, prev.timeSuper),
          timeWallDetection: num(time.wall_detection, prev.timeWallDetection),
          timeNoDetectionProceed: num(time.no_detection_proceed, prev.timeNoDetectionProceed),
          timeCrashCheck: num(time.check_if_brawl_stars_crashed, prev.timeCrashCheck),
          timeEndScreenDismiss: num(time.end_screen_dismiss_delay, prev.timeEndScreenDismiss),

          // recovery
          watchdogEnabled: fromYesNo(general.watchdog_enabled, prev.watchdogEnabled),
          watchdogTimeoutS: num(general.watchdog_timeout_s, prev.watchdogTimeoutS),
          watchdogPollS: num(general.watchdog_poll_s, prev.watchdogPollS),
          maxReconnectsPerWindow: num(general.max_reconnects_per_window, prev.maxReconnectsPerWindow),
          reconnectWindowS: num(general.reconnect_window_s, prev.reconnectWindowS),
          // emulator (general)
          emulatorAutorestart: general.emulator_autorestart === true || general.emulator_autorestart === 'yes',
          emulatorProfileIndex: general.emulator_profile_index != null ? String(general.emulator_profile_index) : prev.emulatorProfileIndex,
          emulatorLaunchCommand: typeof general.emulator_launch_command === 'string' ? general.emulator_launch_command : prev.emulatorLaunchCommand,
          mumuManagerPath: typeof general.mumu_manager_path === 'string' ? general.mumu_manager_path : prev.mumuManagerPath,
          ldplayerConsolePath: typeof general.ldplayer_console_path === 'string' ? general.ldplayer_console_path : prev.ldplayerConsolePath,
          // watchdog timing (time)
          visualFreezeCheckInterval: num(time.visual_freeze_check_interval, prev.visualFreezeCheckInterval),
          visualFreezeRestart: num(time.visual_freeze_restart, prev.visualFreezeRestart),
          visualFreezeDiffThreshold: num(time.visual_freeze_diff_threshold, prev.visualFreezeDiffThreshold),
          lobbyStartRetry: num(time.lobby_start_retry, prev.lobbyStartRetry),
          lobbyStuckRestart: num(time.lobby_stuck_restart, prev.lobbyStuckRestart),
          lowIpsRecoveryThreshold: num(time.low_ips_recovery_threshold, prev.lowIpsRecoveryThreshold),
          lowIpsStartupGraceSeconds: num(time.low_ips_startup_grace_seconds, prev.lowIpsStartupGraceSeconds),
          lowIpsMatchGraceSeconds: num(time.low_ips_match_grace_seconds, prev.lowIpsMatchGraceSeconds),
          lowIpsRecoverySeconds: num(time.low_ips_recovery_seconds, prev.lowIpsRecoverySeconds),
          lowIpsRecoveryCooldown: num(time.low_ips_recovery_cooldown, prev.lowIpsRecoveryCooldown),
          lowIpsAppRestartAfter: num(time.low_ips_app_restart_after, prev.lowIpsAppRestartAfter),
          lowIpsEmulatorRestartAfter: num(time.low_ips_emulator_restart_after, prev.lowIpsEmulatorRestartAfter),
          foregroundFailureRestartThreshold: num(time.foreground_failure_restart_threshold, prev.foregroundFailureRestartThreshold),
          emulatorRestartCooldown: num(time.emulator_restart_cooldown, prev.emulatorRestartCooldown),

          // discord — webhook_config.toml is the new source of truth;
          // legacy fields in general_config remain as fallback for display only.
          webhookUrl: (typeof webhook.webhook_url === 'string' && webhook.webhook_url)
            ? webhook.webhook_url
            : (typeof general.personal_webhook === 'string' ? general.personal_webhook : prev.webhookUrl),
          discordId: (typeof webhook.discord_id === 'string' && webhook.discord_id)
            ? webhook.discord_id
            : (typeof general.discord_id === 'string' ? general.discord_id : prev.discordId),
          discordUsername: typeof webhook.username === 'string' ? webhook.username : prev.discordUsername,
          discordNotifyOnError: fromYesNo(general.discord_notify_on_error, prev.discordNotifyOnError),
          discordMilestoneWins: num(general.discord_milestone_wins_interval, 0),
          discordMilestoneGames: num(general.discord_milestone_games_interval, 0),
          discordSendMatchSummary: webhook.send_match_summary === true || webhook.send_match_summary === 'yes',
          discordIncludeScreenshot: webhook.include_screenshot === true || webhook.include_screenshot === 'yes',
          discordPingWhenStuck: webhook.ping_when_stuck === true || webhook.ping_when_stuck === 'yes',
          discordPingWhenTargetReached: webhook.ping_when_target_is_reached === true || webhook.ping_when_target_is_reached === 'yes',
          discordPingEveryXMatch: num(webhook.ping_every_x_match, 0),
          discordPingEveryXMinutes: num(webhook.ping_every_x_minutes, 0),

          // bsapi
          bsapiToken: typeof bsapi.api_token === 'string' ? bsapi.api_token : '',
          bsapiTag: typeof bsapi.player_tag === 'string' ? bsapi.player_tag : '',
          bsapiTimeout: num(bsapi.timeout_seconds, 15),
          bsapiAutoRefresh: bsapi.auto_refresh_token === true || bsapi.auto_refresh_token === 'yes',
          bsapiEmail: typeof bsapi.developer_email === 'string' ? bsapi.developer_email : '',
          bsapiPassword: typeof bsapi.developer_password === 'string' ? bsapi.developer_password : '',
          bsapiDeleteAll: bsapi.delete_all_tokens === true || bsapi.delete_all_tokens === 'yes',

          // combat AI / bot_config.toml (v1.1.5+)
          currentPlaystyle: typeof bot.current_playstyle === 'string' ? bot.current_playstyle : prev.currentPlaystyle,
          matchWarmupSeconds: num(bot.match_warmup_seconds, prev.matchWarmupSeconds),
          adaptiveBrainEnabled: fromYesNo(bot.adaptive_brain_enabled, prev.adaptiveBrainEnabled),
          adaptiveBrainWindow: num(bot.adaptive_brain_window, prev.adaptiveBrainWindow),
          strafeWhileAttacking: fromYesNo(bot.strafe_while_attacking, prev.strafeWhileAttacking),
          strafeInterval: num(bot.strafe_interval, prev.strafeInterval),
          strafeBlend: num(bot.strafe_blend, prev.strafeBlend),
          leadShots: fromYesNo(bot.lead_shots, prev.leadShots),
          aimedAttacks: fromYesNo(bot.aimed_attacks, prev.aimedAttacks),
          projectileSpeedPxS: num(bot.projectile_speed_px_s, prev.projectileSpeedPxS),

          // debug
          visualDebug: fromYesNo(general.visual_debug, prev.visualDebug),
          superDebug: fromYesNo(general.super_debug, prev.superDebug),
          wallStuckDebug: fromYesNo(general.wall_stuck_debug, prev.wallStuckDebug),
          terminalLogging: fromYesNo(general.terminal_logging, prev.terminalLogging),
          captureBadVisionFrames: fromYesNo(general.capture_bad_vision_frames, prev.captureBadVisionFrames),
          badVisionCaptureInterval: num(general.bad_vision_capture_interval, prev.badVisionCaptureInterval),
          badVisionCaptureMax: num(general.bad_vision_capture_max, prev.badVisionCaptureMax),
          visualDebugScale: num(general.visual_debug_scale, prev.visualDebugScale),
          visualDebugMaxFps: num(general.visual_debug_max_fps, prev.visualDebugMaxFps),
          visualDebugMaxBoxes: num(general.visual_debug_max_boxes, prev.visualDebugMaxBoxes),
          ocrScaleDownFactor: num(general.ocr_scale_down_factor, prev.ocrScaleDownFactor),
        }));
        setDirty(false);
      } catch (e) { /* leave defaults */ }
    })();
    // Load playstyles + perf profiles in parallel; failures keep the page usable.
    (async () => {
      try {
        const [ps, pp] = await Promise.all([
          window.PylaAPI.listPlaystyles().catch(() => ({ playstyles: [] })),
          window.PylaAPI.listPerfProfiles().catch(() => ({ profiles: [] })),
        ]);
        setPlaystyles(ps.playstyles || []);
        setPerfProfiles(pp.profiles || []);
      } catch (_) { /* ignore */ }
    })();
  }, []);

  const upd = (k, v) => { setS({...s, [k]: v}); setDirty(true); setSaveState(''); };

  async function onSave() {
    setSaveState('saving');
    try {
      const general = {
        current_emulator: String(s.currentEmulator || 'Others'),
        emulator_port: num(s.emulatorPort, 5555),
        cpu_or_gpu: String(s.cpuOrGpu || 'auto'),
        directml_device_id: String(s.directmlDeviceId || 'auto'),
        max_ips: num(s.maxIps, 24),
        scrcpy_max_fps: num(s.scrcpyMaxFps, 30),
        scrcpy_max_width: num(s.scrcpyMaxWidth, 1280),
        scrcpy_bitrate: num(s.scrcpyBitrate, 3000000),
        onnx_cpu_threads: /^\d+$/.test(String(s.onnxCpuThreads)) ? Number(s.onnxCpuThreads) : String(s.onnxCpuThreads || 'auto'),
        used_threads: /^\d+$/.test(String(s.usedThreads)) ? Number(s.usedThreads) : String(s.usedThreads || 'auto'),
        run_for_minutes: num(s.runForMinutes, 600),
        trophies_multiplier: num(s.trophiesMultiplier, 1),
        brawl_stars_package: String(s.brawlStarsPackage || 'com.supercell.brawlstars'),
        api_base_url: String(s.apiBaseUrl || 'default'),
        long_press_star_drop: toYesNo(s.longPressStarDrop),

        // recovery
        watchdog_enabled: toYesNo(s.watchdogEnabled),
        watchdog_timeout_s: num(s.watchdogTimeoutS, 120),
        watchdog_poll_s: num(s.watchdogPollS, 30),
        max_reconnects_per_window: num(s.maxReconnectsPerWindow, 3),
        reconnect_window_s: num(s.reconnectWindowS, 300),
        emulator_autorestart: !!s.emulatorAutorestart,
        emulator_profile_index: /^\d+$/.test(String(s.emulatorProfileIndex)) ? Number(s.emulatorProfileIndex) : String(s.emulatorProfileIndex || 'auto'),
        emulator_launch_command: String(s.emulatorLaunchCommand || ''),
        mumu_manager_path: String(s.mumuManagerPath || ''),
        ldplayer_console_path: String(s.ldplayerConsolePath || ''),

        // discord — keep legacy mirror so notify_user(general_config) still works
        personal_webhook: String(s.webhookUrl || ''),
        discord_id: String(s.discordId || ''),
        discord_notify_on_error: toYesNo(s.discordNotifyOnError),
        discord_milestone_wins_interval: num(s.discordMilestoneWins, 0),
        discord_milestone_games_interval: num(s.discordMilestoneGames, 0),

        // debug
        visual_debug: toYesNo(s.visualDebug),
        super_debug: toYesNo(s.superDebug),
        wall_stuck_debug: toYesNo(s.wallStuckDebug),
        terminal_logging: toYesNo(s.terminalLogging),
        capture_bad_vision_frames: toYesNo(s.captureBadVisionFrames),
        bad_vision_capture_interval: num(s.badVisionCaptureInterval, 2.0),
        bad_vision_capture_max: num(s.badVisionCaptureMax, 500),
        visual_debug_scale: num(s.visualDebugScale, 0.6),
        visual_debug_max_fps: num(s.visualDebugMaxFps, 10),
        visual_debug_max_boxes: num(s.visualDebugMaxBoxes, 120),
        ocr_scale_down_factor: num(s.ocrScaleDownFactor, 0.5),
      };

      const bot = {
        entity_detection_confidence: num(s.entityDetectionConfidence, 0.75),
        wall_detection_confidence: num(s.wallDetectionConfidence, 0.8),
        super_pixels_minimum: num(s.superPixelsMinimum, 2400),
        gadget_pixels_minimum: num(s.gadgetPixelsMinimum, 1300),
        hypercharge_pixels_minimum: num(s.hyperchargePixelsMinimum, 2000),
        idle_pixels_minimum: num(s.idlePixelsMinimum, 3000),

        minimum_movement_delay: num(s.minimumMovementDelay, 0.1),
        attack_cooldown: num(s.attackCooldown, 0.16),
        gadget_cooldown: num(s.gadgetCooldown, 1.0),
        super_cooldown: num(s.superCooldown, 1.0),
        unstuck_movement_delay: num(s.unstuckMovementDelay, 3.0),
        unstuck_movement_hold_time: num(s.unstuckMovementHoldTime, 1.2),
        wall_stuck_enabled: toYesNo(s.wallStuckEnabled),
        wall_stuck_timeout: num(s.wallStuckTimeout, 3.0),
        wall_stuck_ignore_radius: num(s.wallStuckIgnoreRadius, 150),
        wall_stuck_min_walls: num(s.wallStuckMinWalls, 3),
        escape_retreat_duration: num(s.escapeRetreatDuration, 0.4),
        escape_arc_duration: num(s.escapeArcDuration, 1.2),
        escape_arc_degrees: num(s.escapeArcDegrees, 135.0),

        bot_uses_gadgets: toYesNo(s.botUsesGadgets),
        play_again_on_win: toYesNo(s.playAgainOnWin),
        trio_grouping_enabled: toYesNo(s.trioGroupingEnabled),
        teammate_follow_min_distance: num(s.teammateFollowMinDistance, 180),
        teammate_follow_max_distance: num(s.teammateFollowMaxDistance, 520),
        teammate_combat_regroup_distance: num(s.teammateCombatRegroupDistance, 650),
        teammate_combat_bias: num(s.teammateCombatBias, 0.35),
        seconds_to_hold_attack_after_reaching_max: num(s.secondsToHoldAttackAfterReachingMax, 1.5),

        current_playstyle: String(s.currentPlaystyle || 'default.pyla'),
        match_warmup_seconds: num(s.matchWarmupSeconds, 4.0),
        adaptive_brain_enabled: toYesNo(s.adaptiveBrainEnabled),
        adaptive_brain_window: num(s.adaptiveBrainWindow, 20),
        strafe_while_attacking: toYesNo(s.strafeWhileAttacking),
        strafe_interval: num(s.strafeInterval, 1.6),
        strafe_blend: num(s.strafeBlend, 0.55),
        lead_shots: toYesNo(s.leadShots),
        aimed_attacks: toYesNo(s.aimedAttacks),
        projectile_speed_px_s: num(s.projectileSpeedPxS, 900.0),
      };

      const time = {
        state_check: num(s.timeStateCheck, 1.5),
        no_detections: num(s.timeNoDetections, 10),
        game_start: num(s.timeGameStart, 0),
        idle: num(s.timeIdle, 5),
        gadget: num(s.timeGadget, 0.1),
        hypercharge: num(s.timeHypercharge, 0.1),
        super: num(s.timeSuper, 0.1),
        wall_detection: num(s.timeWallDetection, 0.25),
        no_detection_proceed: num(s.timeNoDetectionProceed, 6.5),
        check_if_brawl_stars_crashed: num(s.timeCrashCheck, 10),
        end_screen_dismiss_delay: num(s.timeEndScreenDismiss, 0.35),
        visual_freeze_check_interval: num(s.visualFreezeCheckInterval, 1.0),
        visual_freeze_restart: num(s.visualFreezeRestart, 45),
        visual_freeze_diff_threshold: num(s.visualFreezeDiffThreshold, 0.35),
        lobby_start_retry: num(s.lobbyStartRetry, 8),
        lobby_stuck_restart: num(s.lobbyStuckRestart, 120),
        low_ips_recovery_threshold: num(s.lowIpsRecoveryThreshold, 4.0),
        low_ips_startup_grace_seconds: num(s.lowIpsStartupGraceSeconds, 120),
        low_ips_match_grace_seconds: num(s.lowIpsMatchGraceSeconds, 20),
        low_ips_recovery_seconds: num(s.lowIpsRecoverySeconds, 60),
        low_ips_recovery_cooldown: num(s.lowIpsRecoveryCooldown, 45),
        low_ips_app_restart_after: num(s.lowIpsAppRestartAfter, 3),
        low_ips_emulator_restart_after: num(s.lowIpsEmulatorRestartAfter, 6),
        foreground_failure_restart_threshold: num(s.foregroundFailureRestartThreshold, 4),
        emulator_restart_cooldown: num(s.emulatorRestartCooldown, 180),
      };

      const webhook = {
        webhook_url: String(s.webhookUrl || ''),
        discord_id: String(s.discordId || ''),
        username: String(s.discordUsername || 'PylaAI'),
        send_match_summary: !!s.discordSendMatchSummary,
        include_screenshot: !!s.discordIncludeScreenshot,
        ping_when_stuck: !!s.discordPingWhenStuck,
        ping_when_target_is_reached: !!s.discordPingWhenTargetReached,
        ping_every_x_match: num(s.discordPingEveryXMatch, 0),
        ping_every_x_minutes: num(s.discordPingEveryXMinutes, 0),
      };

      const bsapi = {
        api_token: String(s.bsapiToken || ''),
        player_tag: String(s.bsapiTag || ''),
        timeout_seconds: num(s.bsapiTimeout, 15),
        auto_refresh_token: !!s.bsapiAutoRefresh,
        developer_email: String(s.bsapiEmail || ''),
        developer_password: String(s.bsapiPassword || ''),
        delete_all_tokens: !!s.bsapiDeleteAll,
      };

      await Promise.all([
        window.PylaAPI.putConfig('general', general),
        window.PylaAPI.putConfig('bot', bot),
        window.PylaAPI.putConfig('time', time),
        window.PylaAPI.putConfig('brawl_stars_api', bsapi),
        window.PylaAPI.putConfig('webhook', webhook),
      ]);
      setDirty(false);
      setSaveState('saved');
      setTimeout(() => setSaveState(''), 1800);
    } catch (e) {
      setSaveState('fail');
    }
  }

  async function onTestBsapi() {
    setBsapiTest({ status: 'loading', msg: '' });
    try {
      const r = await window.PylaAPI.getBrawlStarsApiTrophies();
      const n = r && r.trophies ? Object.keys(r.trophies).length : 0;
      setBsapiTest({ status: 'ok', msg: t('settings.bsapiTestOk').replace('{n}', n) });
    } catch (e) {
      setBsapiTest({ status: 'fail', msg: t('settings.bsapiTestFail').replace('{err}', e.message || String(e)) });
    }
  }

  async function onApplyPerf(profileKey) {
    setPerfApply({ status: 'loading', msg: '' });
    try {
      const r = await window.PylaAPI.applyPerfProfile(profileKey);
      setPerfApply({
        status: 'ok',
        msg: t('settings.perfApplyOk').replace('{name}', r.profile || profileKey),
      });
      // Re-pull general+bot so the form reflects what the script just wrote.
      const [general, bot] = await Promise.all([
        window.PylaAPI.getConfig('general').catch(() => ({})),
        window.PylaAPI.getConfig('bot').catch(() => ({})),
      ]);
      setS(prev => ({
        ...prev,
        maxIps: num(general.max_ips, prev.maxIps),
        scrcpyMaxFps: num(general.scrcpy_max_fps, prev.scrcpyMaxFps),
        scrcpyMaxWidth: num(general.scrcpy_max_width, prev.scrcpyMaxWidth),
        scrcpyBitrate: num(general.scrcpy_bitrate, prev.scrcpyBitrate),
        onnxCpuThreads: general.onnx_cpu_threads != null ? String(general.onnx_cpu_threads) : prev.onnxCpuThreads,
        usedThreads: general.used_threads != null ? String(general.used_threads) : prev.usedThreads,
        cpuOrGpu: general.cpu_or_gpu || prev.cpuOrGpu,
        entityDetectionConfidence: num(bot.entity_detection_confidence, prev.entityDetectionConfidence),
      }));
      setDirty(false);
    } catch (e) {
      setPerfApply({
        status: 'fail',
        msg: t('settings.perfApplyFail').replace('{err}', e.message || String(e)),
      });
    }
  }

  const sections = [
    { id: 'runtime',  label: t('settings.runtime'),  ic: <Icon.bolt s={13}/> },
    { id: 'combat',   label: t('settings.combat'),   ic: <Icon.brawler s={13}/> },
    { id: 'vision',   label: t('settings.vision'),   ic: <Icon.eye s={13}/> },
    { id: 'movement', label: t('settings.movement'), ic: <Icon.shield s={13}/> },
    { id: 'match',    label: t('settings.match'),    ic: <Icon.brawler s={13}/> },
    { id: 'timing',   label: t('settings.timing'),   ic: <Icon.chart s={13}/> },
    { id: 'recovery', label: t('settings.recovery'), ic: <Icon.gear s={13}/> },
    { id: 'discord',  label: t('settings.discord'),  ic: <Icon.log s={13}/> },
    { id: 'bsapi',    label: t('settings.bsapi'),    ic: <Icon.trophy s={13}/> },
    { id: 'debug',    label: t('settings.debug'),    ic: <Icon.gear s={13}/> },
  ];

  return (
    <div className="settings-page">
      <aside className="settings-nav">
        {sections.map(sec => (
          <button key={sec.id} className="settings-nav-item" data-active={section===sec.id}
                  onClick={()=>setSection(sec.id)}>
            {sec.ic}<span>{sec.label}</span>
          </button>
        ))}
      </aside>

      <div className="settings-body">
        {section === 'runtime' && (
          <SettingsSection title={t('settings.runtimeTitle')} desc={t('settings.runtimeDesc')}>
            <Field label={t('settings.f.perfProfile')} hint={t('settings.f.perfProfileHint')}>
              <div className="perf-profile-row" style={{display:'flex', flexWrap:'wrap', gap:8, alignItems:'center'}}>
                {(perfProfiles.length ? perfProfiles : [{key:'balanced'},{key:'low_end'},{key:'quality'}]).map(p => (
                  <button key={p.key}
                          className="btn small"
                          disabled={perfApply.status === 'loading'}
                          onClick={() => onApplyPerf(p.key)}
                          title={p.description || ''}>
                    {t('settings.perf.' + p.key) || p.key}
                  </button>
                ))}
                {perfApply.msg && (
                  <span className="muted small"
                        style={{color: perfApply.status === 'fail' ? '#F87171'
                                     : perfApply.status === 'ok'   ? '#34D399' : undefined}}>
                    {perfApply.msg}
                  </span>
                )}
              </div>
            </Field>
            <Field label={t('settings.f.emulator')} hint={t('settings.f.emulatorHint')}>
              <select className="input" value={s.currentEmulator} onChange={e=>upd('currentEmulator', e.target.value)}>
                <option value="LDPlayer">LDPlayer</option>
                <option value="BlueStacks">BlueStacks</option>
                <option value="MEmu">MEmu</option>
                <option value="MuMu">MuMu</option>
                <option value="Others">Others</option>
              </select>
            </Field>
            <Field label={t('settings.f.emulatorPort')}>
              <input className="input small-input" type="number" min="1" max="65535"
                     value={s.emulatorPort} onChange={e=>upd('emulatorPort', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.device')} hint={t('settings.f.deviceHint')}>
              <select className="input" value={s.cpuOrGpu} onChange={e=>upd('cpuOrGpu', e.target.value)}>
                <option value="auto">auto</option>
                <option value="directml">directml</option>
                <option value="cuda">cuda</option>
                <option value="openvino">openvino</option>
                <option value="cpu">cpu</option>
              </select>
            </Field>
            <Field label={t('settings.f.directml')} hint={t('settings.f.directmlHint')}>
              <input className="input small-input" value={s.directmlDeviceId}
                     onChange={e=>upd('directmlDeviceId', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.onnxThreads')} hint={t('settings.f.onnxThreadsHint')}>
              <input className="input small-input" value={s.onnxCpuThreads}
                     onChange={e=>upd('onnxCpuThreads', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.usedThreads')} hint={t('settings.f.usedThreadsHint')}>
              <input className="input small-input" value={s.usedThreads}
                     onChange={e=>upd('usedThreads', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.maxIps')} hint={t('settings.f.maxIpsHint')}>
              <div className="slider-row">
                <input type="range" min="5" max="60" value={s.maxIps}
                       onChange={e=>upd('maxIps', +e.target.value)}/>
                <span className="num">{s.maxIps}</span>
              </div>
            </Field>
            <Field label={t('settings.f.scrcpyFps')} hint={t('settings.f.scrcpyFpsHint')}>
              <input className="input small-input" type="number" min="5" max="120"
                     value={s.scrcpyMaxFps} onChange={e=>upd('scrcpyMaxFps', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.scrcpyMaxWidth')} hint={t('settings.f.scrcpyMaxWidthHint')}>
              <div>
                <input className="input small-input" type="number" min="480" max="1920" step="80"
                       value={s.scrcpyMaxWidth} onChange={e=>upd('scrcpyMaxWidth', +e.target.value)}/>
                {(+s.scrcpyMaxWidth) < 1100 && (
                  <div className="muted small" style={{color:'#F87171', marginTop: 4}}>
                    {t('settings.f.scrcpyMaxWidthWarn')}
                  </div>
                )}
              </div>
            </Field>
            <Field label={t('settings.f.scrcpyBitrate')} hint={t('settings.f.scrcpyBitrateHint')}>
              <input className="input small-input" type="number" min="500000" max="20000000" step="500000"
                     value={s.scrcpyBitrate} onChange={e=>upd('scrcpyBitrate', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.runFor')} hint={t('settings.f.runForHint')}>
              <input className="input small-input" type="number" min="1" max="10000"
                     value={s.runForMinutes} onChange={e=>upd('runForMinutes', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.trophiesMult')} hint={t('settings.f.trophiesMultHint')}>
              <input className="input small-input" type="number" min="1" max="5"
                     value={s.trophiesMultiplier} onChange={e=>upd('trophiesMultiplier', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.longPressStar')} hint={t('settings.f.longPressStarHint')}>
              <Toggle on={s.longPressStarDrop} onChange={v=>upd('longPressStarDrop', v)}/>
            </Field>
            <Field label={t('settings.f.bsPackage')}>
              <input className="input" value={s.brawlStarsPackage}
                     onChange={e=>upd('brawlStarsPackage', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.apiBase')} hint={t('settings.f.apiBaseHint')}>
              <input className="input" value={s.apiBaseUrl} onChange={e=>upd('apiBaseUrl', e.target.value)}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'combat' && (
          <SettingsSection title={t('settings.combatTitle')} desc={t('settings.combatDesc')}>
            <Field label={t('settings.f.playstyle')} hint={t('settings.f.playstyleHint')}>
              <div style={{display:'flex', alignItems:'center', gap:6, flexWrap:'wrap'}}>
                <select className="input"
                        value={s.currentPlaystyle}
                        style={{flex:'1 1 200px'}}
                        onChange={e => upd('currentPlaystyle', e.target.value)}>
                  {(playstyles.length ? playstyles : [{file: s.currentPlaystyle, name: s.currentPlaystyle}]).map(p => (
                    <option key={p.file} value={p.file}>
                      {(p.name || p.file)}{p.is_default ? ' ★' : ''}
                    </option>
                  ))}
                </select>
                <button className="btn small ghost"
                        onClick={() => onPreviewPlaystyle(s.currentPlaystyle)}
                        disabled={!s.currentPlaystyle}
                        title={t('settings.f.psPreviewHint')}>
                  {t('settings.f.psPreview')}
                </button>
                <button className="btn small"
                        onClick={() => psFileRef.current && psFileRef.current.click()}
                        title={t('settings.f.psUploadHint')}>
                  {t('settings.f.psUpload')}
                </button>
                {(() => {
                  const p = playstyles.find(p => p.file === s.currentPlaystyle);
                  return (p && !p.is_default) ? (
                    <button className="btn small danger"
                            onClick={() => onDeletePlaystyle(s.currentPlaystyle)}
                            title={t('settings.f.psDeleteHint')}>
                      {t('settings.f.psDelete')}
                    </button>
                  ) : null;
                })()}
                <input ref={psFileRef} type="file" accept=".pyla,text/plain"
                       style={{display:'none'}}
                       onChange={onPickPlaystyleFile}/>
                <button className="btn small ghost"
                        onClick={refreshPlaystyles}
                        title={t('settings.f.psRefreshHint')}>
                  ↻
                </button>
              </div>
            </Field>
            {(() => {
              const p = playstyles.find(p => p.file === s.currentPlaystyle);
              if (!p) return null;
              return (
                <div className="muted small" style={{marginTop:-6, marginBottom:6}}>
                  {p.description && <span>{p.description}</span>}
                  {p.author && <span> · {t('settings.f.psAuthor')}: {p.author}</span>}
                  {p.version && <span> · v{p.version}</span>}
                  {p.header_error && <span style={{color:'#F87171'}}> · {p.header_error}</span>}
                </div>
              );
            })()}
            <div className="muted small" style={{color:'#FBBF24', marginTop:-2, marginBottom:8}}>
              ⚠ {t('settings.f.psWarning')}
            </div>
            {psBusy.msg && (
              <div className="muted small" style={{marginBottom:6,
                color: psBusy.status === 'fail' ? '#F87171'
                     : psBusy.status === 'ok'   ? '#34D399' : undefined}}>
                {psBusy.msg}
              </div>
            )}
            <Field label={t('settings.f.adaptiveBrain')} hint={t('settings.f.adaptiveBrainHint')}>
              <Toggle on={s.adaptiveBrainEnabled} onChange={v => upd('adaptiveBrainEnabled', v)}/>
            </Field>
            <Field label={t('settings.f.adaptiveBrainWindow')} hint={t('settings.f.adaptiveBrainWindowHint')}>
              <input className="input small-input" type="number" min="5" max="200"
                     value={s.adaptiveBrainWindow}
                     onChange={e => upd('adaptiveBrainWindow', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.strafe')} hint={t('settings.f.strafeHint')}>
              <Toggle on={s.strafeWhileAttacking} onChange={v => upd('strafeWhileAttacking', v)}/>
            </Field>
            <Field label={t('settings.f.strafeInterval')}>
              <input className="input small-input" type="number" step="0.1" min="0.2" max="10"
                     value={s.strafeInterval}
                     onChange={e => upd('strafeInterval', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.strafeBlend')} hint={t('settings.f.strafeBlendHint')}>
              <div className="slider-row">
                <input type="range" min="0" max="1" step="0.05"
                       value={s.strafeBlend}
                       onChange={e => upd('strafeBlend', +e.target.value)}/>
                <span className="num">{Number(s.strafeBlend).toFixed(2)}</span>
              </div>
            </Field>
            <Field label={t('settings.f.leadShots')} hint={t('settings.f.leadShotsHint')}>
              <Toggle on={s.leadShots} onChange={v => upd('leadShots', v)}/>
            </Field>
            <Field label={t('settings.f.aimedAttacks')} hint={t('settings.f.aimedAttacksHint')}>
              <Toggle on={s.aimedAttacks} onChange={v => upd('aimedAttacks', v)}/>
            </Field>
            <Field label={t('settings.f.projectileSpeed')} hint={t('settings.f.projectileSpeedHint')}>
              <input className="input small-input" type="number" min="100" max="3000" step="50"
                     value={s.projectileSpeedPxS}
                     onChange={e => upd('projectileSpeedPxS', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.matchWarmup')} hint={t('settings.f.matchWarmupHint')}>
              <input className="input small-input" type="number" min="0" max="30" step="0.5"
                     value={s.matchWarmupSeconds}
                     onChange={e => upd('matchWarmupSeconds', +e.target.value)}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'vision' && (
          <SettingsSection title={t('settings.visionTitle')} desc={t('settings.visionDesc')}>
            <Field label={t('settings.f.conf')} hint={t('settings.f.confHint')}>
              <div className="slider-row">
                <input type="range" min="0.3" max="0.95" step="0.01" value={s.entityDetectionConfidence}
                       onChange={e=>upd('entityDetectionConfidence', parseFloat(e.target.value))}/>
                <span className="num">{Number(s.entityDetectionConfidence).toFixed(2)}</span>
              </div>
            </Field>
            <Field label={t('settings.f.wallConf')} hint={t('settings.f.wallConfHint')}>
              <div className="slider-row">
                <input type="range" min="0.3" max="0.95" step="0.01" value={s.wallDetectionConfidence}
                       onChange={e=>upd('wallDetectionConfidence', parseFloat(e.target.value))}/>
                <span className="num">{Number(s.wallDetectionConfidence).toFixed(2)}</span>
              </div>
            </Field>
            <Field label={t('settings.f.superPx')} hint={t('settings.f.superPxHint')}>
              <input className="input small-input" type="number" min="0" step="50"
                     value={s.superPixelsMinimum} onChange={e=>upd('superPixelsMinimum', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.gadgetPx')} hint={t('settings.f.gadgetPxHint')}>
              <input className="input small-input" type="number" min="0" step="50"
                     value={s.gadgetPixelsMinimum} onChange={e=>upd('gadgetPixelsMinimum', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.hyperPx')} hint={t('settings.f.hyperPxHint')}>
              <input className="input small-input" type="number" min="0" step="50"
                     value={s.hyperchargePixelsMinimum} onChange={e=>upd('hyperchargePixelsMinimum', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.idlePx')} hint={t('settings.f.idlePxHint')}>
              <input className="input small-input" type="number" min="0" step="50"
                     value={s.idlePixelsMinimum} onChange={e=>upd('idlePixelsMinimum', +e.target.value)}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'movement' && (
          <SettingsSection title={t('settings.movementTitle')} desc={t('settings.movementDesc')}>
            <Field label={t('settings.f.minMovDelay')} hint={t('settings.f.minMovDelayHint')}>
              <input className="input small-input" type="number" step="0.01" min="0"
                     value={s.minimumMovementDelay} onChange={e=>upd('minimumMovementDelay', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.attackCd')}>
              <input className="input small-input" type="number" step="0.01" min="0"
                     value={s.attackCooldown} onChange={e=>upd('attackCooldown', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.gadgetCd')}>
              <input className="input small-input" type="number" step="0.05" min="0"
                     value={s.gadgetCooldown} onChange={e=>upd('gadgetCooldown', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.superCd')}>
              <input className="input small-input" type="number" step="0.05" min="0"
                     value={s.superCooldown} onChange={e=>upd('superCooldown', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.unstuckDelay')} hint={t('settings.f.unstuckDelayHint')}>
              <input className="input small-input" type="number" step="0.1" min="0"
                     value={s.unstuckMovementDelay} onChange={e=>upd('unstuckMovementDelay', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.unstuckHold')} hint={t('settings.f.unstuckHoldHint')}>
              <input className="input small-input" type="number" step="0.1" min="0"
                     value={s.unstuckMovementHoldTime} onChange={e=>upd('unstuckMovementHoldTime', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.wallStuck')} hint={t('settings.f.wallStuckHint')}>
              <Toggle on={s.wallStuckEnabled} onChange={v=>upd('wallStuckEnabled', v)}/>
            </Field>
            <Field label={t('settings.f.wallStuckTimeout')}>
              <input className="input small-input" type="number" step="0.1" min="0"
                     value={s.wallStuckTimeout} onChange={e=>upd('wallStuckTimeout', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.wallStuckRadius')} hint={t('settings.f.wallStuckRadiusHint')}>
              <input className="input small-input" type="number" min="0"
                     value={s.wallStuckIgnoreRadius} onChange={e=>upd('wallStuckIgnoreRadius', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.wallStuckMinWalls')}>
              <input className="input small-input" type="number" min="1" max="20"
                     value={s.wallStuckMinWalls} onChange={e=>upd('wallStuckMinWalls', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.escapeRetreat')}>
              <input className="input small-input" type="number" step="0.05" min="0"
                     value={s.escapeRetreatDuration} onChange={e=>upd('escapeRetreatDuration', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.escapeArcDur')}>
              <input className="input small-input" type="number" step="0.05" min="0"
                     value={s.escapeArcDuration} onChange={e=>upd('escapeArcDuration', parseFloat(e.target.value))}/>
            </Field>
            <Field label={t('settings.f.escapeArcDeg')} hint={t('settings.f.escapeArcDegHint')}>
              <input className="input small-input" type="number" step="1" min="0" max="360"
                     value={s.escapeArcDegrees} onChange={e=>upd('escapeArcDegrees', parseFloat(e.target.value))}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'match' && (
          <SettingsSection title={t('settings.matchTitle')} desc={t('settings.matchDesc')}>
            <Field label={t('settings.f.useGadgets')} hint={t('settings.f.useGadgetsHint')}>
              <Toggle on={s.botUsesGadgets} onChange={v=>upd('botUsesGadgets', v)}/>
            </Field>
            <Field label={t('settings.f.playAgain')} hint={t('settings.f.playAgainHint')}>
              <Toggle on={s.playAgainOnWin} onChange={v=>upd('playAgainOnWin', v)}/>
            </Field>
            <Field label={t('settings.f.trioGroup')} hint={t('settings.f.trioGroupHint')}>
              <Toggle on={s.trioGroupingEnabled} onChange={v=>upd('trioGroupingEnabled', v)}/>
            </Field>
            <Field label={t('settings.f.followMin')} hint={t('settings.f.followMinHint')}>
              <input className="input small-input" type="number" min="0"
                     value={s.teammateFollowMinDistance} onChange={e=>upd('teammateFollowMinDistance', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.followMax')}>
              <input className="input small-input" type="number" min="0"
                     value={s.teammateFollowMaxDistance} onChange={e=>upd('teammateFollowMaxDistance', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.combatRegroup')} hint={t('settings.f.combatRegroupHint')}>
              <input className="input small-input" type="number" min="0"
                     value={s.teammateCombatRegroupDistance} onChange={e=>upd('teammateCombatRegroupDistance', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.combatBias')} hint={t('settings.f.combatBiasHint')}>
              <div className="slider-row">
                <input type="range" min="0" max="1" step="0.05" value={s.teammateCombatBias}
                       onChange={e=>upd('teammateCombatBias', parseFloat(e.target.value))}/>
                <span className="num">{Number(s.teammateCombatBias).toFixed(2)}</span>
              </div>
            </Field>
            <Field label={t('settings.f.holdAttack')} hint={t('settings.f.holdAttackHint')}>
              <input className="input small-input" type="number" step="0.1" min="0"
                     value={s.secondsToHoldAttackAfterReachingMax}
                     onChange={e=>upd('secondsToHoldAttackAfterReachingMax', parseFloat(e.target.value))}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'timing' && (
          <SettingsSection title={t('settings.timingTitle')} desc={t('settings.timingDesc')}>
            <TimingField k="timeStateCheck"           s={s} upd={upd} min="0.1" max="10"  step="0.1"/>
            <TimingField k="timeNoDetections"         s={s} upd={upd} min="1"   max="60"  step="1"/>
            <TimingField k="timeGameStart"            s={s} upd={upd} min="0"   max="10"  step="0.1"/>
            <TimingField k="timeIdle"                 s={s} upd={upd} min="1"   max="60"  step="1"/>
            <TimingField k="timeGadget"               s={s} upd={upd} min="0.05" max="5"   step="0.05"/>
            <TimingField k="timeHypercharge"          s={s} upd={upd} min="0.05" max="5"   step="0.05"/>
            <TimingField k="timeSuper"                s={s} upd={upd} min="0.05" max="5"   step="0.05"/>
            <TimingField k="timeWallDetection"        s={s} upd={upd} min="0.05" max="5"   step="0.05"/>
            <TimingField k="timeNoDetectionProceed"   s={s} upd={upd} min="1"   max="30"  step="0.5"/>
            <TimingField k="timeCrashCheck"           s={s} upd={upd} min="1"   max="120" step="1"/>
            <TimingField k="timeEndScreenDismiss"     s={s} upd={upd} min="0.05" max="5"   step="0.05"/>
          </SettingsSection>
        )}

        {section === 'recovery' && (
          <SettingsSection title={t('settings.recoveryTitle')} desc={t('settings.recoveryDesc')}>
            <Field label={t('settings.f.wdEnabled')} hint={t('settings.f.wdEnabledHint')}>
              <Toggle on={s.watchdogEnabled} onChange={v=>upd('watchdogEnabled', v)}/>
            </Field>
            <Field label={t('settings.f.wdTimeout')} hint={t('settings.f.wdTimeoutHint')}>
              <div className="slider-row">
                <input type="range" min="30" max="600" step="10" value={s.watchdogTimeoutS}
                       onChange={e=>upd('watchdogTimeoutS', +e.target.value)}/>
                <span className="num">{s.watchdogTimeoutS}s</span>
              </div>
            </Field>
            <Field label={t('settings.f.wdPoll')} hint={t('settings.f.wdPollHint')}>
              <div className="slider-row">
                <input type="range" min="5" max="300" step="5" value={s.watchdogPollS}
                       onChange={e=>upd('watchdogPollS', +e.target.value)}/>
                <span className="num">{s.watchdogPollS}s</span>
              </div>
            </Field>
            <Field label={t('settings.f.wdMaxReconn')}>
              <input className="input small-input" type="number" min="0" max="20"
                     value={s.maxReconnectsPerWindow}
                     onChange={e=>upd('maxReconnectsPerWindow', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.wdWindow')} hint={t('settings.f.wdWindowHint')}>
              <div className="slider-row">
                <input type="range" min="60" max="1800" step="30" value={s.reconnectWindowS}
                       onChange={e=>upd('reconnectWindowS', +e.target.value)}/>
                <span className="num">{s.reconnectWindowS}s</span>
              </div>
            </Field>

            <h3 className="section-subhead">{t('settings.subhead.emulator')}</h3>
            <Field label={t('settings.f.emuAutorestart')} hint={t('settings.f.emuAutorestartHint')}>
              <Toggle on={s.emulatorAutorestart} onChange={v=>upd('emulatorAutorestart', v)}/>
            </Field>
            <Field label={t('settings.f.emuProfileIndex')} hint={t('settings.f.emuProfileIndexHint')}>
              <input className="input small-input" value={s.emulatorProfileIndex}
                     onChange={e=>upd('emulatorProfileIndex', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.emuLaunchCmd')} hint={t('settings.f.emuLaunchCmdHint')}>
              <input className="input" value={s.emulatorLaunchCommand}
                     placeholder='"C:\\path\\to\\Player.exe" --instance 0'
                     onChange={e=>upd('emulatorLaunchCommand', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.mumuPath')}>
              <input className="input" value={s.mumuManagerPath}
                     placeholder="C:\\Program Files\\Netease\\MuMuPlayer-12.0\\shell\\MuMuManager.exe"
                     onChange={e=>upd('mumuManagerPath', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.ldconsolePath')}>
              <input className="input" value={s.ldplayerConsolePath}
                     placeholder="C:\\LDPlayer\\LDPlayer9\\ldconsole.exe"
                     onChange={e=>upd('ldplayerConsolePath', e.target.value)}/>
            </Field>

            <h3 className="section-subhead">{t('settings.subhead.visualFreeze')}</h3>
            <Field label={t('settings.f.visualFreezeRestart')} hint={t('settings.f.visualFreezeRestartHint')}>
              <input className="input small-input" type="number" min="5" max="600" step="1"
                     value={s.visualFreezeRestart}
                     onChange={e=>upd('visualFreezeRestart', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.visualFreezeCheck')}>
              <input className="input small-input" type="number" min="0.2" max="10" step="0.1"
                     value={s.visualFreezeCheckInterval}
                     onChange={e=>upd('visualFreezeCheckInterval', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.visualFreezeDiff')} hint={t('settings.f.visualFreezeDiffHint')}>
              <input className="input small-input" type="number" min="0.05" max="2" step="0.05"
                     value={s.visualFreezeDiffThreshold}
                     onChange={e=>upd('visualFreezeDiffThreshold', +e.target.value)}/>
            </Field>

            <h3 className="section-subhead">{t('settings.subhead.lobbyWatchdog')}</h3>
            <Field label={t('settings.f.lobbyStartRetry')} hint={t('settings.f.lobbyStartRetryHint')}>
              <input className="input small-input" type="number" min="2" max="120" step="1"
                     value={s.lobbyStartRetry}
                     onChange={e=>upd('lobbyStartRetry', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lobbyStuckRestart')} hint={t('settings.f.lobbyStuckRestartHint')}>
              <input className="input small-input" type="number" min="30" max="900" step="10"
                     value={s.lobbyStuckRestart}
                     onChange={e=>upd('lobbyStuckRestart', +e.target.value)}/>
            </Field>

            <h3 className="section-subhead">{t('settings.subhead.lowIps')}</h3>
            <Field label={t('settings.f.lowIpsThreshold')} hint={t('settings.f.lowIpsThresholdHint')}>
              <input className="input small-input" type="number" min="0.5" max="30" step="0.5"
                     value={s.lowIpsRecoveryThreshold}
                     onChange={e=>upd('lowIpsRecoveryThreshold', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lowIpsStartupGrace')}>
              <input className="input small-input" type="number" min="10" max="600" step="10"
                     value={s.lowIpsStartupGraceSeconds}
                     onChange={e=>upd('lowIpsStartupGraceSeconds', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lowIpsMatchGrace')}>
              <input className="input small-input" type="number" min="0" max="300" step="5"
                     value={s.lowIpsMatchGraceSeconds}
                     onChange={e=>upd('lowIpsMatchGraceSeconds', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lowIpsRecovery')} hint={t('settings.f.lowIpsRecoveryHint')}>
              <input className="input small-input" type="number" min="10" max="600" step="5"
                     value={s.lowIpsRecoverySeconds}
                     onChange={e=>upd('lowIpsRecoverySeconds', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lowIpsCooldown')}>
              <input className="input small-input" type="number" min="5" max="600" step="5"
                     value={s.lowIpsRecoveryCooldown}
                     onChange={e=>upd('lowIpsRecoveryCooldown', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lowIpsAppRestart')} hint={t('settings.f.lowIpsAppRestartHint')}>
              <input className="input small-input" type="number" min="1" max="10" step="1"
                     value={s.lowIpsAppRestartAfter}
                     onChange={e=>upd('lowIpsAppRestartAfter', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.lowIpsEmuRestart')} hint={t('settings.f.lowIpsEmuRestartHint')}>
              <input className="input small-input" type="number" min="1" max="20" step="1"
                     value={s.lowIpsEmulatorRestartAfter}
                     onChange={e=>upd('lowIpsEmulatorRestartAfter', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.foregroundFail')} hint={t('settings.f.foregroundFailHint')}>
              <input className="input small-input" type="number" min="1" max="20" step="1"
                     value={s.foregroundFailureRestartThreshold}
                     onChange={e=>upd('foregroundFailureRestartThreshold', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.emuRestartCooldown')}>
              <input className="input small-input" type="number" min="30" max="1800" step="10"
                     value={s.emulatorRestartCooldown}
                     onChange={e=>upd('emulatorRestartCooldown', +e.target.value)}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'discord' && (
          <SettingsSection title={t('settings.discordTitle')} desc={t('settings.discordDesc')}>
            <Field label={t('settings.f.webhook')} hint={t('settings.f.webhookHint')}>
              <input className="input" type="password" value={s.webhookUrl}
                     placeholder="https://discord.com/api/webhooks/..."
                     onChange={e=>upd('webhookUrl', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.discordId')} hint={t('settings.f.discordIdHint')}>
              <input className="input" value={s.discordId}
                     placeholder="123456789012345678"
                     onChange={e=>upd('discordId', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.discordUsername')}>
              <input className="input" value={s.discordUsername}
                     placeholder="PylaAI"
                     onChange={e=>upd('discordUsername', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.notifyErr')}>
              <Toggle on={s.discordNotifyOnError} onChange={v=>upd('discordNotifyOnError', v)}/>
            </Field>
            <Field label={t('settings.f.sendMatchSummary')} hint={t('settings.f.sendMatchSummaryHint')}>
              <Toggle on={s.discordSendMatchSummary} onChange={v=>upd('discordSendMatchSummary', v)}/>
            </Field>
            <Field label={t('settings.f.includeScreenshot')} hint={t('settings.f.includeScreenshotHint')}>
              <Toggle on={s.discordIncludeScreenshot} onChange={v=>upd('discordIncludeScreenshot', v)}/>
            </Field>
            <Field label={t('settings.f.pingWhenStuck')} hint={t('settings.f.pingWhenStuckHint')}>
              <Toggle on={s.discordPingWhenStuck} onChange={v=>upd('discordPingWhenStuck', v)}/>
            </Field>
            <Field label={t('settings.f.pingWhenTarget')} hint={t('settings.f.pingWhenTargetHint')}>
              <Toggle on={s.discordPingWhenTargetReached} onChange={v=>upd('discordPingWhenTargetReached', v)}/>
            </Field>
            <Field label={t('settings.f.pingEveryMatches')} hint={t('settings.f.pingEveryMatchesHint')}>
              <input className="input small-input" type="number" min="0" max="500"
                     value={s.discordPingEveryXMatch}
                     onChange={e=>upd('discordPingEveryXMatch', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.pingEveryMinutes')} hint={t('settings.f.pingEveryMinutesHint')}>
              <input className="input small-input" type="number" min="0" max="1440"
                     value={s.discordPingEveryXMinutes}
                     onChange={e=>upd('discordPingEveryXMinutes', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.msWins')} hint={t('settings.f.msWinsHint')}>
              <input className="input small-input" type="number" min="0" max="500"
                     value={s.discordMilestoneWins}
                     onChange={e=>upd('discordMilestoneWins', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.msGames')} hint={t('settings.f.msGamesHint')}>
              <input className="input small-input" type="number" min="0" max="500"
                     value={s.discordMilestoneGames}
                     onChange={e=>upd('discordMilestoneGames', +e.target.value)}/>
            </Field>
          </SettingsSection>
        )}

        {section === 'bsapi' && (
          <SettingsSection title={t('settings.bsapiTitle')} desc={t('settings.bsapiDesc')}>
            <Field label={t('settings.f.bsapiToken')} hint={t('settings.f.bsapiTokenHint')}>
              <input className="input" type="password" value={s.bsapiToken || ''}
                     placeholder="eyJ0eXAiOiJKV1QiLCJhbGciOi..."
                     onChange={e=>upd('bsapiToken', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.bsapiTag')} hint={t('settings.f.bsapiTagHint')}>
              <input className="input" value={s.bsapiTag || ''}
                     placeholder="#YOURTAG"
                     onChange={e=>upd('bsapiTag', e.target.value)}/>
            </Field>
            <Field label={t('settings.f.bsapiTimeout')}>
              <input className="input small-input" type="number" min="1" max="120"
                     value={s.bsapiTimeout || 15}
                     onChange={e=>upd('bsapiTimeout', +e.target.value)}/>
            </Field>
            <Field label={t('settings.f.bsapiAutoRefresh')} hint={t('settings.f.bsapiAutoRefreshHint')}>
              <Toggle on={!!s.bsapiAutoRefresh} onChange={v=>upd('bsapiAutoRefresh', v)}/>
            </Field>
            {s.bsapiAutoRefresh && <>
              <Field label={t('settings.f.bsapiEmail')}>
                <input className="input" type="email" value={s.bsapiEmail || ''}
                       onChange={e=>upd('bsapiEmail', e.target.value)}/>
              </Field>
              <Field label={t('settings.f.bsapiPassword')} hint={t('settings.f.bsapiPasswordHint')}>
                <input className="input" type="password" value={s.bsapiPassword || ''}
                       onChange={e=>upd('bsapiPassword', e.target.value)}/>
              </Field>
              <Field label={t('settings.f.bsapiDeleteAll')} hint={t('settings.f.bsapiDeleteAllHint')}>
                <Toggle on={!!s.bsapiDeleteAll} onChange={v=>upd('bsapiDeleteAll', v)}/>
              </Field>
            </>}
            <div className="field">
              <div className="field-left"/>
              <div className="field-right row-gap" style={{alignItems:'center'}}>
                <button className="btn ghost xs" onClick={onTestBsapi}
                        disabled={bsapiTest.status === 'loading'}>
                  {bsapiTest.status === 'loading' ? t('settings.bsapiTesting') : t('settings.bsapiTest')}
                </button>
                {bsapiTest.msg && (
                  <span className="muted small"
                        style={{color: bsapiTest.status === 'fail' ? 'var(--err, #F87171)'
                                     : bsapiTest.status === 'ok'   ? 'var(--ok, #34D399)' : undefined}}>
                    {bsapiTest.msg}
                  </span>
                )}
              </div>
            </div>
          </SettingsSection>
        )}

        {section === 'debug' && (
          <SettingsSection title={t('settings.debugTitle')} desc={t('settings.debugDesc')}>
            <Field label={t('settings.f.visualDebug')} hint={t('settings.f.visualDebugHint')}>
              <Toggle on={s.visualDebug} onChange={v=>upd('visualDebug', v)}/>
            </Field>
            <Field label={t('settings.f.superDebug')} hint={t('settings.f.superDebugHint')}>
              <Toggle on={s.superDebug} onChange={v=>upd('superDebug', v)}/>
            </Field>
            <Field label={t('settings.f.wallStuckDebug')}>
              <Toggle on={s.wallStuckDebug} onChange={v=>upd('wallStuckDebug', v)}/>
            </Field>
            <Field label={t('settings.f.terminalLogging')} hint={t('settings.f.terminalLoggingHint')}>
              <Toggle on={s.terminalLogging} onChange={v=>upd('terminalLogging', v)}/>
            </Field>
            <Field label={t('settings.f.captureFrames')} hint={t('settings.f.captureFramesHint')}>
              <Toggle on={s.captureBadVisionFrames} onChange={v=>upd('captureBadVisionFrames', v)}/>
            </Field>
            {s.captureBadVisionFrames && <>
              <Field label={t('settings.f.captureInterval')}>
                <input className="input small-input" type="number" step="0.5" min="0.5"
                       value={s.badVisionCaptureInterval}
                       onChange={e=>upd('badVisionCaptureInterval', parseFloat(e.target.value))}/>
              </Field>
              <Field label={t('settings.f.captureMax')}>
                <input className="input small-input" type="number" step="50" min="10"
                       value={s.badVisionCaptureMax}
                       onChange={e=>upd('badVisionCaptureMax', +e.target.value)}/>
              </Field>
            </>}
            {s.visualDebug && <>
              <Field label={t('settings.f.visualDebugScale')} hint={t('settings.f.visualDebugScaleHint')}>
                <input className="input small-input" type="number" step="0.05" min="0.2" max="1"
                       value={s.visualDebugScale}
                       onChange={e=>upd('visualDebugScale', parseFloat(e.target.value))}/>
              </Field>
              <Field label={t('settings.f.visualDebugMaxFps')}>
                <input className="input small-input" type="number" step="1" min="1" max="60"
                       value={s.visualDebugMaxFps}
                       onChange={e=>upd('visualDebugMaxFps', +e.target.value)}/>
              </Field>
              <Field label={t('settings.f.visualDebugMaxBoxes')} hint={t('settings.f.visualDebugMaxBoxesHint')}>
                <input className="input small-input" type="number" step="10" min="10" max="500"
                       value={s.visualDebugMaxBoxes}
                       onChange={e=>upd('visualDebugMaxBoxes', +e.target.value)}/>
              </Field>
            </>}
            <Field label={t('settings.f.ocrScale')} hint={t('settings.f.ocrScaleHint')}>
              <input className="input small-input" type="number" step="0.05" min="0.2" max="1"
                     value={s.ocrScaleDownFactor}
                     onChange={e=>upd('ocrScaleDownFactor', parseFloat(e.target.value))}/>
            </Field>
            <div className="danger-zone">
              <div>
                <b>{t('settings.resetAll')}</b>
                <div className="muted small">{t('settings.resetHint')}</div>
              </div>
              <button className="btn danger" onClick={()=>{setS(DEFAULT_SETTINGS);setDirty(true);}}>
                {t('common.reset')}
              </button>
            </div>
          </SettingsSection>
        )}

        {(dirty || saveState) && (
          <div className="settings-save-bar">
            <span>
              {saveState === 'saving' ? t('settings.saving')
               : saveState === 'saved'  ? t('settings.saved')
               : saveState === 'fail'   ? t('settings.saveFail')
               : t('common.unsaved')}
            </span>
            <div className="row-gap">
              <button className="btn ghost" onClick={()=>{setS(DEFAULT_SETTINGS);setDirty(false);setSaveState('');}}>
                {t('common.discard')}
              </button>
              <button className="btn primary" onClick={onSave}>{t('common.save')}</button>
            </div>
          </div>
        )}
      </div>

      {psPreview && (
        <div className="modal-backdrop"
             style={{position:'fixed', inset:0, background:'rgba(0,0,0,0.6)', zIndex:1000,
                     display:'flex', alignItems:'center', justifyContent:'center'}}
             onClick={() => setPsPreview(null)}>
          <div className="modal-card"
               style={{background:'#1c1c1c', border:'1px solid #333', borderRadius:8,
                       width:'min(900px, 92vw)', maxHeight:'85vh', display:'flex', flexDirection:'column'}}
               onClick={e => e.stopPropagation()}>
            <div style={{padding:'14px 16px', borderBottom:'1px solid #333', display:'flex',
                         alignItems:'center', justifyContent:'space-between'}}>
              <div>
                <b style={{fontSize:15}}>{psPreview.meta?.name || psPreview.file}</b>
                {psPreview.meta?.author && <span className="muted small"> · {psPreview.meta.author}</span>}
                <div className="muted small" style={{marginTop:2}}>
                  {psPreview.file} · {psPreview.text.length} {t('settings.f.psBytes')}
                </div>
              </div>
              <button className="btn small ghost" onClick={() => setPsPreview(null)}>
                {t('common.close') || '✕'}
              </button>
            </div>
            <pre style={{margin:0, padding:'12px 16px', overflow:'auto', flex:1, fontSize:12,
                         lineHeight:1.45, fontFamily:'Consolas, "Courier New", monospace',
                         color:'#e0e0e0', background:'#101010'}}>
              {psPreview.text}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

// Shared field for the Timing section — all 11 keys use the same slider layout,
// so extracting avoids 11 copy-pasted blocks.
function TimingField({ k, s, upd, min, max, step }) {
  const label = t(`settings.f.${k}`);
  const hint  = t(`settings.f.${k}Hint`);
  const val   = Number(s[k]) || 0;
  return (
    <Field label={label} hint={hint && hint !== `settings.f.${k}Hint` ? hint : undefined}>
      <div className="slider-row">
        <input type="range" min={min} max={max} step={step} value={val}
               onChange={e=>upd(k, parseFloat(e.target.value))}/>
        <span className="num">{val}s</span>
      </div>
    </Field>
  );
}

function SettingsSection({ title, desc, children }) {
  return (
    <div className="settings-section">
      <div className="settings-section-head">
        <h2>{title}</h2>
        <p className="muted">{desc}</p>
      </div>
      <div className="settings-fields">{children}</div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div className="field">
      <div className="field-left">
        <div className="field-label">{label}</div>
        {hint && <div className="field-hint muted">{hint}</div>}
      </div>
      <div className="field-right">{children}</div>
    </div>
  );
}

function Toggle({ on, onChange }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={on} onChange={e=>onChange(e.target.checked)}/>
      <span className="switch-track"><span className="switch-dot"/></span>
    </label>
  );
}

Object.assign(window, { SettingsPage });
