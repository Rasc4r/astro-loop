#!/usr/bin/env python3
"""Apply an experimental autopilot to a locally downloaded PubDeer/astro-loop checkout.

No network access needed by this script. Fails closed if expected source anchors differ.
"""
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd()
HERE = Path(__file__).resolve().parent
GAME = ROOT / 'app/src/main/java/com/astroloop/game/core/GameSurfaceView.kt'
GRADLE = ROOT / 'app/build.gradle.kts'
TARGET = ROOT / 'app/src/main/java/com/astroloop/game/core/AutoPilot.kt'
STRINGS = ROOT / 'app/src/main/res/values/strings.xml'


def replace_once(src, old, new, label):
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f'Expected exactly one {label} anchor, found {count}; source revision may differ.')
    return src.replace(old, new, 1)


def main():
    if not GAME.exists() or not GRADLE.exists() or not (ROOT / 'gradlew.bat').exists():
        raise SystemExit('Pass the ROOT of the unmodified astro-loop source checkout.')
    data = GAME.read_text(encoding='utf-8')
    gradle = GRADLE.read_text(encoding='utf-8')
    if 'AutoPilot SourceKit' in data or TARGET.exists():
        raise SystemExit('Already patched. Use a fresh original repo checkout.')

    data = replace_once(data,
        '    private val touchController = TouchController()\n',
        '''    private val touchController = TouchController()
    // AutoPilot SourceKit: opt-in. All game physics and normal touch input remain intact.
    private val autonomousPilot = AutoPilot()
    @Volatile private var autonomousMode = false
    private var autoButtonPressed = false
    private val autoBadgePaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private fun autoButton(): android.graphics.RectF {
        val r = layout.safe
        return android.graphics.RectF(r.right - 194f, r.top + 10f, r.right - 12f, r.top + 73f)
    }
''', 'field insertion')

    data = replace_once(data,
        '''                ship.moveDirection.set(touchController.moveDirection)
                ship.moveDirection.mul(touchController.moveMagnitude)
''',
        '''                if (autonomousMode) {
                    // Fresh world-state snapshot, not a screenshot (run thread owns these lists).
                    EntityPools.asteroids.getActiveEntities(activeAsteroids)
                    EntityPools.projectiles.getActiveEntities(activeProjectiles)
                    EntityPools.enemies.getActiveEntities(activeEnemies)
                    EntityPools.powerUps.getActiveEntities(activePowerUps)
                    autonomousPilot.steer(ship, activeAsteroids, activeProjectiles, activeEnemies, activePowerUps)
                } else {
                    ship.moveDirection.set(touchController.moveDirection)
                    ship.moveDirection.mul(touchController.moveMagnitude)
                }
''', 'ship control')

    data = replace_once(data,
        '        // Check for tap on upgrade option\n',
        '''        // Autopilot: accept the first valid upgrade to avoid waiting indefinitely.
        // Choice strategy can be refined independently without changing game progression.
        if (autonomousMode) {
            if (upgradeSystem.getPendingOptions().isNotEmpty()) {
                val option = upgradeSystem.selectOption(0)
                if (option != null) {
                    telemetryManager.logUpgradeOffered(state.survivalTime.toInt(), state.telemetryLastOfferedOptions, option.id)
                    SoundManager.playSFX("sfx_ui_upgrade_select")
                    applyUpgrade(option)
                    weaponSystem.resetBeatSync()
                    state.phase = GamePhase.PLAYING
                }
            }
            return
        }
        // Check for tap on upgrade option
''', 'upgrade selection')

    data = replace_once(data,
        '''        // Debug menu overlay (renders on top of everything)
''',
        '''        // An always-visible touch target (logical canvas coordinates) for AUTO ON/OFF.
        if (state.phase == GamePhase.PLAYING) {
            val box = autoButton()
            autoBadgePaint.color = if (autonomousMode) 0xDD167D53.toInt() else 0xDD283849.toInt()
            autoBadgePaint.style = Paint.Style.FILL
            canvas.drawRoundRect(box, 13f, 13f, autoBadgePaint)
            autoBadgePaint.color = 0xFFFFFFFF.toInt()
            autoBadgePaint.textSize = 27f
            autoBadgePaint.textAlign = Paint.Align.CENTER
            canvas.drawText(if (autonomousMode) "AUTO: ON" else "AUTO: OFF", box.centerX(), box.centerY() + 9f, autoBadgePaint)
        }
        // Debug menu overlay (renders on top of everything)
''', 'auto mode badge')

    data = replace_once(data,
        '''    override fun onTouchEvent(event: MotionEvent): Boolean {
''',
        '''    override fun onTouchEvent(event: MotionEvent): Boolean {
        // AUTO toggle lives in screen-space. Any manual touch elsewhere takes back control.
        if (state.phase == GamePhase.PLAYING && !state.isPaused) {
            val x = event.x / renderScale
            val y = event.y / renderScale
            val inside = autoButton().contains(x, y)
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    if (inside) { autoButtonPressed = true; return true }
                    if (autonomousMode) {
                        autonomousMode = false
                        autonomousPilot.reset()
                    }
                }
                MotionEvent.ACTION_MOVE -> if (autoButtonPressed) return true
                MotionEvent.ACTION_UP -> if (autoButtonPressed) {
                    autoButtonPressed = false
                    if (inside) {
                        autonomousMode = !autonomousMode
                        autonomousPilot.reset()
                        touchController.reset()
                    }
                    return true
                }
                MotionEvent.ACTION_CANCEL -> if (autoButtonPressed) {
                    autoButtonPressed = false
                    return true
                }
            }
        }
''', 'touch toggle')

    gradle = replace_once(gradle,
        'applicationId = "com.astroloop.game"',
        'applicationId = "com.astroloop.autopilot"', 'side-by-side package name')
    # Preflight all anchors above BEFORE writing source changes.
    GAME.with_suffix('.kt.original.bak').write_text(GAME.read_text(encoding='utf-8'), encoding='utf-8')
    GRADLE.with_suffix('.kts.original.bak').write_text(GRADLE.read_text(encoding='utf-8'), encoding='utf-8')
    GAME.write_text(data, encoding='utf-8')
    GRADLE.write_text(gradle, encoding='utf-8')
    shutil.copy2(HERE / 'AutoPilot.kt', TARGET)
    if STRINGS.exists():
        original = STRINGS.read_text(encoding='utf-8')
        updated, count = re.subn(r'(<string\s+name="app_name"[^>]*>).*?(</string>)',
            r'\g<1>Astro Loop Auto\2', original, count=1, flags=re.S)
        if count:
            STRINGS.with_suffix('.xml.original.bak').write_text(original, encoding='utf-8')
            STRINGS.write_text(updated, encoding='utf-8')
    print('PATCH APPLIED: experimental AutoPilot, AUTO toggle, auto upgrade selection, separate app id.')
    print('BUILD NEXT: gradlew.bat :app:assembleDebug')
    print('APK IF BUILD PASSES: app/build/outputs/apk/debug/app-debug.apk')

if __name__ == '__main__':
    main()
