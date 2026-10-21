"""
Auto-player de MIDI para el piano/guitarra in-game (E3 a D#6, 36 notas cromaticas).
Autor: UID 214287452235

Uso:
  python piano_player_es.py                        # menu interactivo (canciones de la carpeta "midis")
  python piano_player_es.py cancion.txt            # formato texto
  python piano_player_es.py cancion.mid            # archivo MIDI
  python piano_player_es.py cancion.mid --list     # lista las pistas del MIDI
  python piano_player_es.py cancion.mid --track 2  # toca solo esa pista
  python piano_player_es.py cancion.mid --speed 0.9 --transpose -12

Requisitos:  pip install keyboard mido
Windows: ejecutar la terminal como ADMINISTRADOR (si no, el juego ignora las teclas).
Parar en cualquier momento: ESC.

Formato texto (.txt):
  bpm=100
  E4 G4 C5:2 R:1 C4+E4+G4:2     # nota[:beats]  R = silencio  A+B = acorde
  # las lineas que empiezan con # son comentarios
"""
import argparse
import os
import re
import sys
import time

import keyboard

# --- Mapa de teclas: indice 0 = E3 (MIDI 52) ... indice 35 = D#6 (MIDI 87) ---
BAS = ["a", "s", "d", "f", "g", "h", "j", "k", "l", ";", "'", "enter"]    # E3..D#4
MID = ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "[", "]"]        # E4..D#5
TRE = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="]        # E5..D#6
KEYS = BAS + MID + TRE
LOW, HIGH = 52, 52 + len(KEYS) - 1  # 52..87

NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def name_to_midi(name: str) -> int:
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d)", name.strip())
    if not m:
        raise ValueError(f"Nota invalida: {name!r}")
    letter, acc, octave = m.groups()
    n = NOTE_BASE[letter.upper()] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return 12 * (int(octave) + 1) + n


def fold(n: int) -> int:
    """Lleva la nota al rango del instrumento moviendola de a octavas."""
    while n < LOW:
        n += 12
    while n > HIGH:
        n -= 12
    return n


def key_for(n: int) -> str:
    return KEYS[fold(n) - LOW]


def stopped() -> bool:
    return keyboard.is_pressed("esc")


def countdown(secs=5):
    print(f"Cambia a la ventana del juego. Empieza en {secs}s (ESC para parar)...")
    for i in range(secs, 0, -1):
        print(i, end=" ", flush=True)
        time.sleep(1)
    print("\n>> Tocando... (ESC para parar)")


# ------------------------------- TEXTO ---------------------------------
def play_text(path, speed, transpose):
    bpm = 100.0
    events = []  # (keys[], beats)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0] if line.lstrip().startswith("#") else line
            line = re.sub(r"\s#.*$", "", line).strip()
            if not line:
                continue
            if line.lower().startswith("bpm="):
                bpm = float(line.split("=")[1])
                continue
            for tok in line.split():
                pitch, _, dur = tok.partition(":")
                beats = float(dur) if dur else 1.0
                if pitch.upper() == "R":
                    events.append(([], beats))
                else:
                    notes = [name_to_midi(p) + transpose for p in pitch.split("+")]
                    events.append(([key_for(n) for n in notes], beats))

    spb = 60.0 / (bpm * speed)
    countdown()
    for keys, beats in events:
        if stopped():
            break
        dur = beats * spb
        for k in keys:
            keyboard.press(k)
        time.sleep(min(0.08, dur * 0.6))
        for k in keys:
            keyboard.release(k)
        time.sleep(max(0, dur - min(0.08, dur * 0.6)))


# -------------------------------- MIDI ---------------------------------
def load_midi_events(path, track, transpose, tagged_out=False):
    """Eventos (t, 'on'/'off', nota). Con tagged_out=True agrega el indice de pista."""
    import mido

    mid = mido.MidiFile(path, clip=True)
    if track is None:
        wanted = set(range(len(mid.tracks)))
    else:
        wanted = {track} if isinstance(track, int) else set(track)

    # Se mezclan TODAS las pistas para respetar los cambios de tempo de cualquiera,
    # pero solo se toman notas de las pistas elegidas.
    tagged = []
    for i, tr in enumerate(mid.tracks):
        tick = 0
        for msg in tr:
            tick += msg.time
            tagged.append((tick, i, msg))
    tagged.sort(key=lambda x: x[0])

    tempo, last_tick, t, out = 500000, 0, 0.0, []
    for tick, i, msg in tagged:
        t += mido.tick2second(tick - last_tick, mid.ticks_per_beat, tempo)
        last_tick = tick
        if msg.type == "set_tempo":
            tempo = msg.tempo
            continue
        if i not in wanted or getattr(msg, "channel", 0) == 9:  # 9 = bateria
            continue
        if msg.type == "note_on" and msg.velocity > 0:
            ev = (t, "on", msg.note + transpose)
        elif msg.type in ("note_off", "note_on"):
            ev = (t, "off", msg.note + transpose)
        else:
            continue
        out.append(ev + (i,) if tagged_out else ev)
    out.sort(key=lambda e: e[0])
    return out


def note_tracks(path):
    """Pistas con notas tocables (sin bateria): [(indice, nombre, cantidad)]."""
    import mido

    res = []
    for i, tr in enumerate(mido.MidiFile(path, clip=True).tracks):
        n = sum(1 for m in tr if m.type == "note_on" and m.velocity > 0 and m.channel != 9)
        if n:
            res.append((i, tr.name or "(sin nombre)", n))
    return res


def _moments(events):
    raw = {}
    for t, kind, n in events:
        if kind == "on":
            raw.setdefault(round(t, 2), []).append(n)
    return [raw[k] for k in sorted(raw)]


def mono_ratio(events):
    """Fraccion de momentos con una sola nota (las octavas cuentan como una)."""
    m = _moments(events)
    return sum(len({n % 12 for n in v}) == 1 for v in m) / len(m) if m else 1.0


def track_scores(path):
    """Puntaje de 'que tan melodia es' cada pista: en rango, una nota por vez, por grados."""
    tracks = note_tracks(path)
    moms = {i: _moments(load_midi_events(path, [i], 0)) for i, _, _ in tracks}
    maxm = max((len(m) for m in moms.values()), default=1) or 1
    scores = {}
    for i, m in moms.items():
        if not m:
            continue
        ons = [n for v in m for n in v]
        inr = sum(LOW <= n <= HIGH for n in ons) / len(ons)
        mono = sum(len({n % 12 for n in v}) == 1 for v in m) / len(m)
        tops = [max(v) for v in m]
        step = sum(abs(b - a) <= 4 for a, b in zip(tops, tops[1:])) / max(1, len(tops) - 1)
        vol = min(1.0, len(m) / (0.3 * maxm))
        scores[i] = (inr * mono * step * vol, inr)
    return scores


def recommend_track(path):
    if len(note_tracks(path)) < 2:
        return None
    s = track_scores(path)
    return max(s, key=lambda i: s[i][0]) if s else None


GAP_FILL = 0.6  # silencios mas largos que esto se rellenan con otro instrumento


def load_notes(path, track, transpose):
    """Notas con duracion: (inicio, 'on', nota, pista, fin). Empareja cada note_on con su note_off."""
    evs = load_midi_events(path, track, transpose, tagged_out=True)
    last = evs[-1][0] if evs else 0.0
    pending, out = {}, []
    for t, kind, n, i in evs:
        key = (i, n)
        if kind == "on":
            if pending.get(key):  # la misma nota sin cerrar: se corta la anterior
                s = pending[key].pop(0)
                out.append((s, "on", n, i, t))
            pending.setdefault(key, []).append(t)
        elif pending.get(key):
            s = pending[key].pop(0)
            out.append((s, "on", n, i, t))
    for (i, n), starts in pending.items():
        for s in starts:
            out.append((s, "on", n, i, max(last, s + 0.25)))
    out.sort(key=lambda e: e[0])
    return out


def fill_gaps(path, primary, transpose):
    """Notas de las pistas 'primary' + relleno de los silencios largos con la mejor
    pista que este sonando en ese momento (los bajos quedan como ultima opcion)."""
    evs = load_notes(path, primary, transpose)
    allev = load_notes(path, None, transpose)
    all_on = [e[0] for e in allev if e[1] == "on"]
    if not all_on:
        return evs
    sc = track_scores(path)
    others = [i for i in sc if i not in primary]
    others.sort(key=lambda i: (sc[i][1] >= 0.3, sc[i][0]), reverse=True)  # bajos al final

    added = []
    for _ in range(4):  # varias pasadas: un relleno puede dejar huecos mas chicos
        marks = sorted({e[0] for e in evs + added if e[1] == "on"})
        bounds = [min(all_on) - 0.001] + marks + [max(all_on) + 0.001]
        new = []
        for a, b in zip(bounds, bounds[1:]):
            if b - a <= GAP_FILL:
                continue
            lo, hi = a + 0.05, b - 0.05
            for i in others:
                ons = [e for e in allev if e[3] == i and e[1] == "on" and lo < e[0] < hi]
                if ons:
                    new += ons
                    break
        if not new:
            break
        added += new
    return sorted(evs + added, key=lambda e: e[0])


def recommend_accomp(path, mel):
    """Pista de acompanamiento: acordes, cubre toda la cancion, sin saturar. None si no hay."""
    evs_all = load_midi_events(path, None, 0)
    if not evs_all:
        return None
    total = max(e[0] for e in evs_all) or 1
    best, best_s = None, 0.05  # umbral minimo para que valga la pena
    for i, _, _ in note_tracks(path):
        if i == mel:
            continue
        ev = load_midi_events(path, [i], 0)
        m = _moments(ev)
        ons_t = [e[0] for e in ev if e[1] == "on"]
        if not m or not ons_t:
            continue
        span = ons_t[-1] - ons_t[0]
        notes = [n for v in m for n in v]
        inr = sum(LOW <= n <= HIGH for n in notes) / len(notes)
        poly = sum(len({n % 12 for n in v}) >= 2 for v in m) / len(m)
        dens = len(m) / max(span, 1)
        s = poly * (span / total) * (0.5 + 0.5 * inr) / max(dens, 1)
        if s > best_s:
            best, best_s = i, s
    return best


def ask(prompt, default, cast):
    """Pregunta hasta recibir algo valido. Enter = default. Acepta coma decimal."""
    while True:
        raw = input(prompt).strip().replace(",", ".")
        if not raw:
            return default
        try:
            return cast(raw)
        except ValueError:
            print("  Valor invalido, proba de nuevo.")


def list_tracks(path):
    import mido

    mid = mido.MidiFile(path, clip=True)
    for i, tr in enumerate(mid.tracks):
        notes = sum(1 for m in tr if m.type == "note_on" and m.velocity > 0)
        print(f"[{i}] {tr.name or '(sin nombre)'} - {notes} notas")


CHORD_WINDOW = 0.03  # notas que arrancan con <30 ms de diferencia = mismo acorde
MIN_GAP = 3          # semitonos minimos entre notas de un acorde (evita sonido "doble")


def clean_chord(notes, max_notes, min_gap=MIN_GAP, mel_notes=None):
    """Ajusta al rango, saca duplicados y notas pegadas, limita la cantidad.
    Prioridad: melodia (la nota mas aguda, o la de la pista de melodia si se indica),
    despues el bajo, despues el resto. El acompanamiento nunca tapa a la melodia."""
    acc = sorted({fold(n) for n in notes}, reverse=True)  # agudo -> grave
    if mel_notes:
        melody = max(fold(n) for n in mel_notes)
        acc = [n for n in acc if n < melody]
    elif acc:
        melody, acc = acc[0], acc[1:]
    else:
        return []
    order = [melody] + ([acc[-1]] if acc else []) + acc[:-1]
    kept = []
    for n in order:
        if len(kept) >= max_notes:
            break
        if n not in kept and all(abs(n - k) >= min_gap for k in kept):
            kept.append(n)
    return kept


def build_chords(events, max_notes, min_gap=MIN_GAP, mel_track=None, with_end=False):
    """Agrupa notas simultaneas en acordes. Si mel_track se indica, los eventos
    deben venir con indice de pista y esa pista manda como melodia.
    Con with_end=True (eventos de load_notes) cada nota sale como (altura, fin)."""
    onsets = [e for e in events if e[1] == "on"]
    chords, cur, cur_t = [], [], None

    def flush():
        notes = [e[2] for e in cur]
        mel = [e[2] for e in cur if mel_track is not None and e[3] == mel_track]
        kept = clean_chord(notes, max_notes, min_gap, mel or None)
        if with_end:
            kept = [(p, max(e[4] for e in cur if fold(e[2]) == p)) for p in kept]
        chords.append((cur_t, kept))

    for e in onsets:
        if cur_t is not None and e[0] - cur_t > CHORD_WINDOW:
            flush()
            cur = []
        if not cur:
            cur_t = e[0]
        cur.append(e)
    if cur:
        flush()
    return [(t, n) for t, n in chords if n]


TAP = 0.04       # duracion de un toque corto (modo sin mantener)
MIN_HOLD = 0.03  # minimo que se mantiene una tecla para que el juego la registre
REPRESS = 0.012  # pausa entre soltar y volver a apretar la misma tecla


def schedule(chords, max_notes, min_gap, hold):
    """Convierte acordes [(t, [(altura, fin)])] en acciones [(t, 0=soltar/1=apretar, tecla)].
    Al mantener notas: se sueltan antes las que choquen con una nota nueva (misma tecla
    o muy pegadas) y nunca hay mas teclas apretadas que max_notes."""
    held = {}  # altura -> (t_soltar, t_apretada)
    acts = []

    def release(p, t):
        acts.append((t, 0, KEYS[p - LOW]))
        del held[p]

    for t, items in chords:
        for p in [p for p, (rel, _) in held.items() if rel <= t]:
            release(p, held[p][0])
        new = [p for p, _ in items]
        for p in list(held):
            if any(abs(p - q) < max(min_gap, 1) for q in new):
                release(p, t)
        while held and len(held) + len(new) > max_notes:
            oldest = min(held, key=lambda p: held[p][1])
            release(oldest, t)
        for p, end in items:
            rel = max(t + MIN_HOLD, end) if hold else t + TAP
            held[p] = (rel, t)
            acts.append((t, 1, KEYS[p - LOW]))
    for p in list(held):
        release(p, held[p][0])
    acts.sort(key=lambda a: (a[0], a[1]))
    return acts


def play_midi(path, track, speed, transpose, max_notes=3, min_gap=MIN_GAP, mel_track=None,
              fill=False, hold=True):
    if fill and track:
        notes = fill_gaps(path, track, transpose)
    else:
        notes = load_notes(path, track, transpose)
    chords = build_chords(notes, max_notes, min_gap, mel_track, with_end=True)
    if not chords:
        print("No hay notas para tocar con esa configuracion.")
        return
    t0 = chords[0][0]  # saltea el silencio inicial
    chords = [(t - t0, [(p, e - t0) for p, e in items]) for t, items in chords]
    acts = schedule(chords, max_notes, min_gap, hold)

    countdown()
    down = set()
    start = time.perf_counter()
    try:
        i = 0
        while i < len(acts):
            if stopped():
                break
            t = acts[i][0]
            wait = t / speed - (time.perf_counter() - start)
            if wait > 0:
                time.sleep(wait)
            released = set()
            while i < len(acts) and acts[i][0] == t:
                _, kind, k = acts[i]
                if kind == 0:
                    if k in down:
                        keyboard.release(k)
                        down.discard(k)
                        released.add(k)
                else:
                    if k in released:
                        time.sleep(REPRESS)
                        released.discard(k)
                    if k in down:
                        keyboard.release(k)
                        time.sleep(REPRESS)
                    keyboard.press(k)
                    down.add(k)
                i += 1
    finally:
        for k in down:
            keyboard.release(k)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?", help="archivo .mid o .txt (o arrastralo sobre el .exe)")
    ap.add_argument("--track", type=int, default=None, help="pista MIDI a tocar")
    ap.add_argument("--list", action="store_true", help="listar pistas del MIDI")
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 normal, 0.8 mas lento")
    ap.add_argument("--transpose", type=int, default=0, help="semitonos (+/-)")
    ap.add_argument("--max-notes", type=int, default=3, help="notas por acorde (1 = solo melodia)")
    a = ap.parse_args()
    if not a.file:
        return menu(a)

    if a.list:
        if not a.file.lower().endswith((".mid", ".midi")):
            sys.exit("--list solo sirve con .mid")
        return list_tracks(a.file)
    play(a.file, a.track, a.speed, a.transpose, a.max_notes)
    print("Fin.")


def app_dir():
    base = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    return os.path.dirname(base)


def play(path, track, speed, transpose, max_notes=3, min_gap=MIN_GAP, mel_track=None, fill=False,
         hold=True):
    if path.lower().endswith((".mid", ".midi")):
        play_midi(path, track, speed, transpose, max_notes, min_gap, mel_track, fill, hold)
    else:
        play_text(path, speed, transpose)


def menu(a):
    """Lista los .mid/.txt de la carpeta "midis" (al lado del programa) y deja elegir."""
    folder = os.path.join(app_dir(), SONGS_DIR)
    os.makedirs(folder, exist_ok=True)
    while True:
        files = sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith((".mid", ".midi", ".txt"))
        )
        print(f"\n=== Canciones en: {folder} ===")
        if not files:
            print(f"No hay canciones. Pone tus archivos .mid en la carpeta:\n  {folder}\ny volve a abrir el programa.")
            input("Enter para cerrar...")
            return
        for i, f in enumerate(files, 1):
            print(f"  [{i}] {f}")
        sel = input("\nNumero de cancion (Enter = salir): ").strip()
        if not sel:
            return
        if not sel.isdigit() or not 1 <= int(sel) <= len(files):
            print("Numero invalido.")
            continue
        path = os.path.join(folder, files[int(sel) - 1])
        try:
            if path.lower().endswith((".mid", ".midi")):
                cfg = midi_options(path)
                if cfg is None:
                    continue
                play(path, **cfg)
            else:
                play(path, None, a.speed, a.transpose)
        except Exception as e:
            print("Error:", e)
        print("Fin.")


SONGS_DIR = "midis"  # carpeta de canciones, al lado del .exe
ALL = 99    # "todas las notas"
HOLD = True  # mantener cada tecla apretada lo que dura la nota (se cambia con M en el menu)


def midi_options(path):
    """Muestra modos faciles para el MIDI elegido. Devuelve kwargs para play() o None."""
    tracks = note_tracks(path)
    names = {i: name for i, name, _ in tracks}
    multi = len(tracks) > 1
    mel = recommend_track(path) if multi else None
    acc = recommend_accomp(path, mel) if multi else None
    base = dict(speed=1.0, transpose=0)

    opts = []  # (texto, kwargs)
    if multi:
        opts.append((f"Solo melodia             - pista {mel} ({names[mel]}), una nota a la vez, sin silencios",
                     dict(track=[mel], max_notes=1, min_gap=MIN_GAP, mel_track=None, fill=True)))
        if acc is not None:
            opts.append((f"Melodia + acompanamiento - pista {mel} + pista {acc} ({names[acc]}), hasta 3 notas",
                         dict(track=[mel, acc], max_notes=3, min_gap=MIN_GAP, mel_track=mel, fill=True)))
        opts.append((f"Banda completa ordenada  - todas las pistas, melodia arriba, hasta 3 notas",
                     dict(track=None, max_notes=3, min_gap=MIN_GAP, mel_track=mel)))
        opts.append(("Todas las notas          - todo el MIDI sin filtrar (puede sonar sucio)",
                     dict(track=None, max_notes=ALL, min_gap=1, mel_track=None)))
        rec = 1 if acc is not None else 0
    else:
        solo = mono_ratio(load_midi_events(path, None, 0)) >= 0.9
        opts.append(("Solo melodia             - una nota a la vez",
                     dict(track=None, max_notes=1, min_gap=MIN_GAP, mel_track=None)))
        opts.append(("Melodia + bajo           - 2 notas",
                     dict(track=None, max_notes=2, min_gap=MIN_GAP, mel_track=None)))
        opts.append(("Equilibrada              - melodia, bajo y una del medio (3 notas)",
                     dict(track=None, max_notes=3, min_gap=MIN_GAP, mel_track=None)))
        opts.append(("Todas las notas          - todo el MIDI sin filtrar (puede sonar sucio)",
                     dict(track=None, max_notes=ALL, min_gap=1, mel_track=None)))
        rec = 0 if solo else 2

    global HOLD
    custom = len(opts) + 1
    while True:
        print(f"\n--- {os.path.basename(path)} ---")
        for n, (txt, _) in enumerate(opts, 1):
            star = "   <- RECOMENDADA" if n - 1 == rec else ""
            print(f"  [{n}] {txt}{star}")
        print(f"  [{custom}] Personalizado            - elegir pistas, notas, velocidad y tono")
        estado = "SI (cada nota dura lo que dura en el MIDI)" if HOLD else "NO (toques cortos)"
        print(f"  [M] Mantener notas: {estado}  -> escribi M para cambiar")
        print("  Extras despues del modo (separados por coma):")
        print("    ,1 ,2 ,3 ... ,T  = maximo de notas por acorde   (ej: 2,1)")
        print("    ,12 / ,-12       = una fila mas aguda / mas grave (ej: 2,-12)")
        print("    combinados       = ej: 2,1,12 (1 nota y una fila mas aguda)")
        raw = input("Modo (Enter = volver a la lista): ").strip().lower().replace(" ", "")
        if not raw:
            return None
        if raw == "m":
            HOLD = not HOLD
            continue
        parts = raw.split(",")
        ch, extras = parts[0], [x for x in parts[1:] if x]
        override, shift, error = None, None, None
        for x in extras:
            if x in ("12", "+12", "-12"):
                if shift is not None:
                    error = "pusiste dos veces el cambio de fila."
                shift = -12 if x == "-12" else 12
            elif x == "t":
                if override:
                    error = "pusiste dos veces la cantidad de notas."
                override = (ALL, 1)
            elif x.isdigit() and 1 <= int(x) <= 11:
                if override:
                    error = "pusiste dos veces la cantidad de notas."
                override = (int(x), MIN_GAP)
            else:
                error = f"'{x}' no es valido. Despues de la coma va 1-11, T, 12 o -12."
        if len(extras) > 2:
            error = "como maximo dos extras: notas y fila (ej 2,1,12)."
        if error:
            print("  " + error)
            continue
        if ch.isdigit() and 1 <= int(ch) <= custom:
            break
        print("  Opcion invalida.")
    if int(ch) < custom:
        cfg = dict(base, hold=HOLD, **opts[int(ch) - 1][1])
        resumen = []
        if override:
            cfg["max_notes"], cfg["min_gap"] = override
            resumen.append("todas las notas" if override[0] == ALL else f"maximo {override[0]} nota(s) por acorde")
        if shift is not None:
            cfg["transpose"] = shift
            resumen.append("una fila mas aguda" if shift > 0 else "una fila mas grave")
        if resumen:
            print(f"  -> Modo {ch} con " + " y ".join(resumen) + ".")
        return cfg

    # ---- Personalizado ----
    track, mel_track = None, None
    if multi:
        print("\nInstrumentos (la bateria se ignora sola):")
        for i, name, n in tracks:
            tag = "  <- melodia" if i == mel else ("  <- acompanamiento" if i == acc else "")
            print(f"  [{i}] {name} - {n} notas{tag}")
        valid = set(names)
        while True:
            ts = input("Pistas, ej: 3  o  3,1  (T = todas): ").strip().lower()
            if ts == "t":
                break
            picks = [int(x) for x in ts.replace(" ", "").split(",") if x.isdigit()]
            if picks and all(p in valid for p in picks):
                track = picks
                break
            print("  Pista invalida.")
        if (track is None or mel in track) and (track is None or len(track) > 1):
            mel_track = mel
    while not override:
        mn = input("Notas por acorde: 1, 2, 3 ... o T = todas: ").strip().lower()
        if mn == "t":
            max_notes, min_gap = ALL, 1
            break
        if mn.isdigit() and int(mn) >= 1:
            max_notes, min_gap = int(mn), MIN_GAP
            break
        print("  Valor invalido.")
    if override:
        max_notes, min_gap = override
    speed = ask("Velocidad (1 = normal, 0.8 = mas lento) [Enter = 1]: ", 1.0, float)
    if shift is not None:
        transpose = shift
    else:
        transpose = ask("Transponer: 12 = una fila mas aguda, -12 = una fila mas grave [Enter = igual]: ",
                        0, int)
    return dict(track=track, speed=speed, transpose=transpose, max_notes=max_notes,
                min_gap=min_gap, mel_track=mel_track, hold=HOLD)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e)
        input("Enter para cerrar...")
