import os
import asyncio
import logging
import ignis
from ignis import widgets
from ignis.services.mpris import MprisService, MprisPlayer
from ignis import utils
from services.material import MaterialService
from jinja2 import Template
from ignis.css_manager import CssManager, CssInfoString
import uuid
import time

# --- Logging setup ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("media-player")

mpris = MprisService.get_default()
css_manager = CssManager.get_default()
material = MaterialService.get_default()

MEDIA_TEMPLATE = utils.get_current_dir() + "/media.scss"
MEDIA_SCSS_CACHE_DIR = ignis.CACHE_DIR + "/media"
os.makedirs(MEDIA_SCSS_CACHE_DIR, exist_ok=True)

# Constants
ARTWORK_POLL_INTERVAL = 2  # seconds
NO_TRACK_GRACE_PERIOD = 8  # seconds
MAX_TITLE_CHARS = 30

PLAYER_ICONS = {
    "spotify": "spotify-symbolic",
    "firefox": "firefox-browser-symbolic",
    "chrome": "chrome-symbolic",
    None: "folder-music-symbolic",
}

FALLBACK_COLORS = {
    "primary": "#333333",
    "onPrimary": "#D17500",
    "onSurface": "#cccccc",
    "onSurfaceVariant": "#999999",
    "art_url": "",
}

LAST_ARTWORK_CACHE = {}

class Player(widgets.Revealer):
    def __init__(self, player: MprisPlayer, media_container=None) -> None:
        self._player = player
        self._media_container = media_container
        self._polling_task = None
        self._no_track_task = None
        self._running = True
        self._destroyed = False
        
        # Create unique identifier for this player instance
        desktop_entry = player.desktop_entry or "unknown"
        self._unique_id = f"{desktop_entry}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        
        log.info(f"Player initialized: desktop_entry={player.desktop_entry}, track_id={player.track_id}, unique_id={self._unique_id}")

        player.connect("closed", lambda x: self.destroy())
        player.connect("notify::art-url", lambda x, y: self.load_colors())
        player.connect("notify::track-id", lambda x, y: asyncio.create_task(self._on_track_id_change_async()))

        player.connect("notify::desktop-entry", lambda x, y: log.debug(f"desktop_entry changed: {x.desktop_entry}"))
        player.connect("notify::title", lambda x, y: log.debug(f"title changed: {x.title}"))
        player.connect("notify::artist", lambda x, y: log.debug(f"artist changed: {x.artist}"))

        self.load_colors()

        if not (self._player.art_url and os.path.isfile(self._player.art_url)):
            log.debug(f"No initial artwork for {self._player.desktop_entry}, starting poller...")
            self._polling_task = asyncio.create_task(self.poll_for_art())

        super().__init__(
            transition_type="slide_down",
            reveal_child=False,
            css_classes=[self.get_css("media")],
            child=widgets.Overlay(
                child=widgets.Box(css_classes=[self.get_css("media-image")]),
                overlays=[
                    widgets.Box(
                        hexpand=True, vexpand=True,
                        css_classes=[self.get_css("media-image-gradient")],
                    ),
                    widgets.Icon(
                        icon_name=self.get_player_icon(),
                        pixel_size=22,
                        halign="start",
                        valign="start",
                        css_classes=[self.get_css("media-player-icon")],
                    ),
                    widgets.Box(
                        vertical=True, hexpand=True,
                        css_classes=[self.get_css("media-content")],
                        child=[
                            widgets.Box(
                                vexpand=True, valign="center",
                                child=[
                                    widgets.Box(
                                        hexpand=True, vertical=True,
                                        child=[
                                            widgets.Label(
                                                ellipsize="end", label=player.bind("title"),
                                                max_width_chars=MAX_TITLE_CHARS,
                                                halign="start",
                                                css_classes=[self.get_css("media-title")],
                                            ),
                                            widgets.Label(
                                                label=player.bind("artist"),
                                                max_width_chars=MAX_TITLE_CHARS,
                                                ellipsize="end",
                                                halign="start",
                                                css_classes=[self.get_css("media-artist")],
                                            ),
                                        ]
                                    ),
                                    widgets.Button(
                                        child=widgets.Icon(
                                            image=player.bind(
                                                "playback_status",
                                                lambda v: "media-playback-pause-symbolic" if v == "Playing" else "media-playback-start-symbolic"),
                                            pixel_size=18,
                                        ),
                                        on_click=lambda x: asyncio.create_task(player.play_pause_async()),
                                        visible=player.bind("can_play"),
                                        css_classes=player.bind("playback_status",
                                            lambda v: [self.get_css("media-playback-button"), "playing"] if v == "Playing" else [self.get_css("media-playback-button"), "paused"]),
                                    ),
                                ],
                            ),
                        ],
                    ),
                    widgets.Box(
                        vexpand=True, valign="end",
                        style="padding: 1rem;",
                        child=[
                            widgets.Button(
                                child=widgets.Icon(image="media-skip-backward-symbolic", pixel_size=20),
                                css_classes=[self.get_css("media-skip-button")],
                                on_click=lambda x: asyncio.create_task(player.previous_async()),
                                visible=player.bind("can_go_previous"),
                                style="margin-left: 1rem;",
                            ),
                            widgets.Button(
                                child=widgets.Icon(image="media-skip-forward-symbolic", pixel_size=20),
                                css_classes=[self.get_css("media-skip-button")],
                                on_click=lambda x: asyncio.create_task(player.next_async()),
                                visible=player.bind("can_go_next"),
                                style="margin-left: 1rem;",
                            ),
                        ],
                    )
                ],
            ),
        )

    async def poll_for_art(self):
        while self._running and not self._destroyed:
            try:
                art_url = self._player.art_url
                if art_url and os.path.isfile(art_url):
                    log.info(f"Artwork found for {self._player.desktop_entry}: {art_url}")
                    self.load_colors()
                    break
                log.debug(f"Polling for artwork: {self._player.desktop_entry} (art_url={art_url})")
                await asyncio.sleep(ARTWORK_POLL_INTERVAL)
            except Exception as e:
                log.error(f"Error in artwork polling: {e}")
                break

    def get_player_icon(self) -> str:
        desktop_entry = self._player.desktop_entry
        if desktop_entry == "firefox":
            return PLAYER_ICONS["firefox"]
        elif desktop_entry == "spotify":
            return PLAYER_ICONS["spotify"]
        elif self._player.track_id is not None:
            track_id = str(self._player.track_id)
            if "chromium" in track_id or "chrome" in track_id or "brave" in track_id:
                return PLAYER_ICONS["chrome"]
        return PLAYER_ICONS[None]

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True

        log.info(f"Destroying player widget: {self._player.desktop_entry or 'unknown'} (unique_id: {self._unique_id})")
        self._running = False
        
        # Cancel async tasks
        if self._polling_task:
            self._polling_task.cancel()
        if self._no_track_task:
            self._no_track_task.cancel()
            self._no_track_task = None
        
        # Remove CSS for this specific instance
        try:
            if self._unique_id in css_manager.list_css_info_names():
                css_manager.remove_css(self._unique_id)
                log.debug(f"Removed CSS for {self._unique_id}")
        except Exception as e:
            log.error(f"Error removing CSS for {self._unique_id}: {e}")
        
        self.set_reveal_child(False)
        utils.Timeout(self.transition_duration, super().unparent)

    def get_css(self, class_name: str) -> str:
        # Use unique ID instead of desktop_entry to avoid conflicts
        return f"{class_name}-{self._unique_id}"

    def _get_base_track_id(self) -> str:
        tid = self._player.track_id or ""
        if "/TrackList" in tid:
            return tid.split("/TrackList")[0]
        return tid

    async def _on_track_id_change_async(self):
        if self._destroyed:
            return
            
        tid = self._player.track_id or ""
        log.debug(f"track_id changed observed: {tid}")

        if "NoTrack" in tid:
            if self._no_track_task is None:
                log.info("Received NoTrack, starting grace timer before destroying widget.")
                self._no_track_task = asyncio.create_task(self._no_track_timeout())
            return

        # Valid track came back; cancel any pending destruction
        if self._no_track_task:
            log.info("Valid track detected, cancelling no-track timeout.")
            self._no_track_task.cancel()
            self._no_track_task = None

        self.load_colors()

    async def _no_track_timeout(self):
        try:
            await asyncio.sleep(NO_TRACK_GRACE_PERIOD)
            if not self._destroyed:
                log.info("No track prefix detected within timeout. Destroying widget.")
                # Notify media container that this player should be marked as destroyed
                if self._media_container:
                    self._media_container._destroyed_players[self._player] = True
                self.destroy()
        except asyncio.CancelledError:
            log.debug("NoTrack timeout cancelled")

    async def safe_color_extraction(self, art_url: str) -> dict:
        """Safely extract colors from artwork with error handling."""
        try:
            if art_url and os.path.isfile(art_url):
                colors = material.get_colors_from_img(art_url, True)
                colors["art_url"] = art_url
                return colors
        except Exception as e:
            log.error(f"Failed to extract colors from {art_url}: {e}")
        
        colors = FALLBACK_COLORS.copy()
        colors["art_url"] = ""
        return colors

    def load_colors(self) -> None:
        if self._destroyed:
            return
            
        tid = self._player.track_id or ""
        if "NoTrack" in tid:
            return

        art_url = self._player.art_url
        base_id = self._get_base_track_id()
        log.debug(f"Loading colors for {self._player.desktop_entry}, base_track_id={base_id}, art_url={art_url}")

        if art_url and os.path.isfile(art_url):
            log.info(f"Using artwork for {self._player.desktop_entry}: {art_url}")
            colors = asyncio.create_task(self.safe_color_extraction(art_url))
            colors = FALLBACK_COLORS.copy()  # Temporary fallback, should await the task
            try:
                colors = material.get_colors_from_img(art_url, True)
                colors["art_url"] = art_url
                LAST_ARTWORK_CACHE[base_id] = art_url
            except Exception as e:
                log.error(f"Error extracting colors: {e}")
                colors = FALLBACK_COLORS.copy()
                colors["art_url"] = ""
        else:
            cached = LAST_ARTWORK_CACHE.get(base_id)
            if cached and os.path.isfile(cached):
                log.info(f"Reusing cached artwork for {base_id}: {cached}")
                try:
                    colors = material.get_colors_from_img(cached, True)
                    colors["art_url"] = cached
                except Exception as e:
                    log.error(f"Error using cached artwork: {e}")
                    colors = FALLBACK_COLORS.copy()
                    colors["art_url"] = ""
            else:
                log.warning(f"No artwork and no cached image for {self._player.desktop_entry}, using fallback colors.")
                colors = FALLBACK_COLORS.copy()
                colors["art_url"] = ""

        colors["desktop_entry"] = self._unique_id  # Use unique ID for CSS

        try:
            with open(MEDIA_TEMPLATE) as file:
                template_rendered = Template(file.read()).render(colors)

            # Remove old CSS if it exists
            if self._unique_id in css_manager.list_css_info_names():
                css_manager.remove_css(self._unique_id)

            # Apply new CSS with unique identifier
            css_manager.apply_css(
                CssInfoString(
                    name=self._unique_id,
                    compiler_function=lambda string: utils.sass_compile(string=string),
                    string=template_rendered,
                )
            )
        except Exception as e:
            log.error(f"Error applying CSS: {e}")

    def clean_desktop_entry(self) -> str:
        return self._player.desktop_entry or "unknown"


class Media(widgets.Box):
    def __init__(self):
        super().__init__(
            vertical=True,
            setup=lambda self: mpris.connect(
                "player_added", lambda x, player: self.__add_player(player)
            ),
            css_classes=["rec-unset"],
        )

        mpris.connect("notify::active-player", lambda x, y:
            log.info(f"Active player changed: {x.active_player.desktop_entry if x.active_player else None}")
        )

        self._players = {}
        self._destroyed_players = {}  # Track destroyed players by desktop_entry

    def __add_player(self, obj: MprisPlayer) -> None:
        log.info(f"New player added: desktop_entry={obj.desktop_entry}, track_id={obj.track_id}")
        
        # Clean up any existing CSS that might conflict
        desktop_entry = obj.desktop_entry or "unknown"
        existing_css_names = [name for name in css_manager.list_css_info_names() if desktop_entry in name]
        for name in existing_css_names:
            try:
                css_manager.remove_css(name)
                log.debug(f"Cleaned up existing CSS: {name}")
            except Exception as e:
                log.error(f"Error cleaning up CSS {name}: {e}")
        
        # Check if this player was previously destroyed but is now active again
        if obj in self._destroyed_players:
            log.info(f"Player {desktop_entry} was previously destroyed, removing from destroyed list")
            del self._destroyed_players[obj]
        
        # Add track_id change monitoring to detect when media starts on existing players
        obj.connect("notify::track-id", lambda x, y: self.__handle_track_change(x))
        
        player = Player(obj, self)  # Pass self as media_container
        self._players[obj] = player
        self.append(player)
        player.set_reveal_child(True)

        obj.connect("closed", lambda x: self._remove_player(obj))

    def __handle_track_change(self, obj: MprisPlayer) -> None:
        """Handle track_id changes on existing players - recreate widget if it was destroyed"""
        track_id = obj.track_id or ""
        desktop_entry = obj.desktop_entry or "unknown"
        
        log.debug(f"Track change detected: desktop_entry={desktop_entry}, track_id={track_id}")
        log.debug(f"Player in destroyed list: {obj in self._destroyed_players}")
        log.debug(f"Player in active list: {obj in self._players}")
        log.debug(f"Destroyed players count: {len(self._destroyed_players)}")
        log.debug(f"Active players count: {len(self._players)}")
        
        # Check if this player needs a widget (either destroyed or never had one)
        needs_widget = (obj in self._destroyed_players) or (obj not in self._players)
        
        if needs_widget and track_id and "NoTrack" not in track_id:
            log.info(f"Recreating widget for {desktop_entry} - media started on existing player")
            
            # Remove from destroyed list if present
            if obj in self._destroyed_players:
                del self._destroyed_players[obj]
            
            # Remove existing widget if somehow still present
            if obj in self._players:
                old_player = self._players[obj]
                old_player.destroy()
                self.remove(old_player)
                del self._players[obj]
            
            # Clean up any conflicting CSS
            existing_css_names = [name for name in css_manager.list_css_info_names() if desktop_entry in name]
            for name in existing_css_names:
                try:
                    css_manager.remove_css(name)
                    log.debug(f"Cleaned up existing CSS: {name}")
                except Exception as e:
                    log.error(f"Error cleaning up CSS {name}: {e}")
            
            # Create new player widget
            player = Player(obj, self)  # Pass self as media_container
            self._players[obj] = player
            self.append(player)
            player.set_reveal_child(True)
        else:
            log.debug(f"No widget recreation needed. needs_widget={needs_widget}, track_id={track_id}")
            if "NoTrack" in track_id:
                log.debug("Track contains 'NoTrack', skipping recreation")

    def _remove_player(self, obj: MprisPlayer) -> None:
        player = self._players.pop(obj, None)
        if player:
            desktop_entry = obj.desktop_entry or "unknown"
            log.info(f"Removing player widget for closed player {desktop_entry}")
            
            # Mark this player as destroyed but don't remove the MPRIS object reference
            # The browser might still be running and could start playing media again
            self._destroyed_players[obj] = True
            log.debug(f"Added {desktop_entry} to destroyed players list")
            
            player.destroy()
            self.remove(player)