# Module: Fight Choreography (Jeet Kune Do / Wing Chun)

A fight choreographer for AI video prompts. The aim: on-screen combat reads as real JKD (or Wing Chun) rather than generic kung fu with broad, swinging strikes.

This module supplies fight CONTENT; whatever prompt format is in use supplies the FORMAT.

## Knowledge base

| File | When to read it |
|---|---|
| `jkd-core.md` | Always when building choreography: principles, stance, footwork, ranges, the five ways of attack. |
| `moves-catalog.md` | Read FIRST when the user names specific moves (pak sao, stop-kick, lop sao pull…): alias → canonical move → English snippet + reaction. Resolution rules at the bottom. |
| `styles/wing-chun.md` | When the user asks for Wing Chun / Ip Man style: frontal stance, sticky contact, chain punches, its own FIGHT STYLE LOCK. Both styles can share one scene as a clash of schools. |
| `techniques.md` | Choosing specific strikes and interceptions: mechanics and visual features. |
| `choreography-patterns.md` | Ready-made beat patterns (interception, two-on-one, knife, trap combination) and rules for translating them into prompt language. |

## Workflow

1. **Break down the scene.** Fighters, number of opponents, weapons, location, emotion, shot duration, winner. If the user names moves, resolve each through `moves-catalog.md` and keep their order.
2. **Read** `jkd-core.md` and `choreography-patterns.md`.
3. **Choreograph in beats** of 1–2 s. Each beat: position → action (which limb, which technique, which target) → opponent's physical reaction → new position. JKD logic: intercept rather than block, shortest line, minimal movement.
4. **Translate into prompt language** (see `choreography-patterns.md`): concrete limbs and targets, non-telegraphed motion, timing in seconds.
5. **Check authenticity** with the checklist below — and run the previz (`scripts/previz.py`) on the beat list: it catches beats that are too dense, strikes thrown from out of reach, and kicks above the belt.

## Authenticity checklist

- Stance as BODY GEOMETRY in the opening frame (snippet S1), not a term — the model does not know "bai-jong".
- At least one stop-hit / interception.
- Kicks below the waist, written positively: "every kick stays below belt height."
- No windup, written positively: "the first visible motion of a limb IS the strike itself, launched from where the hands rest at guard."
- Broken rhythm: explosion → complete stillness → explosion (stillness written as a state, S3).
- Economy: resolve the fight in 2–4 beats.
- Every strike: limb, trajectory, target, and the physics of the reaction along the strike vector.
- Martial-arts terminology and prohibitions stay out of the prompt body (named = summoned). End with a FIGHT STYLE LOCK (see `moves-catalog.md`).

## Example: one beat → one prompt sentence

Weak: "the hero fights off the attacker with martial arts moves"

Strong: "He stands almost side-on, right shoulder and right foot leading, rear heel floating off the ground, weight light on the balls of his feet, lead hand half-extended at shoulder height. The attacker's shoulder just begins to load a wide right swing — and in that exact instant the hero's lead fist is already landing on his chin, one straight line from where it hovered at guard, a short glide-step feeding body weight into it. The attacker's head whips back and he staggers two steps into the dumpster. The hero settles back into the narrow side-on stance and goes completely still."
