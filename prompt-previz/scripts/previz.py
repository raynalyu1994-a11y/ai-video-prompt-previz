#!/usr/bin/env python3
"""
prompt-previz — code previsualization for AI video prompts.

Turn a shot spec (JSON, extracted from a prompt / storyboard) into:
  * a list of problems the generator will likely trip on (timing, space, lens,
    light, wording, acting, fight logic, scene structure)
  * an HTML previz: top-down blocking diagram with camera FOV + 180° line,
    a beat/dialogue timeline per shot, and the issue list.

Usage:
  python3 previz.py check  spec.json  [-o out_dir]     # full previz (report.html + report.json)
  python3 previz.py lint   prompt.txt [--style jkd]    # wording-only lint of a raw prompt
  python3 previz.py schema                              # print the spec format

Standard library only. Spec format: references/shot-spec.md
"""
import argparse, html, json, math, os, re, sys

# ----------------------------------------------------------------- constants
SEV_ORDER = {"error": 0, "warn": 1, "info": 2}
CJK = re.compile(r"[一-鿿]")
SENSOR_W = {"spherical": 24.9, "anamorphic": 39.9}  # effective horizontal width, mm
COC_MM = 0.025
REACH = {"punch": 0.95, "strike": 0.95, "elbow": 0.55, "knee": 0.6, "kick": 1.25,
         "trap": 0.7, "grab": 0.8, "intercept": 0.95, "push": 0.9}
STEP_GAIN = 1.0  # a glide-step / lunge adds roughly a metre of reach

NEGATION = re.compile(r"\b(no|not|never|without|don't|doesn't|avoid|zero)\b|不要|不能|禁止|避免|没有", re.I)
TAIL_OK = re.compile(r"^(no cloned|no text|no watermark|no logo|clean environment plate, no characters)", re.I)
EMOTION_ADV = re.compile(r"\b(sadly|angrily|nervously|happily|anxiously|fearfully|tearfully|lovingly|"
                         r"desperately|bitterly|joyfully|furiously|shyly|coldly|warmly|sorrowfully)\b", re.I)
FACE_CHOREO = re.compile(r"\b(brows? (lift|rise|raise|furrow|knit)s?|eyebrows? (lift|rise|raise)s?|"
                         r"mouth trembles?|lips? (quiver|tremble|tighten)s?|eyes widen|eyes flick|"
                         r"jaw clench(es)?|nostrils flare)\b", re.I)
BRANDS = re.compile(r"\b(ARRI|Alexa|Kodak|Vision3|Portra|Fuji(film)?|Cinestill|Cooke|Panavision|Zeiss|Leica|"
                    r"Canon|Sony|Nikon|RED|Atlas|Hawk|Angenieux|Sigma|Blackmagic|IMAX|Technicolor)\b")
JARGON = re.compile(r"\b(bai[- ]?jong|pak sao|lop sao|jeet tek|bil jee|biu jee|chi sao|tan sao|bong sao|"
                    r"fook sao|jut sao|chung chui|wing chun|jkd|jeet kune do|kung fu|wu shu|kata)\b", re.I)
HIGH_KICK = re.compile(r"\b(spinning|jump(ing)? kick|flying kick|roundhouse to the (head|face)|"
                       r"kick(s|ed)? (him |her |them )?(in|to) the (head|face|jaw|chin))\b", re.I)
FLARE_WORDS = re.compile(r"flare", re.I)
OVAL_WORDS = re.compile(r"oval", re.I)

# ----------------------------------------------------------------- helpers
class Report:
    def __init__(self):
        self.items = []

    def add(self, sev, code, where, msg, fix=""):
        self.items.append({"severity": sev, "code": code, "where": where, "message": msg, "fix": fix})

    def sorted(self):
        return sorted(self.items, key=lambda i: (SEV_ORDER[i["severity"]], i["where"], i["code"]))


def hfov_deg(focal, lens="spherical"):
    w = SENSOR_W.get(lens, SENSOR_W["spherical"])
    return math.degrees(2 * math.atan(w / (2 * focal)))


def f_number(ap):
    if ap is None:
        return None
    if isinstance(ap, (int, float)):
        return float(ap)
    s = str(ap).lower()
    if "wide" in s or "open" in s:
        return 2.0
    m = re.search(r"(\d+(\.\d+)?)", s)
    return float(m.group(1)) if m else None


def dof(focal, n, dist_m):
    """near/far limits of acceptable sharpness in metres (thin-lens approximation)."""
    f, s = focal, dist_m * 1000.0
    H = f * f / (n * COC_MM) + f
    near = s * (H - f) / (H + s - 2 * f)
    far = s * (H - f) / (H - s) if s < H else float("inf")
    return near / 1000.0, far / 1000.0


def pos_at(shot, cid, t):
    p = (shot.get("positions") or {}).get(cid)
    if p is None:
        return None
    cur = dict(p)
    for mv in sorted(shot.get("moves") or [], key=lambda m: m.get("t", 0)):
        if mv.get("id") == cid and mv.get("t", 0) <= t + 1e-9:
            cur.update({k: v for k, v in mv.items() if k in ("x", "y", "facing")})
    return cur


def cam_yaw(shot):
    cam = shot.get("camera") or {}
    if "yaw" in cam:
        return float(cam["yaw"])
    aim = cam.get("aim")
    if isinstance(aim, str):
        p = pos_at(shot, aim, 0)
        if p:
            return math.degrees(math.atan2(p["y"] - cam.get("y", 0), p["x"] - cam.get("x", 0)))
    if isinstance(aim, (list, tuple)) and len(aim) == 2:
        return math.degrees(math.atan2(aim[1] - cam.get("y", 0), aim[0] - cam.get("x", 0)))
    ps = [pos_at(shot, c, 0) for c in (shot.get("positions") or {})]
    ps = [p for p in ps if p]
    if ps:
        cx = sum(p["x"] for p in ps) / len(ps)
        cy = sum(p["y"] for p in ps) / len(ps)
        return math.degrees(math.atan2(cy - cam.get("y", 0), cx - cam.get("x", 0)))
    return 90.0


def screen_x(shot, p):
    """-1..1 = left..right edge of frame; None if behind camera."""
    cam = shot.get("camera") or {}
    fov = hfov_deg(cam.get("focal_mm", 35), cam.get("lens", "spherical"))
    a = math.atan2(p["y"] - cam.get("y", 0), p["x"] - cam.get("x", 0)) - math.radians(cam_yaw(shot))
    a = (a + math.pi) % (2 * math.pi) - math.pi
    if math.cos(a) <= 0:
        return None
    return -math.tan(a) / math.tan(math.radians(fov / 2))


def speech_rate(text, secs):
    if secs <= 0:
        return None, None
    if CJK.search(text):
        n = len(CJK.findall(text))
        return n / secs, 5.0  # chars/s
    n = len(re.findall(r"[A-Za-z']+", text))
    return n / secs, 3.0      # words/s


# ----------------------------------------------------------------- text lint
def lint_text(text, where, rep, style=None, acting_expected=False):
    if not text:
        return
    for line in re.split(r"(?<=[.!?。！？])\s+|\n", text):
        l = line.strip()
        if not l or TAIL_OK.match(l) or l.lower().startswith("(safety"):
            continue
        if re.search(r"safety:|blink", l, re.I):
            continue
        m = NEGATION.search(l)
        if m:
            rep.add("warn", "TEXT-01", where, f"Negative phrasing “{m.group(0)}” in: “{l[:90]}”",
                    "Named = summoned. Rewrite as the positive state you want (e.g. “every kick stays below belt height”).")
    for m in EMOTION_ADV.finditer(text):
        rep.add("warn", "TEXT-02", where, f"Emotion adverb as direction: “{m.group(0)}”",
                "Replace with the task that produces the emotion (acting module, step 5 TACTIC).")
    for m in FACE_CHOREO.finditer(text):
        rep.add("warn", "TEXT-03", where, f"Facial choreography: “{m.group(0)}” — reads as playing the result",
                "Give the eyes a task aimed at the partner instead (acting module).")
    for m in set(x.group(0) for x in BRANDS.finditer(text)):
        rep.add("warn", "TEXT-04", where, f"Brand / manufacturer name in prompt: “{m}”",
                "Describe the look (balance, speed, grain, flare) instead of the label — brands pull logos and priors.")
    for m in set(x.group(0).lower() for x in JARGON.finditer(text)):
        rep.add("warn", "TEXT-05", where, f"Martial-arts term in prompt body: “{m}”",
                "Models don't know the term and fall back to generic kung fu. Use body geometry (fight module, moves-catalog).")
    if style in ("jkd", "wing-chun"):
        for m in HIGH_KICK.finditer(text):
            rep.add("error", "TEXT-07", where, f"High / spinning kick in a {style} scene: “{m.group(0)}”",
                    "Both styles keep every kick below belt height.")
    words = len(re.findall(r"\S+", text)) if not CJK.search(text) else len(CJK.findall(text)) // 2
    if words > 260:
        rep.add("info", "TEXT-06", where, f"Prompt is long (~{words} words); late facts tend to get dropped.",
                "Move critical facts to the first third; cut decoration.")
    if acting_expected and not re.search(r"ACTING TASK", text):
        rep.add("info", "TEXT-08", where, "Dialogue in shot but no ACTING TASK block in the prompt text.")


# ----------------------------------------------------------------- checks
def check_shot(spec, shot, idx, rep, max_len):
    sid = shot.get("id", f"S{idx+1}")
    dur = float(shot.get("duration", 0) or 0)
    beats = shot.get("beats") or []
    dlg = shot.get("dialogue") or []
    cam = shot.get("camera") or {}
    style = (shot.get("style") or spec.get("style") or "").lower() or None
    chars_in = list((shot.get("positions") or {}).keys())

    # ---- TIME
    if dur <= 0:
        rep.add("error", "TIME-00", sid, "Shot has no duration.")
    if max_len and dur > max_len:
        rep.add("warn", "TIME-06", sid, f"Duration {dur}s exceeds model max {max_len}s.", "Split into two shots.")
    for b in beats:
        if b.get("t1", 0) > dur + 1e-6:
            rep.add("error", "TIME-01", sid, f"Beat “{b.get('action','?')}” ends at {b['t1']}s > shot length {dur}s.",
                    "Cut beats or lengthen the shot.")
    action_beats = [b for b in beats if b.get("kind") not in ("still", "look", "dialogue", "react")]
    if dur and action_beats:
        density = len(action_beats) / dur
        if density > 1.25:
            rep.add("warn", "TIME-02", sid,
                    f"{len(action_beats)} action beats in {dur}s ({density:.1f}/s) — generators merge or skip beats this dense.",
                    "Aim for ≤1 action per ~0.8 s; give each beat 1–2 s.")
    by_actor = {}
    for b in beats:
        by_actor.setdefault(b.get("actor"), []).append(b)
    for a, bs in by_actor.items():
        bs = sorted(bs, key=lambda b: b.get("t0", 0))
        for x, y in zip(bs, bs[1:]):
            if y.get("t0", 0) < x.get("t1", 0) - 1e-6 and "still" not in (x.get("kind"), y.get("kind")):
                rep.add("warn", "TIME-03", sid, f"{a}: “{x.get('action')}” and “{y.get('action')}” overlap in time.")
    for d in dlg:
        t0, t1 = d.get("t0", 0), d.get("t1", dur)
        r, lim = speech_rate(d.get("text", ""), t1 - t0)
        if r and r > lim:
            unit = "chars/s" if CJK.search(d.get("text", "")) else "words/s"
            rep.add("error", "TIME-04", sid,
                    f"{d.get('speaker')}: line too fast — {r:.1f} {unit} (comfortable ≤ {lim}). “{d.get('text','')[:40]}”",
                    "Shorten the line or give it more time; rushed lines get swallowed or lip-sync breaks.")
        if t1 > dur + 1e-6:
            rep.add("error", "TIME-05", sid, f"{d.get('speaker')}'s line runs past the end of the shot ({t1}s > {dur}s).")

    # ---- SPACE
    pts = {c: pos_at(shot, c, 0) for c in chars_in}
    if cam and pts:
        for c, p in pts.items():
            sx = screen_x(shot, p)
            must = c in {b.get("actor") for b in beats} or c in {d.get("speaker") for d in dlg}
            if (sx is None or abs(sx) > 1.0) and must and not shot.get("offscreen", {}).get(c):
                rep.add("warn", "SPACE-03", sid, f"{c} acts/speaks but sits outside the camera's field of view.",
                        "Move the camera, widen the lens, or mark the character offscreen.")
    names = list(pts.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = pts[names[i]], pts[names[j]]
            if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < 0.35:
                rep.add("warn", "SPACE-05", sid, f"{names[i]} and {names[j]} occupy the same spot (<0.35 m).")
    for b in beats:
        kind = (b.get("kind") or "").lower()
        if kind in REACH and b.get("target") in pts and b.get("actor") in pts:
            pa, pt = pos_at(shot, b["actor"], b.get("t0", 0)), pos_at(shot, b["target"], b.get("t0", 0))
            d = math.hypot(pa["x"] - pt["x"], pa["y"] - pt["y"])
            reach = REACH[kind] + (STEP_GAIN if b.get("step") else 0)
            if d > reach + 0.05:
                rep.add("error", "SPACE-04", sid,
                        f"{b['actor']}'s {kind} (“{b.get('action','')}”) at {b.get('t0')}s: target is {d:.2f} m away, reach ≈ {reach:.2f} m.",
                        "Add a closing step (and say so in the prompt), or move the characters closer before this beat.")

    # ---- LENS
    focal = cam.get("focal_mm")
    framing = (shot.get("framing") or "").lower()
    if focal and focal < 35 and (framing in ("close", "closeup", "close-up", "ecu", "mcu") or shot.get("subject") == "face"):
        rep.add("error", "LENS-01", sid, f"{focal} mm on a face / close-up — the face will stretch.",
                "Use 85 mm for portraits, 50 mm for medium shots.")
    if focal:
        shot["_hfov"] = round(hfov_deg(focal, cam.get("lens", "spherical")), 1)
    focus = shot.get("focus") or {}
    if shot.get("blur_requested"):
        miss = [k for k, v in (("focus target", focus.get("target")), ("focus distance", focus.get("distance_m")),
                               ("aperture", cam.get("aperture"))) if not v]
        if miss:
            rep.add("error", "LENS-02", sid, "Strong blur asked for but the physics is missing: " + ", ".join(miss) + ".",
                    "Name one focus object, put the camera 1–3 m from it, say “wide open” (anamorphic module §2).")
        n = f_number(cam.get("aperture"))
        bg = shot.get("background_m")
        if focal and n and focus.get("distance_m"):
            near, far = dof(focal, n, focus["distance_m"])
            shot["_dof"] = [round(near, 2), None if far == float("inf") else round(far, 2)]
            if bg and bg <= far:
                rep.add("error", "LENS-03", sid,
                        f"Depth of field {near:.1f}–{'∞' if far == float('inf') else f'{far:.1f}'} m at f/{n:g}: background at {bg} m will be SHARP.",
                        "Move the camera closer to the focus object, open up, or use a longer lens.")
    text = shot.get("prompt", "")
    shared = spec.get("shared_prompt", "")
    full = (text + "\n" + shared).strip()
    if cam.get("lens") == "anamorphic" and full:
        if not OVAL_WORDS.search(full):
            rep.add("warn", "LENS-04", sid, "Anamorphic lens named but no oval bokeh described — model will render round bokeh.",
                    "Add “elongated vertical oval highlights on <surface>”.")

    # ---- LIGHT
    lights = shot.get("lights") or []
    flare = shot.get("flare") or {}
    if flare:
        src = [l for l in lights if l.get("in_frame")]
        if not src:
            rep.add("error", "LIGHT-02", sid, "Streak flare described but no bright source in frame.",
                    "Put one practical (lamp, window, horizon band) in frame and name the flare's source.")
        named = next((l for l in lights if l.get("name") == flare.get("source")), None) or (src[0] if src else None)
        if named and (flare.get("color") or "").lower() == "blue" and named.get("kelvin", 5600) < 4000:
            rep.add("warn", "LIGHT-01", sid,
                    f"Blue streak off a warm source ({named.get('name')}, {named.get('kelvin')}K) reads fake.",
                    "Make it a warm-orange streak, or add a cool source for the blue one.")
    elif cam.get("lens") == "anamorphic" and full and not FLARE_WORDS.search(full):
        rep.add("info", "LIGHT-04", sid, "Anamorphic shot with no flare described — fine if intentional.")
    stock = (shot.get("film_stock") or "").lower()
    tod = (shot.get("time_of_day") or "").lower()
    if stock:
        warm = [l for l in lights if l.get("kelvin", 5600) < 4000]
        if stock == "daylight" and (tod in ("night", "interior-night") or (lights and len(warm) == len(lights))):
            rep.add("warn", "LIGHT-03", sid, "Daylight-balanced stock on a night / tungsten-lit scene.",
                    "Use “tungsten-balanced 500-speed colour negative film grain”.")
        if stock == "tungsten" and tod in ("day", "noon", "overcast") and not warm:
            rep.add("warn", "LIGHT-03", sid, "Tungsten-balanced stock on a daylight scene.",
                    "Use “daylight-balanced 250-speed colour negative film, fine grain”.")

    # ---- ACTING
    acting = shot.get("acting") or {}
    speakers = {d.get("speaker") for d in dlg}
    for c in speakers:
        if c not in acting:
            rep.add("warn", "ACT-01", sid, f"{c} speaks but has no ACTING TASK — expect dead, glassy eyes.",
                    "Write scene direction / motive / goal / obstacle / tactic (acting module).")
    if dlg:
        for c in chars_in:
            if c not in speakers and c not in acting and not shot.get("offscreen", {}).get(c):
                rep.add("info", "ACT-04", sid, f"{c} is in frame as a listener with no task.",
                        "A listener's task is real too (e.g. “decide if he's serious”).")
    for c, a in acting.items():
        miss = [k for k in ("scene_direction", "motive", "goal", "obstacle", "tactic") if not a.get(k)]
        if miss:
            rep.add("warn", "ACT-02", sid, f"{c}'s acting task is missing: {', '.join(miss)}.")
        if not a.get("safety_line"):
            rep.add("info", "ACT-03", sid, f"{c}: no anti-frozen-stare safety line.",
                    "Add: gaze always engaged in the task, natural blink cadence.")
        tac = a.get("tactic", "")
        if tac and (EMOTION_ADV.search(tac) or FACE_CHOREO.search(tac)):
            rep.add("warn", "ACT-05", sid, f"{c}'s tactic describes the face, not an action at the partner.")

    # ---- FIGHT
    strikes = [b for b in beats if (b.get("kind") or "") in ("punch", "kick", "strike", "elbow", "knee", "intercept", "trap")]
    if style in ("jkd", "wing-chun") and strikes:
        for b in strikes:
            if b.get("kind") == "kick" and (b.get("height") or "").lower() in ("head", "face", "chest", "high"):
                rep.add("error", "FIGHT-01", sid, f"Kick to the {b['height']} in a {style} scene.",
                        "Low line only: knee, shin, groin, stomach.")
        if style == "jkd" and not any(b.get("kind") == "intercept" or re.search(r"intercept|stop[- ]hit|stop[- ]kick", b.get("action", ""), re.I) for b in strikes):
            rep.add("warn", "FIGHT-02", sid, "No interception / stop-hit beat — this is the style's defining logic.")
        if len(strikes) > 4:
            rep.add("warn", "FIGHT-03", sid, f"{len(strikes)} strike beats — economy rule says resolve in 2–4.")
        if not any(b.get("kind") == "still" for b in beats):
            rep.add("info", "FIGHT-04", sid, "No stillness beat — broken rhythm (explosion → stillness → explosion) is missing.")
        if full and "FIGHT STYLE LOCK" not in full:
            rep.add("info", "FIGHT-05", sid, "Prompt text has no FIGHT STYLE LOCK line at the end.")

    lint_text(text, sid, rep, style=style, acting_expected=bool(dlg) and "ACTING TASK" not in shared)


def check_sequence(spec, rep):
    shots = spec.get("shots") or []
    axis = spec.get("axis")
    prev = None
    for s in shots:
        cam = s.get("camera") or {}
        pos = s.get("positions") or {}
        ax = axis or (list(pos.keys())[:2] if len(pos) >= 2 else None)
        if not cam or not ax or not all(a in pos for a in ax):
            prev = None
            continue
        A, B = pos_at(s, ax[0], 0), pos_at(s, ax[1], 0)
        cross = (B["x"] - A["x"]) * (cam.get("y", 0) - A["y"]) - (B["y"] - A["y"]) * (cam.get("x", 0) - A["x"])
        side = 1 if cross > 0 else -1
        sa, sb = screen_x(s, A), screen_x(s, B)
        order = None if sa is None or sb is None else (ax[0] if sa < sb else ax[1])
        s["_axis_side"], s["_left"] = side, order
        if prev and prev["side"] != side and not s.get("crosses_line_ok"):
            rep.add("error", "SPACE-01", s.get("id"),
                    f"Camera jumped across the 180° line ({ax[0]}–{ax[1]}) from {prev['id']} — screen direction flips.",
                    "Keep the camera on one side, show the move across the line on screen, or set crosses_line_ok.")
        elif prev and order and prev["left"] and order != prev["left"] and not s.get("crosses_line_ok"):
            rep.add("warn", "SPACE-02", s.get("id"),
                    f"{ax[0]}/{ax[1]} swapped left/right of frame vs {prev['id']}.")
        prev = {"id": s.get("id"), "side": side, "left": order}

    eng = spec.get("scene_engine")
    if eng:
        for k in ("goal", "obstacle"):
            if not eng.get(k):
                rep.add("warn", "ENGINE-01", "scene", f"Scene engine: no {k} named.")
        if eng.get("obstacle") and not eng.get("obstacle_scale"):
            rep.add("info", "ENGINE-04", "scene", "Obstacle scale (stage / whole goal) not named.")
        revs = eng.get("reversals") or []
        if eng.get("sequence_resolved", True) and not revs:
            rep.add("error", "ENGINE-03", "scene", "Resolved sequence with zero reversals — fails the engine.")
        for i, r in enumerate(revs, 1):
            vs = r.get("value_shift") or {}
            if not (vs.get("before") and vs.get("after")):
                rep.add("error", "ENGINE-02", "scene",
                        f"Reversal {i} (“{r.get('what','')[:50]}”) has no audience before→after verdict — it is INERT.",
                        "Name how the audience re-judges the character; if you can't, redesign the reversal.")
        for i, t in enumerate(eng.get("tactics") or [], 1):
            if isinstance(t, dict) and t.get("fails") and not t.get("returns_info"):
                rep.add("warn", "ENGINE-05", "scene", f"Tactic {i} fails and returns no information — wheel-spin.")


# ----------------------------------------------------------------- rendering
def svg_topdown(shot, w=360, h=300):
    cam = shot.get("camera") or {}
    pos = shot.get("positions") or {}
    moves = shot.get("moves") or []
    pts = [(cam.get("x", 0), cam.get("y", 0))] + [(p["x"], p["y"]) for p in pos.values()] + \
          [(m["x"], m["y"]) for m in moves if "x" in m]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = 1.2
    minx, maxx, miny, maxy = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    sc = min(w / (maxx - minx), h / (maxy - miny))
    T = lambda x, y: ((x - minx) * sc, h - (y - miny) * sc)
    out = [f'<svg viewBox="0 0 {w} {h}" class="td" role="img" aria-label="top-down blocking">']
    # grid (1 m)
    for gx in range(math.floor(minx), math.ceil(maxx) + 1):
        x, _ = T(gx, 0); out.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h}" class="grid"/>')
    for gy in range(math.floor(miny), math.ceil(maxy) + 1):
        _, y = T(0, gy); out.append(f'<line x1="0" y1="{y:.1f}" x2="{w}" y2="{y:.1f}" class="grid"/>')
    # 180 line
    names = list(pos.keys())
    if len(names) >= 2:
        a, b = pos[names[0]], pos[names[1]]
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        L = math.hypot(dx, dy) or 1
        ext = 50
        p1 = T(a["x"] - dx / L * ext, a["y"] - dy / L * ext); p2 = T(a["x"] + dx / L * ext, a["y"] + dy / L * ext)
        out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" class="axis"/>')
    # camera wedge
    if cam:
        yaw = math.radians(cam_yaw(shot))
        fov = math.radians(hfov_deg(cam.get("focal_mm", 35), cam.get("lens", "spherical")))
        r = 90 / sc
        cx, cy = cam.get("x", 0), cam.get("y", 0)
        l = (cx + r * math.cos(yaw + fov / 2), cy + r * math.sin(yaw + fov / 2))
        rr = (cx + r * math.cos(yaw - fov / 2), cy + r * math.sin(yaw - fov / 2))
        P = [T(cx, cy), T(*l), T(*rr)]
        out.append('<polygon points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in P) + '" class="fov"/>')
        X, Y = T(cx, cy)
        out.append(f'<rect x="{X-6:.1f}" y="{Y-5:.1f}" width="12" height="10" rx="2" class="cam"/>')
        out.append(f'<text x="{X+9:.1f}" y="{Y+4:.1f}" class="lbl">CAM {cam.get("focal_mm","?")}mm</text>')
    # move paths
    for cid in names:
        trail = [pos[cid]] + [m for m in sorted(moves, key=lambda m: m.get("t", 0)) if m.get("id") == cid and "x" in m]
        if len(trail) > 1:
            d = " ".join(f"{T(p['x'], p['y'])[0]:.1f},{T(p['x'], p['y'])[1]:.1f}" for p in trail)
            out.append(f'<polyline points="{d}" class="path"/>')
    # characters
    for i, cid in enumerate(names):
        p = pos[cid]
        X, Y = T(p["x"], p["y"])
        out.append(f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="9" class="ch c{i%4}"/>')
        if "facing" in p:
            f = math.radians(p["facing"])
            out.append(f'<line x1="{X:.1f}" y1="{Y:.1f}" x2="{X+18*math.cos(f):.1f}" y2="{Y-18*math.sin(f):.1f}" class="face"/>')
        out.append(f'<text x="{X+11:.1f}" y="{Y-10:.1f}" class="lbl">{html.escape(str(cid))}</text>')
    out.append("</svg>")
    return "".join(out)


def svg_timeline(shot, w=520):
    dur = float(shot.get("duration", 0) or 1)
    rows = {}
    for b in shot.get("beats") or []:
        rows.setdefault(str(b.get("actor", "?")), []).append(("beat", b))
    for d in shot.get("dialogue") or []:
        rows.setdefault(str(d.get("speaker", "?")), []).append(("dlg", d))
    lh, left = 26, 70
    h = max(1, len(rows)) * lh + 24
    sc = (w - left - 10) / max(dur, max([x[1].get("t1", 0) for r in rows.values() for x in r] + [dur]))
    out = [f'<svg viewBox="0 0 {w} {h}" class="tl" role="img" aria-label="timeline">']
    for s in range(int(dur) + 1):
        x = left + s * sc
        out.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{h-16}" class="grid"/><text x="{x:.1f}" y="{h-4}" class="tick">{s}s</text>')
    xe = left + dur * sc
    out.append(f'<line x1="{xe:.1f}" y1="0" x2="{xe:.1f}" y2="{h-16}" class="end"/>')
    for i, (actor, items) in enumerate(rows.items()):
        y = i * lh + 4
        out.append(f'<text x="4" y="{y+15}" class="lbl">{html.escape(actor)}</text>')
        for typ, it in items:
            x0, x1 = left + it.get("t0", 0) * sc, left + it.get("t1", dur) * sc
            cls = "dlg" if typ == "dlg" else ("still" if it.get("kind") == "still" else "beat")
            label = it.get("text") if typ == "dlg" else (it.get("action") or it.get("kind") or "")
            out.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(2,x1-x0):.1f}" height="{lh-6}" rx="3" class="{cls}">'
                       f'<title>{html.escape(str(label))}</title></rect>')
            out.append(f'<text x="{x0+3:.1f}" y="{y+14}" class="bt">{html.escape(str(label)[:int((x1-x0)/6)])}</text>')
    out.append("</svg>")
    return "".join(out)


CSS = """
:root{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dd;--err:#c2410c;--warn:#b45309;--info:#2563eb;
--fov:rgba(37,99,235,.13);--fovs:#2563eb;--axis:#dc2626;--beat:#334155;--still:#cbd5e1;--dlg:#0d9488}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mut:#9a9890;--card:#1d1d1b;--line:#33322e;
--err:#fb923c;--warn:#fbbf24;--info:#60a5fa;--fov:rgba(96,165,250,.16);--fovs:#60a5fa;--axis:#f87171;--beat:#94a3b8;--still:#475569;--dlg:#2dd4bf}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,system-ui,"PingFang SC",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 8px}
.mut{color:var(--mut)}.sum{display:flex;gap:10px;margin:14px 0 22px;flex-wrap:wrap}.pill{padding:4px 10px;border-radius:99px;border:1px solid var(--line);background:var(--card)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:0 0 16px}
.grid2{display:grid;grid-template-columns:minmax(0,360px) minmax(0,1fr);gap:14px}@media(max-width:720px){.grid2{grid-template-columns:1fr}}
svg{width:100%;height:auto;display:block}.grid{stroke:var(--line);stroke-width:1}.axis{stroke:var(--axis);stroke-dasharray:6 4;stroke-width:1.5}
.fov{fill:var(--fov);stroke:var(--fovs)}.cam{fill:var(--fovs)}.ch{stroke:var(--card);stroke-width:2}.c0{fill:#e11d48}.c1{fill:#7c3aed}.c2{fill:#059669}.c3{fill:#d97706}
.face{stroke:var(--fg);stroke-width:2}.path{fill:none;stroke:var(--mut);stroke-dasharray:3 3}.lbl{font-size:11px;fill:var(--fg)}.tick{font-size:10px;fill:var(--mut)}
.beat{fill:var(--beat)}.still{fill:var(--still)}.dlg{fill:var(--dlg)}.bt{font-size:10px;fill:#fff;pointer-events:none}.end{stroke:var(--axis);stroke-width:2}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:6px 8px;border-top:1px solid var(--line);vertical-align:top}
.error{color:var(--err);font-weight:600}.warn{color:var(--warn);font-weight:600}.info{color:var(--info)}code{font-size:12px}
pre{white-space:pre-wrap;font-size:12px;background:var(--bg);padding:8px;border-radius:6px;border:1px solid var(--line);max-height:180px;overflow:auto}
"""


def render_html(spec, items):
    cnt = {k: sum(1 for i in items if i["severity"] == k) for k in SEV_ORDER}
    o = [f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Prompt Previz</title><style>{CSS}</style></head><body><main>"]
    o.append(f"<h1>{html.escape(spec.get('title','Prompt previz'))}</h1><div class='mut'>代码预演报告 · code previz report</div>")
    o.append(f"<div class='sum'><span class='pill error'>❌ {cnt['error']} error</span><span class='pill warn'>⚠ {cnt['warn']} warn</span>"
             f"<span class='pill info'>ℹ {cnt['info']} info</span></div>")
    for s in spec.get("shots") or []:
        sid = s.get("id")
        cam = s.get("camera") or {}
        meta = [f"{s.get('duration','?')}s"]
        if cam.get("focal_mm"):
            meta.append(f"{cam.get('lens','spherical')} {cam['focal_mm']}mm · HFOV {s.get('_hfov','?')}°")
        if s.get("_dof"):
            meta.append(f"DoF {s['_dof'][0]}–{s['_dof'][1] if s['_dof'][1] is not None else '∞'} m")
        if s.get("_left"):
            meta.append(f"frame-left: {s['_left']}")
        o.append(f"<div class='card'><h2>{html.escape(str(sid))} <span class='mut'>{' · '.join(map(html.escape, meta))}</span></h2>")
        o.append(f"<div class='grid2'><div>{svg_topdown(s) if (s.get('positions') or cam) else ''}</div><div>{svg_timeline(s)}")
        si = [i for i in items if i["where"] == sid]
        if si:
            o.append("<ul>" + "".join(f"<li><span class='{i['severity']}'>{i['code']}</span> {html.escape(i['message'])}</li>" for i in si) + "</ul>")
        if s.get("prompt"):
            o.append(f"<details><summary class='mut'>prompt</summary><pre>{html.escape(s['prompt'])}</pre></details>")
        o.append("</div></div></div>")
    o.append("<div class='card'><h2>All issues</h2><table><tr><th>Sev</th><th>Code</th><th>Where</th><th>Problem</th><th>Fix</th></tr>")
    for i in items:
        o.append(f"<tr><td class='{i['severity']}'>{i['severity']}</td><td><code>{i['code']}</code></td><td>{html.escape(str(i['where']))}</td>"
                 f"<td>{html.escape(i['message'])}</td><td class='mut'>{html.escape(i['fix'])}</td></tr>")
    o.append("</table></div><p class='mut'>Top-down: red dashed = 180° line between the first two characters; blue wedge = camera horizontal FOV; "
             "ticks = facing; dotted = blocking moves. Timeline: dark = action beat, grey = stillness, teal = dialogue, red bar = shot end.</p>")
    o.append("</main></body></html>")
    return "".join(o)


def to_markdown(items):
    if not items:
        return "✅ No issues found."
    icon = {"error": "❌", "warn": "⚠️", "info": "ℹ️"}
    lines = [f"{icon[i['severity']]} [{i['code']}] {i['where']}: {i['message']}" + (f"\n    → {i['fix']}" if i['fix'] else "") for i in items]
    return "\n".join(lines)


SCHEMA_HINT = """See references/shot-spec.md. Minimal example:
{"title":"Alley fight","style":"jkd","shots":[{"id":"S1","duration":5,
 "camera":{"x":0,"y":-3,"aim":"A","focal_mm":35,"lens":"anamorphic","aperture":"wide open"},
 "positions":{"A":{"x":0,"y":0,"facing":0},"B":{"x":1.6,"y":0,"facing":180}},
 "beats":[{"t0":0.5,"t1":1.5,"actor":"A","kind":"intercept","action":"lead straight to chin","target":"B","step":true}],
 "prompt":"..."}]}"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Code previz for AI video prompts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("spec"); c.add_argument("-o", "--out", default="previz_out")
    c.add_argument("--max-len", type=float, default=15.0, help="model max shot length in seconds (0 = off)")
    l = sub.add_parser("lint"); l.add_argument("prompt"); l.add_argument("--style", default=None)
    sub.add_parser("schema")
    a = ap.parse_args(argv)

    if a.cmd == "schema":
        print(SCHEMA_HINT); return 0
    rep = Report()
    if a.cmd == "lint":
        text = sys.stdin.read() if a.prompt == "-" else open(a.prompt, encoding="utf-8").read()
        lint_text(text, "prompt", rep, style=a.style, acting_expected=False)
        print(to_markdown(rep.sorted()))
        return 1 if any(i["severity"] == "error" for i in rep.items) else 0

    spec = json.load(open(a.spec, encoding="utf-8"))
    for i, s in enumerate(spec.get("shots") or []):
        s.setdefault("id", f"S{i+1}")
        check_shot(spec, s, i, rep, a.max_len)
    check_sequence(spec, rep)
    items = rep.sorted()
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"issues": items, "shots": [{k: v for k, v in s.items() if k.startswith("_") or k == "id"}
                                              for s in spec.get("shots") or []]}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(a.out, "report.html"), "w", encoding="utf-8") as f:
        f.write(render_html(spec, items))
    print(to_markdown(items))
    print(f"\nHTML previz: {os.path.join(a.out, 'report.html')}")
    return 1 if any(i["severity"] == "error" for i in items) else 0


if __name__ == "__main__":
    sys.exit(main())
