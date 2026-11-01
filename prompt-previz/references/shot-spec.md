# Shot spec format

One JSON file per prompt / sequence. Everything is optional except `shots[].duration`; the more you fill in, the more the previz can check. Fields starting with `_` are written by the script.

Coordinates: metres on a top-down floor plan. `x` → right, `y` → forward (up on the diagram). `facing` / `yaw` in degrees, 0° = +x, counter-clockwise (90° = +y).

```jsonc
{
  "title": "Rain alley",
  "style": "jkd",                    // jkd | wing-chun | null — enables fight checks
  "axis": ["HERO", "THUG"],          // 180° line; default = first two characters in positions
  "scene_engine": {                  // optional, for scene / sequence structure checks
    "goal": "…", "obstacle": "…", "obstacle_scale": "stage | global",
    "tactics": [{"what": "…", "fails": true, "returns_info": true}],
    "reversals": [{"what": "…", "form": "action flips | hidden agency | general",
                   "value_shift": {"before": "audience thinks he's X", "after": "now they see Y"}}],
    "sequence_resolved": true
  },
  "shots": [{
    "id": "S1",
    "duration": 5,                   // seconds
    "framing": "wide | medium | close | ecu | insert",
    "subject": "face | body | location",
    "time_of_day": "day | night | dusk | interior-night",
    "film_stock": "tungsten | daylight",
    "camera": {
      "x": 0, "y": -3,               // camera position
      "aim": "HERO",                 // character id, [x,y] point, or use "yaw": 90
      "focal_mm": 35,
      "lens": "anamorphic | spherical",
      "aperture": "wide open",       // or 2.8
      "height": "knee | waist | chest | eye"
    },
    "focus": {"target": "HERO", "distance_m": 2.0},
    "blur_requested": true,          // the prompt asks for strong blur / shallow DoF
    "background_m": 8,               // distance camera → background that should be soft
    "lights": [{"name": "street lamp", "kelvin": 3000, "in_frame": true}],
    "flare": {"color": "blue | warm-orange", "source": "street lamp"},
    "positions": {"HERO": {"x": 0, "y": 0, "facing": 0}, "THUG": {"x": 1.4, "y": 0, "facing": 180}},
    "moves": [{"t": 1.0, "id": "HERO", "x": 0.6, "y": 0}],   // position changes over time
    "offscreen": {"THUG": true},     // character is intentionally out of frame
    "crosses_line_ok": false,        // this shot deliberately crosses the 180° line
    "beats": [
      // kind: still | move | look | react (a reaction to a hit — not counted as a new action) | punch | kick | strike | elbow | knee | intercept | trap | grab | push | dialogue
      {"t0": 0.0, "t1": 1.0, "actor": "HERO", "kind": "still", "action": "side-on stance"},
      {"t0": 1.0, "t1": 1.8, "actor": "HERO", "kind": "intercept", "action": "lead straight to chin",
       "target": "THUG", "height": "head", "step": true}
    ],
    "dialogue": [{"speaker": "THUG", "t0": 2.0, "t1": 4.0, "text": "Move."}],
    "acting": {
      "THUG": {"scene_direction": "…", "motive": "…", "goal": "…", "obstacle": "…",
               "tactic": "…", "safety_line": true}
    },
    "prompt": "full prompt text for this shot",
    "_assumed": ["camera.x/y estimated from 'three-quarter angle'", "lights.kelvin guessed"]
  }]
}
```

## Extraction tips

- "Wide / establishing" with no lens → assume 24–35 mm. "Close-up" → 50–85 mm. Record the assumption.
- "Camera 2 m from…" → place the camera 2 m from that object along the described angle.
- Each verb that changes the picture is a beat. Reactions ("staggers back") are beats of the target.
- Dialogue with no timing: spread lines across the shot in order, leaving ~0.3 s gaps.
- Reach constants (m): punch 0.95, kick 1.25, elbow 0.55, knee 0.6, trap 0.7, grab 0.8; `step: true` adds ~1.0.
