"""
Rhythm Game - Core Prototype
-----------------------------
Controls (menu):   UP/DOWN or W/S to pick a chart, ENTER to play, ESC to quit.
Controls (game):    D F J K by default to hit notes in lanes 0-3.
                    SPACE starts the song, R restarts, ESC returns to the menu.

Settings:
    - Rebind all four lane keys
    - Change note scroll speed
    - Change each lane's note/slot colour

Run: python main.py [charts/sample_chart.json]
"""

import sys
import os
import json
import math
import random
import glob
import zipfile
import shutil
import tempfile
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import pygame

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCREEN_W, SCREEN_H = 1280, 720
FPS = 60

DEFAULT_LANE_KEYS = [pygame.K_d, pygame.K_f, pygame.K_j, pygame.K_k]
DEFAULT_LANE_KEY_LABELS = ["D", "F", "J", "K"]
DEFAULT_LANE_COLORS = [(255, 90, 90), (255, 200, 70), (100, 220, 255), (170, 120, 255)]
LANE_COUNT = 4
LANE_WIDTH = 130
LANE_GAP = 12
NOTE_HEIGHT = 28

HIT_LINE_Y = SCREEN_H - 120
DEFAULT_NOTE_SPEED = 500.0

# Timing windows (ms) relative to the note's exact hit time
WINDOW_PERFECT = 45
WINDOW_GREAT = 90
WINDOW_GOOD = 140
WINDOW_MISS = 180

JUDGMENT_COLORS = {
    "PERFECT": (255, 240, 130),
    "GREAT": (120, 255, 150),
    "GOOD": (100, 200, 255),
    "MISS": (255, 80, 80),
}

JUDGMENT_INTENSITY = {"PERFECT": 1.0, "GREAT": 0.75, "GOOD": 0.5, "MISS": 0.35}
SCORE_VALUES = {"PERFECT": 1000, "GREAT": 700, "GOOD": 300, "MISS": 0}

RECEPTOR_SIZE = LANE_WIDTH - 12  # exactly matches the visible note width
JUDGMENT_POP_MS = 550
RECEPTOR_JUDGE_MS = 260
PRESS_FLASH_MS = 110
COMBO_PULSE_MS = 180
HEALTH_MAX = 100.0

# Colour presets. The settings screen cycles through these with LEFT/RIGHT.
COLOR_PRESETS = [
    (255, 90, 90),
    (255, 140, 70),
    (255, 200, 70),
    (170, 255, 90),
    (80, 230, 150),
    (70, 220, 255),
    (100, 150, 255),
    (170, 120, 255),
    (230, 100, 255),
    (255, 100, 180),
    (255, 255, 255),
]

SPEED_PRESETS = [250, 325, 400, 500, 600, 725, 850, 1000]


def lane_x(lane_index):
    total_width = LANE_COUNT * LANE_WIDTH + (LANE_COUNT - 1) * LANE_GAP
    start_x = (SCREEN_W - total_width) // 2
    return start_x + lane_index * (LANE_WIDTH + LANE_GAP)


def lane_center_x(lane_index):
    return lane_x(lane_index) + LANE_WIDTH // 2


def ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    t = max(0.0, min(1.0, t))
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))


def key_name(key):
    """Return a clean, human-readable name for a pygame key."""
    name = pygame.key.name(key)
    if len(name) == 1:
        return name.upper()
    replacements = {
        "space": "SPACE",
        "return": "ENTER",
        "left shift": "L-SHIFT",
        "right shift": "R-SHIFT",
        "left ctrl": "L-CTRL",
        "right ctrl": "R-CTRL",
        "left alt": "L-ALT",
        "right alt": "R-ALT",
    }
    return replacements.get(name, name.upper())


# ---------------------------------------------------------------------------
# Small visual helpers
# ---------------------------------------------------------------------------
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "radius")

    def __init__(self, x, y, vx, vy, life_ms, color, radius):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life_ms
        self.max_life = life_ms
        self.color = color
        self.radius = radius

    def update(self, dt):
        self.x += self.vx * dt / 1000.0
        self.y += self.vy * dt / 1000.0
        self.vy += 400 * dt / 1000.0
        self.life -= dt
        return self.life > 0

    def draw(self, surface):
        if self.life <= 0:
            return
        t = max(0.0, self.life / self.max_life)
        alpha = int(255 * t)
        r = max(1, int(self.radius * (0.4 + 0.6 * t)))
        s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color, alpha), (r, r), r)
        surface.blit(s, (self.x - r, self.y - r))


def spawn_burst(particles, x, y, color, intensity=1.0, count=None):
    count = count or int(8 + 10 * intensity)
    for _ in range(count):
        angle = random.uniform(0, math.tau)
        speed = random.uniform(60, 220) * (0.5 + 0.5 * intensity)
        vx = math.cos(angle) * speed
        vy = math.sin(angle) * speed - 60
        life = random.uniform(280, 520)
        radius = random.uniform(2, 5) * (0.6 + 0.6 * intensity)
        particles.append(Particle(x, y, vx, vy, life, color, radius))


def draw_glow_rect(surface, rect, color, glow_px=14, radius=8, base_alpha=90):
    x, y, w, h = rect
    layers = 4
    for i in range(layers, 0, -1):
        pad = int(glow_px * i / layers)
        alpha = int(base_alpha * (1 - i / (layers + 1)))
        glow_surf = pygame.Surface((max(1, int(w + pad * 2)), max(1, int(h + pad * 2))), pygame.SRCALPHA)
        pygame.draw.rect(
            glow_surf, (*color, alpha), (0, 0, int(w + pad * 2), int(h + pad * 2)),
            border_radius=radius + pad // 2
        )
        surface.blit(glow_surf, (int(x - pad), int(y - pad)))


def draw_text_centered(surface, font, text, color, cx, cy, scale=1.0, alpha=255):
    base = font.render(text, True, color)
    if scale != 1.0:
        w = max(1, int(base.get_width() * scale))
        h = max(1, int(base.get_height() * scale))
        base = pygame.transform.smoothscale(base, (w, h))
    if alpha < 255:
        base = base.copy()
        base.set_alpha(alpha)
    surface.blit(base, (cx - base.get_width() // 2, cy - base.get_height() // 2))
    return base.get_rect(center=(cx, cy))


# ---------------------------------------------------------------------------
# Chart / Note data
# ---------------------------------------------------------------------------
class Note:
    __slots__ = ("time_ms", "lane", "hit", "judged", "missed", "pop_start")

    def __init__(self, time_ms, lane):
        self.time_ms = time_ms
        self.lane = lane
        self.hit = False
        self.judged = False
        self.missed = False
        self.pop_start = None


class Chart:
    def __init__(self, path):
        with open(path, "r") as f:
            data = json.load(f)
        self.title = data.get("title", "Untitled")
        self.song_path = data.get("song")
        self.offset_ms = data.get("offset_ms", 0)
        self.notes = [Note(n["time_ms"], n["lane"]) for n in data["notes"]]
        self.notes.sort(key=lambda n: n.time_ms)


def scan_charts(charts_dir):
    found = []
    if os.path.isdir(charts_dir):
        for path in sorted(glob.glob(os.path.join(charts_dir, "*.json"))):
            title = os.path.basename(path)
            note_count = 0
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                title = data.get("title", title)
                note_count = len(data.get("notes", []))
            except (json.JSONDecodeError, OSError):
                pass
            found.append({"path": path, "title": title, "note_count": note_count})
    return found


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, chart_path=None, charts_dir=None):
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            pass

        self.fullscreen = False
        self.display_flags = pygame.SCALED | pygame.RESIZABLE
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), self.display_flags)
        pygame.display.set_caption("Rhythm Game")
        self.clock = pygame.time.Clock()
        self.font_title = pygame.font.SysFont("arial", 64, bold=True)
        self.font_big = pygame.font.SysFont("arial", 50, bold=True)
        self.font_med = pygame.font.SysFont("arial", 30, bold=True)
        self.font_small = pygame.font.SysFont("arial", 20)
        self.font_judgment = pygame.font.SysFont("arial", 44, bold=True)

        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.charts_dir = charts_dir or os.path.join(self.base_dir, "charts")
        self.assets_dir = os.path.join(self.base_dir, "assets")
        os.makedirs(self.assets_dir, exist_ok=True)
        # Main menu music: MP3 file stored in assets/.
        self.menu_music_path = self._find_asset((
            "main_menu_music.mp3",
        ))
        self.select_sound = self._load_sound_asset((
            "select.ogg", "select.wav", "select.mp3", "select.flac",
            "menu_select.ogg", "menu_select.wav",
        ))
        self.menu_music_loaded = False
        self.menu_music_start_ticks = None
        self.background_cubes = []
        self.background_cube_spawn_accumulator = 0.0
        self.available_charts = scan_charts(self.charts_dir)
        self.menu_index = 0
        self.main_menu_items = ["SONGS", "SETTINGS", "CHART EDITOR", "EXIT GAME"]
        self.menu_screen = "main"
        self.time_ms = 0
        self._last_dt = 0

        # User settings. These stay in memory for the session and apply immediately.
        self.lane_keys = DEFAULT_LANE_KEYS.copy()
        self.lane_key_labels = DEFAULT_LANE_KEY_LABELS.copy()
        self.lane_colors = DEFAULT_LANE_COLORS.copy()
        self.note_speed = DEFAULT_NOTE_SPEED

        self.settings_index = 0
        self.rebinding_lane = None
        self.color_indices = [COLOR_PRESETS.index(c) if c in COLOR_PRESETS else 0 for c in self.lane_colors]
        self.speed_index = SPEED_PRESETS.index(DEFAULT_NOTE_SPEED)

        self.bg_surface = self._build_background()
        self.particles = []
        self.receptor_press = [0] * LANE_COUNT
        self.receptor_judge = [0] * LANE_COUNT
        self.receptor_judge_color = [(255, 255, 255)] * LANE_COUNT
        self.last_judgment = None
        self.last_judgment_start = None
        self.combo_pulse_start = None
        self._prev_combo = 0

        self.state = "menu"
        self.chart_path = None

        # Chart editor state. The editor keeps its notes in memory until exported.
        self.editor_notes = []
        self.editor_title = "Untitled Chart"
        self.editor_song_path = None
        self.editor_audio_loaded = False
        self.editor_audio_length_ms = 0
        self.editor_playing = False
        self.editor_start_ticks = None
        self.editor_pause_ms = 0
        self.editor_cursor_ms = 0
        self.editor_return_after_playtest = False
        self.pause_time_ms = 0
        self.pause_started_ticks = None
        self.pause_reason = ""

        if chart_path and os.path.exists(chart_path):
            self.chart_path = chart_path
            self.load_chart()
            self.state = "playing"
        else:
            self.play_menu_music()

    def _find_asset(self, filenames):
        for filename in filenames:
            path = os.path.join(self.assets_dir, filename)
            if os.path.isfile(path):
                return path
        return None

    def _load_sound_asset(self, filenames):
        path = self._find_asset(filenames)
        if not path:
            return None
        try:
            return pygame.mixer.Sound(path)
        except pygame.error:
            return None

    def play_select_sound(self):
        if self.select_sound is not None:
            try:
                self.select_sound.play()
            except pygame.error:
                pass

    def play_menu_music(self):
        if not self.menu_music_path:
            return
        try:
            # Always load the menu track again. Gameplay/editor audio uses
            # pygame.mixer.music as the same single music channel, so simply
            # calling play(-1) here could replay the last level's song.
            pygame.mixer.music.load(self.menu_music_path)
            pygame.mixer.music.play(-1)
            self.menu_music_start_ticks = pygame.time.get_ticks()
            self.background_cubes.clear()
            self.background_cube_spawn_accumulator = 0.0
            self.menu_music_loaded = True
        except pygame.error:
            self.menu_music_loaded = False

    def _build_background(self):
        surf = pygame.Surface((SCREEN_W, SCREEN_H))
        top = (16, 16, 28)
        bottom = (8, 8, 14)
        for y in range(SCREEN_H):
            t = y / SCREEN_H
            pygame.draw.line(surf, lerp_color(top, bottom, t), (0, y), (SCREEN_W, y))
        return surf

    # -- display -------------------------------------------------------------
    def toggle_fullscreen(self):
        # The game now uses a 16:9 1280x720 logical canvas. In fullscreen
        # pygame-ce scales that canvas to the monitor's native 1920x1080
        # output, so there are no aspect-ratio bars on a 16:9 display.
        self.fullscreen = not self.fullscreen
        try:
            if self.fullscreen:
                self.screen = pygame.display.set_mode(
                    (SCREEN_W, SCREEN_H), pygame.SCALED | pygame.FULLSCREEN
                )
            else:
                self.screen = pygame.display.set_mode(
                    (SCREEN_W, SCREEN_H), pygame.SCALED | pygame.RESIZABLE
                )
        except pygame.error:
            self.fullscreen = False
            try:
                self.screen = pygame.display.set_mode(
                    (SCREEN_W, SCREEN_H), pygame.SCALED | pygame.RESIZABLE
                )
            except pygame.error:
                pass

    # -- chart loading -------------------------------------------------------
    def load_chart(self):
        self.chart = Chart(self.chart_path)
        self.score = 0
        self.combo = 0
        self.max_combo = 0
        self.judgment_counts = {"PERFECT": 0, "GREAT": 0, "GOOD": 0, "MISS": 0}
        self.last_judgment = None
        self.last_judgment_start = None
        self.combo_pulse_start = None
        self._prev_combo = 0
        self.song_started = False
        self.start_ticks = None
        self.health = HEALTH_MAX
        self.particles = []
        self.receptor_press = [0] * LANE_COUNT
        self.receptor_judge = [0] * LANE_COUNT

        song_full_path = None
        if self.chart.song_path:
            candidate = self.chart.song_path
            if not os.path.isabs(candidate):
                candidate = os.path.join(os.path.dirname(self.chart_path), "..", candidate)
            song_full_path = os.path.normpath(candidate)

        self.has_audio = False
        self.menu_music_loaded = False
        if song_full_path and os.path.exists(song_full_path):
            try:
                pygame.mixer.music.load(song_full_path)
                self.has_audio = True
            except pygame.error:
                self.has_audio = False

    def current_time_ms(self):
        if self.state == "paused":
            return self.pause_time_ms
        if self.start_ticks is None:
            return -9999
        return pygame.time.get_ticks() - self.start_ticks - self.chart.offset_ms

    def start_song(self):
        self.start_ticks = pygame.time.get_ticks()
        if self.has_audio:
            pygame.mixer.music.play()
        self.song_started = True

    def go_to_menu(self):
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.available_charts = scan_charts(self.charts_dir)
        self.rebinding_lane = None
        self.menu_screen = "main"
        self.menu_index = 0
        self.state = "menu"
        self.play_menu_music()

    # -- settings ------------------------------------------------------------
    def settings_items(self):
        return ["KEY 1", "KEY 2", "KEY 3", "KEY 4", "SCROLL SPEED", "COLOUR 1", "COLOUR 2", "COLOUR 3", "COLOUR 4"]

    def cycle_speed(self, direction):
        self.speed_index = (self.speed_index + direction) % len(SPEED_PRESETS)
        self.note_speed = float(SPEED_PRESETS[self.speed_index])

    def cycle_color(self, lane, direction):
        self.color_indices[lane] = (self.color_indices[lane] + direction) % len(COLOR_PRESETS)
        self.lane_colors[lane] = COLOR_PRESETS[self.color_indices[lane]]

    def handle_settings_key(self, key):
        if self.rebinding_lane is not None:
            if key == pygame.K_ESCAPE:
                self.rebinding_lane = None
                return True
            # Prevent one physical key from controlling multiple lanes.
            if key not in self.lane_keys:
                self.lane_keys[self.rebinding_lane] = key
                self.lane_key_labels[self.rebinding_lane] = key_name(key)
                self.rebinding_lane = None
            return True

        items = self.settings_items()
        if key in (pygame.K_UP, pygame.K_w):
            self.settings_index = (self.settings_index - 1) % len(items)
        elif key in (pygame.K_DOWN, pygame.K_s):
            self.settings_index = (self.settings_index + 1) % len(items)
        elif key in (pygame.K_LEFT, pygame.K_a):
            if 4 == self.settings_index:
                self.cycle_speed(-1)
            elif self.settings_index >= 5:
                self.cycle_color(self.settings_index - 5, -1)
        elif key in (pygame.K_RIGHT, pygame.K_d):
            if 4 == self.settings_index:
                self.cycle_speed(1)
            elif self.settings_index >= 5:
                self.cycle_color(self.settings_index - 5, 1)
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.settings_index < 4:
                self.rebinding_lane = self.settings_index
            elif self.settings_index == 4:
                self.cycle_speed(1)
            else:
                self.cycle_color(self.settings_index - 5, 1)
        elif key == pygame.K_ESCAPE:
            self.state = "menu"
        return True

    # -- pause ---------------------------------------------------------------
    def pause_game(self):
        if self.state != "playing" or not self.song_started:
            return
        self.pause_time_ms = self.current_time_ms()
        self.pause_started_ticks = pygame.time.get_ticks()
        try:
            pygame.mixer.music.pause()
        except pygame.error:
            pass
        self.state = "paused"

    def resume_game(self):
        if self.state != "paused":
            return
        if self.pause_started_ticks is not None and self.start_ticks is not None:
            paused_duration = pygame.time.get_ticks() - self.pause_started_ticks
            self.start_ticks += paused_duration
        try:
            pygame.mixer.music.unpause()
        except pygame.error:
            pass
        self.pause_started_ticks = None
        self.state = "playing"

    # -- chart editor --------------------------------------------------------
    def _tk_root(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        return root

    def choose_editor_song(self):
        root = self._tk_root()
        path = filedialog.askopenfilename(
            parent=root,
            title="Choose a song",
            filetypes=[
                ("Audio files", "*.wav *.ogg *.mp3 *.flac"),
                ("WAV", "*.wav"),
                ("OGG", "*.ogg"),
                ("MP3", "*.mp3"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        if not path:
            return
        try:
            pygame.mixer.music.load(path)
        except pygame.error as exc:
            root = self._tk_root()
            messagebox.showerror("Song could not be loaded", str(exc), parent=root)
            root.destroy()
            return

        self.editor_song_path = os.path.abspath(path)
        self.editor_audio_loaded = True
        try:
            sound = pygame.mixer.Sound(self.editor_song_path)
            self.editor_audio_length_ms = max(1000, int(sound.get_length() * 1000))
            del sound
        except pygame.error:
            self.editor_audio_length_ms = 0
        self.editor_cursor_ms = 0
        self.editor_playing = False
        self.editor_pause_ms = 0

        if self.editor_title == "Untitled Chart":
            self.editor_title = os.path.splitext(os.path.basename(path))[0]

    def start_editor_audio(self):
        if not self.editor_audio_loaded or not self.editor_song_path:
            return
        try:
            pygame.mixer.music.load(self.editor_song_path)
            pygame.mixer.music.play()
            self.editor_start_ticks = pygame.time.get_ticks() - self.editor_cursor_ms
            self.editor_playing = True
        except pygame.error:
            self.editor_playing = False

    def stop_editor_audio(self):
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.editor_playing = False
        self.editor_start_ticks = None

    def editor_time_ms(self):
        if not self.editor_playing or self.editor_start_ticks is None:
            return self.editor_cursor_ms
        self.editor_cursor_ms = max(0, pygame.time.get_ticks() - self.editor_start_ticks)
        if self.editor_audio_length_ms:
            self.editor_cursor_ms = min(self.editor_cursor_ms, self.editor_audio_length_ms)
            if self.editor_cursor_ms >= self.editor_audio_length_ms:
                self.stop_editor_audio()
        return self.editor_cursor_ms

    def add_editor_note(self, lane):
        t = int(round(self.editor_time_ms() / 10.0) * 10)
        t = max(0, t)
        if not any(n["time_ms"] == t and n["lane"] == lane for n in self.editor_notes):
            self.editor_notes.append({"time_ms": t, "lane": lane})
            self.editor_notes.sort(key=lambda n: (n["time_ms"], n["lane"]))

    def remove_editor_note(self):
        if not self.editor_notes:
            return
        now = self.editor_time_ms()
        nearest = min(self.editor_notes, key=lambda n: abs(n["time_ms"] - now))
        if abs(nearest["time_ms"] - now) <= 180:
            self.editor_notes.remove(nearest)

    def new_editor(self):
        self.stop_editor_audio()
        self.editor_notes = []
        self.editor_title = "Untitled Chart"
        self.editor_song_path = None
        self.editor_audio_loaded = False
        self.editor_audio_length_ms = 0
        self.editor_cursor_ms = 0
        self.editor_playing = False
        self.state = "editor"

    def open_editor(self):
        self.new_editor()

    def save_editor_zip(self):
        if not self.editor_song_path or not os.path.exists(self.editor_song_path):
            root = self._tk_root()
            messagebox.showwarning("Song required", "Add a song before exporting the chart.", parent=root)
            root.destroy()
            return

        title = self.editor_title.strip() or "Untitled Chart"
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "chart"
        root = self._tk_root()
        out = filedialog.asksaveasfilename(
            parent=root,
            title="Export chart ZIP",
            defaultextension=".zip",
            initialfile=safe_title + ".zip",
            filetypes=[("Chart ZIP", "*.zip")],
        )
        root.destroy()
        if not out:
            return

        song_name = os.path.basename(self.editor_song_path)
        chart_data = {
            "title": title,
            "song": os.path.join("songs", song_name).replace("\\", "/"),
            "offset_ms": 0,
            "notes": sorted(self.editor_notes, key=lambda n: (n["time_ms"], n["lane"])),
        }
        temp_dir = tempfile.mkdtemp(prefix="rhythm_chart_")
        try:
            chart_json = os.path.join(temp_dir, "chart.json")
            with open(chart_json, "w", encoding="utf-8") as f:
                json.dump(chart_data, f, indent=2)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(chart_json, "charts/chart.json")
                z.write(self.editor_song_path, os.path.join("songs", song_name))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def playtest_editor(self):
        if not self.editor_song_path or not os.path.exists(self.editor_song_path):
            return
        temp_path = os.path.join(self.charts_dir, ".editor_playtest.json")
        data = {
            "title": self.editor_title or "Playtest",
            "song": self.editor_song_path,
            "offset_ms": 0,
            "notes": self.editor_notes,
        }
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.chart_path = temp_path
            self.load_chart()
            self.editor_return_after_playtest = True
            self.state = "playing"
        except OSError:
            pass

    def handle_editor_key(self, key):
        if key == pygame.K_ESCAPE:
            self.stop_editor_audio()
            self.state = "menu"
        elif key == pygame.K_c:
            self.choose_editor_song()
        elif key == pygame.K_t:
            self.playtest_editor()
        elif key == pygame.K_RETURN:
            if not self.editor_playing:
                self.start_editor_audio()
        elif key == pygame.K_SPACE:
            if self.editor_playing:
                self.stop_editor_audio()
            else:
                self.start_editor_audio()
        elif key == pygame.K_BACKSPACE:
            self.remove_editor_note()
        elif key == pygame.K_s:
            self.save_editor_zip()
        elif key == pygame.K_n:
            root = self._tk_root()
            title = simpledialog.askstring("Chart title", "Chart name:", initialvalue=self.editor_title, parent=root)
            root.destroy()
            if title is not None and title.strip():
                self.editor_title = title.strip()
        elif key == pygame.K_LEFT:
            self.editor_cursor_ms = max(0, self.editor_time_ms() - 500)
            if self.editor_playing:
                self.stop_editor_audio()
                self.start_editor_audio()
        elif key == pygame.K_RIGHT:
            length = self.editor_audio_length_ms or 300000
            self.editor_cursor_ms = min(length, self.editor_time_ms() + 500)
            if self.editor_playing:
                self.stop_editor_audio()
                self.start_editor_audio()
        elif key in self.lane_keys:
            self.add_editor_note(self.lane_keys.index(key))
        return True

    def draw_editor(self):
        now = self.editor_time_ms()
        pulse = 0.5 + 0.5 * math.sin(self.time_ms / 450.0)

        draw_text_centered(self.screen, self.font_big, "CHART EDITOR", (255, 255, 255), SCREEN_W // 2, 45)
        title = self.font_med.render(self.editor_title, True, self.lane_colors[2])
        self.screen.blit(title, (SCREEN_W // 2 - title.get_width() // 2, 82))

        # Timeline
        left, right = 70, SCREEN_W - 70
        timeline_y = 140
        pygame.draw.line(self.screen, (70, 70, 85), (left, timeline_y), (right, timeline_y), 4)
        duration = max(self.editor_audio_length_ms, 10000)
        for sec in range(0, duration // 1000 + 1, 5):
            x = left + (right-left) * (sec*1000/duration)
            pygame.draw.line(self.screen, (70,70,85), (x,timeline_y-8), (x,timeline_y+8), 2)
            label = self.font_small.render(f"{sec}s", True, (130,130,145))
            self.screen.blit(label, (x-label.get_width()/2, timeline_y+12))
        cursor_x = left + (right-left) * min(1.0, now/duration)
        pygame.draw.line(self.screen, (255,255,255), (cursor_x, timeline_y-18), (cursor_x, timeline_y+18), 3)

        # Four editor lanes
        lane_top = 210
        lane_bottom = 540
        for i in range(4):
            x = lane_x(i)
            color = self.lane_colors[i]
            pygame.draw.rect(self.screen, (25,25,36), (x,lane_top,LANE_WIDTH,lane_bottom-lane_top), border_radius=8)
            pygame.draw.rect(self.screen, color, (x,lane_top,LANE_WIDTH,lane_bottom-lane_top), 2, border_radius=8)
            for n in self.editor_notes:
                if n["lane"] != i:
                    continue
                ny = lane_bottom - ((n["time_ms"] - now) / 1000.0) * 90
                if lane_top-10 <= ny <= lane_bottom+10:
                    pygame.draw.rect(self.screen, color, (x+6, ny, LANE_WIDTH-12, NOTE_HEIGHT), border_radius=6)
                    pygame.draw.rect(self.screen, (255,255,255), (x+6, ny, LANE_WIDTH-12, 3), border_radius=3)
            label = self.font_med.render(self.lane_key_labels[i], True, (255,255,255))
            self.screen.blit(label, (x+LANE_WIDTH/2-label.get_width()/2, lane_bottom+12))

        current = self.font_med.render(f"{now/1000:.2f}s", True, (255,255,255))
        self.screen.blit(current, (20, 20))
        status = "PLAYING" if self.editor_playing else "STOPPED"
        status_s = self.font_small.render(status, True, self.lane_colors[1] if self.editor_playing else (150,150,165))
        self.screen.blit(status_s, (20, 58))
        song = os.path.basename(self.editor_song_path) if self.editor_song_path else "No song selected"
        song_s = self.font_small.render(f"Song: {song}", True, (180,180,195))
        self.screen.blit(song_s, (20, 610))
        count_s = self.font_small.render(f"Notes: {len(self.editor_notes)}", True, (180,180,195))
        self.screen.blit(count_s, (20, 635))
        hint1 = self.font_small.render("C Add song   N Rename   SPACE Play/Pause   D/F/J/K Add note", True, (170,170,185))
        hint2 = self.font_small.render("BACKSPACE Delete nearest   T Playtest   S Export ZIP   ESC Menu", True, (170,170,185))
        self.screen.blit(hint1, (SCREEN_W//2-hint1.get_width()//2, 660))
        self.screen.blit(hint2, (SCREEN_W//2-hint2.get_width()//2, 690))

    def draw_pause(self):
        self.draw_game()
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((5, 5, 12, 205))
        self.screen.blit(overlay, (0, 0))
        draw_glow_rect(self.screen, (SCREEN_W//2-210, 170, 420, 300), self.lane_colors[2], glow_px=22, base_alpha=55)
        pygame.draw.rect(self.screen, (24,24,36), (SCREEN_W//2-210,170,420,300), border_radius=18)
        pygame.draw.rect(self.screen, self.lane_colors[2], (SCREEN_W//2-210,170,420,300), 3, border_radius=18)
        draw_text_centered(self.screen, self.font_title, "PAUSED", (255,255,255), SCREEN_W//2, 225)
        lines = ["ENTER / P  Resume", "R  Restart", "M  Main Menu"]
        y=300
        for line in lines:
            draw_text_centered(self.screen, self.font_med, line, (220,220,230), SCREEN_W//2, y)
            y += 48
        draw_text_centered(self.screen, self.font_small, "This is the pause menu.", (145,145,160), SCREEN_W//2, 435)

    # -- gameplay logic -------------------------------------------------------
    def handle_hit(self, lane):
        self.receptor_press[lane] = PRESS_FLASH_MS

        now = self.current_time_ms()
        best_note = None
        best_diff = None
        for note in self.chart.notes:
            if note.lane != lane or note.judged:
                continue
            diff = abs(note.time_ms - now)
            if diff <= WINDOW_MISS and (best_diff is None or diff < best_diff):
                best_note = note
                best_diff = diff

        if best_note is None:
            return

        if best_diff <= WINDOW_PERFECT:
            judgment = "PERFECT"
        elif best_diff <= WINDOW_GREAT:
            judgment = "GREAT"
        elif best_diff <= WINDOW_GOOD:
            judgment = "GOOD"
        else:
            judgment = "MISS"

        best_note.judged = True
        best_note.hit = judgment != "MISS"
        best_note.pop_start = pygame.time.get_ticks()
        self.register_judgment(judgment, lane=lane)

    def register_judgment(self, judgment, lane=None):
        self.judgment_counts[judgment] += 1
        self.score += SCORE_VALUES[judgment]

        if judgment == "PERFECT":
            self.health = min(HEALTH_MAX, self.health + 1.5)
        elif judgment == "GREAT":
            self.health = min(HEALTH_MAX, self.health + 1.0)
        elif judgment == "GOOD":
            self.health = min(HEALTH_MAX, self.health + 0.25)
        else:
            self.health = max(0.0, self.health - 10.0)

        if judgment == "MISS":
            self.combo = 0
        else:
            self.combo += 1
            self.max_combo = max(self.max_combo, self.combo)

        now = pygame.time.get_ticks()
        self.last_judgment = judgment
        self.last_judgment_start = now
        color = JUDGMENT_COLORS[judgment]

        if lane is not None:
            self.receptor_judge[lane] = RECEPTOR_JUDGE_MS
            self.receptor_judge_color[lane] = color
            cx = lane_center_x(lane)
            intensity = JUDGMENT_INTENSITY[judgment]
            spawn_burst(
                self.particles, cx, HIT_LINE_Y, color,
                intensity=intensity if judgment != "MISS" else 0.3,
                count=None if judgment != "MISS" else 5,
            )

        if self.combo > 0 and self.combo != self._prev_combo:
            self.combo_pulse_start = now
        self._prev_combo = self.combo

    def update(self, dt):
        self.time_ms += dt
        now = self.current_time_ms()
        for note in self.chart.notes:
            if not note.judged and now - note.time_ms > WINDOW_MISS:
                note.judged = True
                note.missed = True
                note.pop_start = pygame.time.get_ticks()
                self.register_judgment("MISS", lane=note.lane)

        for i in range(LANE_COUNT):
            if self.receptor_press[i] > 0:
                self.receptor_press[i] = max(0, self.receptor_press[i] - dt)
            if self.receptor_judge[i] > 0:
                self.receptor_judge[i] = max(0, self.receptor_judge[i] - dt)

        self.particles = [p for p in self.particles if p.update(dt)]

    # -- drawing -------------------------------------------------------------
    def draw(self):
        self.screen.blit(self.bg_surface, (0, 0))
        if self.state == "menu":
            self.draw_menu()
        elif self.state == "settings":
            self.draw_settings()
        elif self.state == "editor":
            self.draw_editor()
        elif self.state == "paused":
            self.draw_pause()
        else:
            self.draw_game()
        pygame.display.flip()

    def _menu_music_elapsed_ms(self):
        # The menu track is 3:12 (192 seconds). Using our own clock keeps the
        # visual effects synchronized even when pygame's music position wraps
        # back to zero at the loop point.
        if self.menu_music_start_ticks is None:
            return self.time_ms % 192000
        return (pygame.time.get_ticks() - self.menu_music_start_ticks) % 192000

    def _update_menu_background(self, dt):
        elapsed = self._menu_music_elapsed_ms()
        seconds = elapsed / 1000.0

        # Music-synced sections:
        # 0:00-1:12  normal
        # 1:12-1:32  more cubes
        # 1:32-1:36  stop spawning
        # 1:36-2:48  lots of cubes
        # 2:48-3:12  slow everything down
        if seconds < 72.0:
            spawn_rate = 1.2
            speed_scale = 1.0
        elif seconds < 92.0:
            spawn_rate = 2.2
            speed_scale = 1.0
        elif seconds < 96.0:
            spawn_rate = 0.0
            speed_scale = 1.0
        elif seconds < 168.0:
            spawn_rate = 8.0
            speed_scale = 1.0
        else:
            spawn_rate = 3.0
            speed_scale = 0.35

        self.background_cube_spawn_accumulator += (dt / 1000.0) * spawn_rate
        while self.background_cube_spawn_accumulator >= 1.0:
            self.background_cube_spawn_accumulator -= 1.0
            lane = random.randrange(LANE_COUNT)
            size = random.randint(22, 34)
            self.background_cubes.append({
                "x": random.randint(25, max(25, SCREEN_W - size - 25)),
                "y": -size - random.randint(0, 80),
                "size": size,
                "speed": random.uniform(85.0, 150.0),
                "drift": random.uniform(-18.0, 18.0),
                "phase": random.random() * math.tau,
                "lane": lane,
            })

        alive = []
        for cube in self.background_cubes:
            cube["y"] += cube["speed"] * speed_scale * dt / 1000.0
            cube["x"] += math.sin(self.time_ms / 700.0 + cube["phase"]) * cube["drift"] * dt / 1000.0
            if cube["y"] < SCREEN_H + cube["size"] + 10:
                alive.append(cube)
        self.background_cubes = alive

    def draw_menu_background(self, show_title=True):
        self.screen.blit(self.bg_surface, (0, 0))
        self._update_menu_background(self._last_dt)

        # Keep a few of the original slow-moving cubes visible at all times.
        for i in range(4):
            cx = 100 + i * 180 + 40 * math.sin(self.time_ms / 1300.0 + i)
            cy = (self.time_ms / 12.0 + i * 160) % (SCREEN_H + 60) - 30
            color = self.lane_colors[i % LANE_COUNT]
            s = pygame.Surface((26, 26), pygame.SRCALPHA)
            pygame.draw.rect(s, (*color, 35), (0, 0, 26, 26), border_radius=6)
            self.screen.blit(s, (cx, cy))

        for cube in self.background_cubes:
            color = self.lane_colors[cube["lane"] % LANE_COUNT]
            size = cube["size"]
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            pygame.draw.rect(s, (*color, 42), (0, 0, size, size), border_radius=6)
            pygame.draw.rect(s, (*color, 95), (2, 2, size - 4, size - 4), 2, border_radius=5)
            self.screen.blit(s, (int(cube["x"]), int(cube["y"])))

        if show_title:
            pulse = 0.5 + 0.5 * math.sin(self.time_ms / 500.0)
            title_color = lerp_color((255, 255, 255), self.lane_colors[2], pulse * 0.4)
            draw_glow_rect(self.screen, (SCREEN_W // 2 - 180, 42, 360, 70), self.lane_colors[2], glow_px=26, base_alpha=50)
            draw_text_centered(self.screen, self.font_title, "RHYTHM GAME", title_color, SCREEN_W // 2, 77)

    def draw_menu(self):
        self.draw_menu_background()
        pulse = 0.5 + 0.5 * math.sin(self.time_ms / 450.0)

        if self.menu_screen == "songs":
            draw_text_centered(self.screen, self.font_big, "SONGS", (245, 245, 255), SCREEN_W // 2, 155)
            draw_text_centered(self.screen, self.font_small, "Choose a chart • ENTER to play • E for chart editor", (170, 170, 185), SCREEN_W // 2, 195)

            if not self.available_charts:
                msg = self.font_med.render("No charts found in charts/", True, (210, 150, 155))
                self.screen.blit(msg, (SCREEN_W // 2 - msg.get_width() // 2, 310))
            else:
                visible = min(5, len(self.available_charts))
                # Keep the selected item near the middle without changing the
                # underlying chart order.
                top = max(0, min(self.menu_index - 2, len(self.available_charts) - visible))
                for row in range(visible):
                    i = top + row
                    entry = self.available_charts[i]
                    y = 245 + row * 70
                    rect = pygame.Rect(SCREEN_W // 2 - 260, y, 520, 58)
                    selected = i == self.menu_index
                    color = self.lane_colors[i % LANE_COUNT]
                    if selected:
                        draw_glow_rect(self.screen, rect, color, glow_px=15, base_alpha=int(55 + 35 * pulse))
                        fill, border, bw = (45, 45, 60), color, 3
                    else:
                        fill, border, bw = (25, 25, 36), (58, 58, 72), 1
                    pygame.draw.rect(self.screen, fill, rect, border_radius=11)
                    pygame.draw.rect(self.screen, border, rect, bw, border_radius=11)
                    title_s = self.font_med.render(entry["title"], True, (255,255,255) if selected else (205,205,215))
                    self.screen.blit(title_s, (rect[0]+18, rect[1]+8))
                    sub_s = self.font_small.render(f'{entry["note_count"]} notes', True, (150,150,165))
                    self.screen.blit(sub_s, (rect[0]+18, rect[1]+36))
                    if selected:
                        arrow = self.font_med.render(">", True, color)
                        self.screen.blit(arrow, (rect.right-38+int(4*pulse), rect.y+12))

            footer = "↑/↓ Select   ENTER Play   E Editor   ESC Back"
        else:
            draw_text_centered(self.screen, self.font_med, "SELECT AN OPTION", (175,175,190), SCREEN_W // 2, 158)
            item_h = 68
            start_y = 215
            for i, item in enumerate(self.main_menu_items):
                y = start_y + i * 80
                rect = pygame.Rect(SCREEN_W // 2 - 235, y, 470, item_h)
                selected = i == self.menu_index
                color = self.lane_colors[i % LANE_COUNT]
                if selected:
                    draw_glow_rect(self.screen, rect, color, glow_px=18, base_alpha=int(55 + 35*pulse))
                    fill, border, bw = (45,45,60), color, 3
                else:
                    fill, border, bw = (25,25,36), (58,58,72), 2
                pygame.draw.rect(self.screen, fill, rect, border_radius=13)
                pygame.draw.rect(self.screen, border, rect, bw, border_radius=13)
                draw_text_centered(self.screen, self.font_big if selected else self.font_med, item, (255,255,255) if selected else (205,205,215), SCREEN_W//2, y+item_h//2)
                if selected:
                    pygame.draw.circle(self.screen, color, (rect[0]+28, y+item_h//2), 5)
                    pygame.draw.circle(self.screen, color, (rect.right-28, y+item_h//2), 5)
            footer = "↑/↓ Select   ENTER Choose   F11 Fullscreen   F2 Editor"

        draw_text_centered(self.screen, self.font_small, footer, (155,155,170), SCREEN_W//2, SCREEN_H-28)

    def draw_settings(self):
        self.draw_menu_background(show_title=False)
        pulse = 0.5 + 0.5 * math.sin(self.time_ms / 450.0)
        draw_text_centered(self.screen, self.font_title, "SETTINGS", (245, 245, 255), SCREEN_W // 2, 65)
        draw_text_centered(self.screen, self.font_small, "ENTER changes a value • LEFT/RIGHT adjusts • ESC back", (165, 165, 180), SCREEN_W // 2, 112)

        items = self.settings_items()
        start_y = 160
        row_h = 50

        for i, item in enumerate(items):
            y = start_y + i * row_h
            selected = i == self.settings_index
            rect = (SCREEN_W // 2 - 270, y, 540, 42)
            accent = self.lane_colors[i] if i < 4 else self.lane_colors[(i - 5) % 4] if i >= 5 else self.lane_colors[2]

            if selected:
                draw_glow_rect(self.screen, rect, accent, glow_px=12, base_alpha=int(45 + 25 * pulse))
                fill = (45, 45, 60)
                border = accent
            else:
                fill = (27, 27, 38)
                border = (55, 55, 68)

            pygame.draw.rect(self.screen, fill, rect, border_radius=9)
            pygame.draw.rect(self.screen, border, rect, 2 if selected else 1, border_radius=9)

            label = self.font_med.render(item, True, (235, 235, 245))
            self.screen.blit(label, (rect[0] + 18, rect[1] + 7))

            if i < 4:
                value = self.lane_key_labels[i]
                value_color = self.lane_colors[i]
            elif i == 4:
                value = f"{int(self.note_speed)} px/s"
                value_color = self.lane_colors[2]
            else:
                lane = i - 5
                value = "■  " + str(self.lane_colors[lane])
                value_color = self.lane_colors[lane]

            if selected and self.rebinding_lane == i:
                value = "PRESS A KEY..."
                value_color = (255, 240, 130)

            value_surf = self.font_med.render(value, True, value_color)
            self.screen.blit(value_surf, (rect[0] + rect[2] - value_surf.get_width() - 18, rect[1] + 7))

        footer = "Current: " + "  ".join(f"{self.lane_key_labels[i]}" for i in range(4))
        draw_text_centered(self.screen, self.font_small, footer, (155, 155, 170), SCREEN_W // 2, 660)

    def draw_game(self):
        now = self.current_time_ms()

        for i in range(LANE_COUNT):
            x = lane_x(i)
            lane_surf = pygame.Surface((LANE_WIDTH, SCREEN_H), pygame.SRCALPHA)
            color = self.lane_colors[i]
            pygame.draw.rect(lane_surf, (*color, 26), (0, 0, LANE_WIDTH, HIT_LINE_Y))
            pygame.draw.rect(lane_surf, (26, 26, 36, 255), (0, HIT_LINE_Y, LANE_WIDTH, SCREEN_H - HIT_LINE_Y))
            self.screen.blit(lane_surf, (x, 0))
            pygame.draw.line(self.screen, (55, 55, 70), (x, 0), (x, SCREEN_H), 2)
        last_x = lane_x(LANE_COUNT - 1) + LANE_WIDTH
        pygame.draw.line(self.screen, (55, 55, 70), (last_x, 0), (last_x, SCREEN_H), 2)

        draw_glow_rect(self.screen, (0, HIT_LINE_Y - 2, SCREEN_W, 4), (200, 200, 255), glow_px=8, base_alpha=40)
        pygame.draw.rect(self.screen, (230, 230, 230), (0, HIT_LINE_Y, SCREEN_W, 4))

        for i in range(LANE_COUNT):
            self.draw_receptor(i)

        for note in self.chart.notes:
            self.draw_note(note, now)

        for p in self.particles:
            p.draw(self.screen)

        score_surf = self.font_big.render(f"{self.score}", True, (255, 255, 255))
        self.screen.blit(score_surf, (20, 20))
        self.draw_combo()
        self.draw_health_bar()
        self.draw_judgment_popup()

        if not self.song_started:
            title_surf = self.font_med.render(f"'{self.chart.title}' - Press SPACE to start", True, (255, 255, 255))
            self.screen.blit(title_surf, (SCREEN_W // 2 - title_surf.get_width() // 2, SCREEN_H // 2 - 100))
            if not self.has_audio:
                warn = self.font_small.render("(no audio file found - playing silently, timing still works)", True, (200, 140, 140))
                self.screen.blit(warn, (SCREEN_W // 2 - warn.get_width() // 2, SCREEN_H // 2 - 60))
            hint = self.font_small.render("ESC: Back to menu", True, (140, 140, 155))
            self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, SCREEN_H // 2 - 30))

        all_judged = all(n.judged for n in self.chart.notes) and self.song_started
        if all_judged:
            self.draw_results()

    def draw_health_bar(self):
        # A chunky arcade-style health bar with a subtle glow and percentage.
        x, y, w, h = 205, 24, 390, 28
        ratio = max(0.0, min(1.0, self.health / HEALTH_MAX))
        if ratio > 0.6:
            color = (90, 245, 145)
        elif ratio > 0.3:
            color = (255, 200, 75)
        else:
            color = (255, 75, 90)

        bg_rect = (x, y, w, h)
        draw_glow_rect(self.screen, bg_rect, color, glow_px=8, radius=10, base_alpha=35)
        pygame.draw.rect(self.screen, (24, 24, 34), bg_rect, border_radius=10)
        pygame.draw.rect(self.screen, (75, 75, 92), bg_rect, 2, border_radius=10)

        fill_w = int((w - 6) * ratio)
        if fill_w > 0:
            fill_rect = (x + 3, y + 3, fill_w, h - 6)
            pygame.draw.rect(self.screen, color, fill_rect, border_radius=7)
            shine_h = max(2, (h - 6) // 3)
            pygame.draw.rect(self.screen, (255, 255, 255, 75), (x + 5, y + 5, max(1, fill_w - 4), shine_h), border_radius=4)

        text = self.font_small.render(f"HP {int(self.health)}", True, (255, 255, 255))
        self.screen.blit(text, (x + w // 2 - text.get_width() // 2, y + 5))

    def draw_receptor(self, lane_index):
        cx = lane_center_x(lane_index)
        cy = HIT_LINE_Y
        color = self.lane_colors[lane_index]

        press_t = self.receptor_press[lane_index] / PRESS_FLASH_MS if self.receptor_press[lane_index] > 0 else 0
        judge_t = self.receptor_judge[lane_index] / RECEPTOR_JUDGE_MS if self.receptor_judge[lane_index] > 0 else 0

        # The slot is deliberately the exact same dimensions as the note.
        size_w = LANE_WIDTH - 12
        size_h = NOTE_HEIGHT
        scale = 1.0
        if judge_t > 0:
            scale = 1.0 + 0.35 * judge_t
        elif press_t > 0:
            scale = 1.0 + 0.12 * press_t

        w = size_w * scale
        h = size_h * scale
        rect = (cx - w / 2, cy - h / 2, w, h)

        glow_color = self.receptor_judge_color[lane_index] if judge_t > 0 else color
        base_alpha = int(45 + 160 * judge_t) if judge_t > 0 else int(45 + 90 * press_t)
        glow_px = int(10 + 22 * judge_t) if judge_t > 0 else int(10 + 8 * press_t)
        draw_glow_rect(self.screen, rect, glow_color, glow_px=glow_px, radius=6, base_alpha=base_alpha)

        fill_alpha = 55 if judge_t <= 0 and press_t <= 0 else int(70 + 120 * max(judge_t, press_t))
        fill_color = self.receptor_judge_color[lane_index] if judge_t > 0 else color
        slot_surf = pygame.Surface((max(1, int(w)), max(1, int(h))), pygame.SRCALPHA)
        pygame.draw.rect(slot_surf, (*fill_color, fill_alpha), (0, 0, int(w), int(h)), border_radius=6)
        border_alpha = 255 if press_t > 0 or judge_t > 0 else 180
        pygame.draw.rect(slot_surf, (*fill_color, border_alpha), (0, 0, int(w), int(h)), 3, border_radius=6)
        self.screen.blit(slot_surf, (int(rect[0]), int(rect[1])))

        label = self.font_med.render(self.lane_key_labels[lane_index], True, (255, 255, 255))
        self.screen.blit(label, (cx - label.get_width() // 2, cy + h / 2 + 12))

    def draw_note(self, note, now):
        pop_elapsed = None
        if note.pop_start is not None:
            pop_elapsed = pygame.time.get_ticks() - note.pop_start
            if pop_elapsed > 260:
                return
        elif note.judged and note.time_ms < now - 50:
            return

        time_until_hit = note.time_ms - now
        y = HIT_LINE_Y - (time_until_hit / 1000.0) * self.note_speed
        x = lane_x(note.lane)
        color = self.lane_colors[note.lane]

        if pop_elapsed is not None:
            t = min(1.0, pop_elapsed / 260.0)
            if note.hit:
                scale = 1.0 + 0.9 * t
                alpha = int(255 * (1 - t))
                y = HIT_LINE_Y
            else:
                scale = 1.0
                alpha = int(255 * (1 - t))
                y = y + 20 * t
            w = int((LANE_WIDTH - 12) * scale)
            h = int(NOTE_HEIGHT * scale)
            note_color = color if note.hit else (140, 60, 60)
            note_surf = pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA)
            pygame.draw.rect(note_surf, (*note_color, max(0, alpha)), (0, 0, w, h), border_radius=8)
            self.screen.blit(note_surf, (x + LANE_WIDTH // 2 - w // 2, y - h // 2))
            return

        if not (-NOTE_HEIGHT <= y <= SCREEN_H):
            return

        rect = (x + 6, y, LANE_WIDTH - 12, NOTE_HEIGHT)
        draw_glow_rect(self.screen, rect, color, glow_px=8, radius=6, base_alpha=55)
        note_surf = pygame.Surface((LANE_WIDTH - 12, NOTE_HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(note_surf, (*color, 255), (0, 0, LANE_WIDTH - 12, NOTE_HEIGHT), border_radius=6)
        pygame.draw.rect(note_surf, (255, 255, 255, 70), (0, 0, LANE_WIDTH - 12, NOTE_HEIGHT // 2), border_radius=6)
        self.screen.blit(note_surf, (x + 6, y))

    def draw_combo(self):
        if self.combo <= 1:
            return
        scale = 1.0
        if self.combo_pulse_start is not None:
            elapsed = pygame.time.get_ticks() - self.combo_pulse_start
            if elapsed < COMBO_PULSE_MS:
                t = elapsed / COMBO_PULSE_MS
                scale = 1.0 + 0.35 * (1 - t)
        draw_text_centered(self.screen, self.font_med, f"{self.combo} combo", (255, 220, 120), 90, 89, scale=scale)

    def draw_judgment_popup(self):
        if not self.last_judgment or self.last_judgment_start is None:
            return
        elapsed = pygame.time.get_ticks() - self.last_judgment_start
        if elapsed >= JUDGMENT_POP_MS:
            return

        color = JUDGMENT_COLORS[self.last_judgment]
        intensity = JUDGMENT_INTENSITY[self.last_judgment]
        grow_ms = 140
        hold_ms = 220
        fade_ms = JUDGMENT_POP_MS - grow_ms - hold_ms

        if elapsed < grow_ms:
            t = elapsed / grow_ms
            scale = 0.4 + 0.95 * ease_out_back(t) * (0.9 + 0.3 * intensity)
            alpha = int(255 * min(1.0, t * 1.6))
            y_offset = -14 * (1 - t)
        elif elapsed < grow_ms + hold_ms:
            scale = 1.0 + 0.06 * intensity
            alpha = 255
            y_offset = 0
        else:
            t = (elapsed - grow_ms - hold_ms) / max(1, fade_ms)
            scale = 1.0 - 0.05 * t
            alpha = int(255 * (1 - t))
            y_offset = -10 * t

        cx = SCREEN_W // 2
        cy = HIT_LINE_Y - 70 + y_offset
        draw_glow_rect(self.screen, (cx - 90, cy - 22, 180, 44), color, glow_px=int(16 * intensity) + 4, base_alpha=int(90 * intensity * (alpha / 255)))
        draw_text_centered(self.screen, self.font_judgment, self.last_judgment, color, cx, cy, scale=scale, alpha=alpha)

    def draw_results(self):
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 185))
        self.screen.blit(overlay, (0, 0))

        y = SCREEN_H // 2 - 110
        title_surf = self.font_big.render("RESULTS", True, (255, 255, 255))
        self.screen.blit(title_surf, (SCREEN_W // 2 - title_surf.get_width() // 2, y))
        y += 70

        info_lines = [
            f"{self.chart.title}",
            f"Score: {self.score}        Max Combo: {self.max_combo}",
            f"Perfect: {self.judgment_counts['PERFECT']}   Great: {self.judgment_counts['GREAT']}   "
            f"Good: {self.judgment_counts['GOOD']}   Miss: {self.judgment_counts['MISS']}",
            f"Health: {int(self.health)} / {int(HEALTH_MAX)}",
        ]
        for line in info_lines:
            surf = self.font_med.render(line, True, (230, 230, 235))
            self.screen.blit(surf, (SCREEN_W // 2 - surf.get_width() // 2, y))
            y += 38

        y += 20
        hint = self.font_small.render("R Restart    ENTER Menu    ESC Menu", True, (170, 170, 185))
        self.screen.blit(hint, (SCREEN_W // 2 - hint.get_width() // 2, y))

    # -- main menu -----------------------------------------------------------
    def handle_menu_key(self, key):
        if key == pygame.K_F11:
            self.toggle_fullscreen()
            return True

        if self.menu_screen == "main":
            if key in (pygame.K_UP, pygame.K_w):
                self.menu_index = (self.menu_index - 1) % len(self.main_menu_items)
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.menu_index = (self.menu_index + 1) % len(self.main_menu_items)
            elif key in (pygame.K_RETURN, pygame.K_SPACE):
                self.play_select_sound()
                choice = self.main_menu_items[self.menu_index]
                if choice == "SONGS":
                    self.available_charts = scan_charts(self.charts_dir)
                    self.menu_index = 0
                    self.menu_screen = "songs"
                elif choice == "SETTINGS":
                    self.menu_index = 0
                    self.state = "settings"
                elif choice == "CHART EDITOR":
                    self.open_editor()
                elif choice == "EXIT GAME":
                    return False
            elif key == pygame.K_ESCAPE:
                return False
            elif key == pygame.K_F2:
                self.open_editor()
            return True

        # Songs browser
        if key in (pygame.K_UP, pygame.K_w):
            count = max(1, len(self.available_charts))
            self.menu_index = (self.menu_index - 1) % count
        elif key in (pygame.K_DOWN, pygame.K_s):
            count = max(1, len(self.available_charts))
            self.menu_index = (self.menu_index + 1) % count
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            if self.available_charts:
                self.play_select_sound()
                self.chart_path = self.available_charts[self.menu_index]["path"]
                self.load_chart()
                self.state = "playing"
        elif key == pygame.K_e:
            self.open_editor()
        elif key == pygame.K_ESCAPE or key == pygame.K_BACKSPACE:
            self.menu_screen = "main"
            self.menu_index = 0
        elif key == pygame.K_F2:
            self.open_editor()
        return True

    def handle_playing_key(self, key):
        all_judged = all(n.judged for n in self.chart.notes) and self.song_started
        if key in (pygame.K_ESCAPE, pygame.K_p):
            self.pause_game()
        elif key == pygame.K_SPACE and not self.song_started:
            self.start_song()
        elif key == pygame.K_r:
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass
            self.load_chart()
        elif all_judged and key == pygame.K_RETURN:
            if self.editor_return_after_playtest:
                self.editor_return_after_playtest = False
                self.state = "editor"
            else:
                self.go_to_menu()
        elif self.song_started and not all_judged and key in self.lane_keys:
            lane = self.lane_keys.index(key)
            self.handle_hit(lane)
        return True

    def handle_paused_key(self, key):
        if key in (pygame.K_RETURN, pygame.K_p, pygame.K_ESCAPE):
            self.resume_game()
        elif key == pygame.K_r:
            self.resume_game()
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass
            self.load_chart()
        elif key == pygame.K_m:
            self.editor_return_after_playtest = False
            self.go_to_menu()
        return True

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS)
            self._last_dt = dt
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_F11:
                        self.toggle_fullscreen()
                        continue
                    if self.state == "menu":
                        running = self.handle_menu_key(event.key)
                    elif self.state == "settings":
                        running = self.handle_settings_key(event.key)
                    elif self.state == "editor":
                        running = self.handle_editor_key(event.key)
                    elif self.state == "paused":
                        running = self.handle_paused_key(event.key)
                    else:
                        running = self.handle_playing_key(event.key)

            if self.state == "playing":
                if self.song_started:
                    self.update(dt)
                else:
                    self.time_ms += dt
                    for i in range(LANE_COUNT):
                        if self.receptor_press[i] > 0:
                            self.receptor_press[i] = max(0, self.receptor_press[i] - dt)
            elif self.state == "editor":
                self.time_ms += dt
                self.editor_time_ms()
            else:
                self.time_ms += dt

            self.draw()

        pygame.quit()


if __name__ == "__main__":
    charts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "charts")
    chart_arg = sys.argv[1] if len(sys.argv) > 1 else None
    Game(chart_arg, charts_dir=charts_dir).run()
