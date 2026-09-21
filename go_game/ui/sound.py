"""Optional pygame audio: failures never stop gameplay."""

import logging

import pygame

logger = logging.getLogger("go_game.ui.sound")


class Sound:
    """Best-effort sound adapter for environments with or without audio."""

    def __init__(self):
        self.music_playing = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except pygame.error as exc:
            logger.info(
                "Audio initialization unavailable: %s", type(exc).__name__,
                extra={"event": "audio.unavailable"},
            )

    def _ready(self):
        return bool(pygame.mixer.get_init())

    def play_background_music(self, file, loops=-1):
        if not self._ready():
            return
        try:
            pygame.mixer.music.load(file)
            pygame.mixer.music.play(loops=loops)
            self.music_playing = True
        except pygame.error as exc:
            logger.warning(
                "Cannot play background audio: %s", type(exc).__name__,
                extra={"event": "audio.music_failed"},
            )

    def stop_background_music(self):
        if self.music_playing and self._ready():
            pygame.mixer.music.stop()
            self.music_playing = False

    def play_sound_effect(self, file):
        if not self._ready():
            return
        try:
            pygame.mixer.Sound(file).play()
        except pygame.error as exc:
            logger.debug(
                "Sound effect unavailable: %s", type(exc).__name__,
                extra={"event": "audio.effect_failed"},
            )
