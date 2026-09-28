package com.astroloop.game.core

import com.astroloop.game.entity.Asteroid
import com.astroloop.game.entity.EnemyShip
import com.astroloop.game.entity.PowerUp
import com.astroloop.game.entity.PowerUpType
import com.astroloop.game.entity.Projectile
import com.astroloop.game.entity.Ship
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Experimental, self-contained AI controller operating on game-world coordinates.
 * No screenshots, cross-app memory access or synthetic touches.
 * Only produces a movement command; original game physics and collisions are unchanged.
 */
class AutoPilot {
    private var previousX = 0f
    private var previousY = -1f

    // Intentionally small search to keep frame-time bounded on mobile devices.
    private val horizon = floatArrayOf(0.18f, 0.42f, 0.72f, 1.10f)
    private val headings = 20

    fun reset() {
        previousX = 0f
        previousY = -1f
    }

    fun steer(
        ship: Ship,
        asteroids: List<Asteroid>,
        projectiles: List<Projectile>,
        enemies: List<EnemyShip>,
        pickups: List<PowerUp>
    ) {
        val sx = ship.position.x
        val sy = ship.position.y
        val vx = ship.velocity.x
        val vy = ship.velocity.y
        val speed = ship.speed.coerceAtLeast(60f)

        var goalX = 0f
        var goalY = 0f
        var goalWeight = 0f
        var bestInterest = 0f
        for (pickup in pickups) {
            if (!pickup.isActive || pickup.fadeOutTimer >= 0f) continue
            val dx = pickup.position.x - sx
            val dy = pickup.position.y - sy
            val distance = sqrt(dx * dx + dy * dy)
            if (distance > 1400f) continue
            val value = when (pickup.type) {
                PowerUpType.EVOLUTION_DIAMOND -> 360f
                PowerUpType.WEAPON, PowerUpType.PASSIVE -> 250f
                PowerUpType.SCORE_PICKUP -> 65f
            }
            val interest = value / (distance + 120f)
            if (interest > bestInterest && distance > 1f) {
                bestInterest = interest
                goalX = dx / distance
                goalY = dy / distance
                goalWeight = if (pickup.type == PowerUpType.SCORE_PICKUP) 22f else 40f
            }
        }

        var bestScore = Float.NEGATIVE_INFINITY
        var bestX = 0f
        var bestY = 0f
        // Include stop: it may be safer than forcing movement through a wall of hazards.
        for (candidate in 0..headings) {
            val dx: Float
            val dy: Float
            if (candidate == headings) {
                dx = 0f; dy = 0f
            } else {
                val angle = (candidate.toFloat() / headings) * (Math.PI * 2.0).toFloat()
                dx = cos(angle)
                dy = sin(angle)
            }

            var score = if (goalWeight > 0f) {
                (dx * goalX + dy * goalY) * goalWeight
            } else {
                // Default cruise toward north when there are no visible pickups.
                -dy * 7f
            }
            score += (dx * previousX + dy * previousY) * 2.5f
            if (candidate == headings) score -= 6f

            for (t in horizon) {
                // Approximation of acceleration over the lookahead horizon.
                val blend = (t * 2.7f).coerceIn(0f, 1f)
                val futureX = sx + (vx * (1f - blend) + dx * speed * blend) * t
                val futureY = sy + (vy * (1f - blend) + dy * speed * blend) * t
                for (rock in asteroids) {
                    if (!rock.isActive) continue
                    score -= risk(
                        futureX, futureY, rock.position.x + rock.velocity.x * t,
                        rock.position.y + rock.velocity.y * t,
                        ship.radius + rock.radius + 25f, 105f
                    )
                }
                for (shot in projectiles) {
                    if (!shot.isActive || !shot.isEnemyProjectile || shot.isVisualOnly) continue
                    score -= risk(
                        futureX, futureY, shot.position.x + shot.velocity.x * t,
                        shot.position.y + shot.velocity.y * t,
                        ship.radius + shot.radius + 21f, 125f
                    )
                }
                for (enemy in enemies) {
                    if (!enemy.isActive) continue
                    score -= risk(
                        futureX, futureY, enemy.position.x + enemy.velocity.x * t,
                        enemy.position.y + enemy.velocity.y * t,
                        ship.radius + enemy.radius + 25f, 70f
                    )
                }
            }
            if (score > bestScore) {
                bestScore = score
                bestX = dx
                bestY = dy
            }
        }

        previousX = bestX
        previousY = bestY
        // Directly feed the normal game movement vector, with magnitude already applied.
        ship.moveDirection.set(bestX * 0.92f, bestY * 0.92f)
    }

    private fun risk(
        px: Float, py: Float, ox: Float, oy: Float,
        dangerRadius: Float, weight: Float
    ): Float {
        val dx = px - ox
        val dy = py - oy
        val d2 = dx * dx + dy * dy
        val far = dangerRadius + 160f
        if (d2 > far * far) return 0f
        val dist = sqrt(d2)
        val clearance = dist - dangerRadius
        return if (clearance < 0f) {
            weight * (4f + (-clearance / dangerRadius.coerceAtLeast(1f)))
        } else {
            val proximity = 1f - clearance / 160f
            weight * proximity * proximity
        }
    }
}
