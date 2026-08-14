import pygame


class Sound:
    """Defensive pygame sound wrapper that never crashes the game."""

    def __init__(self):
        self.music_playing = False
        try:
            pygame.mixer.init()
        except pygame.error:
            pass

    def _ready(self):
        return bool(pygame.mixer.get_init())

    def play_background_music(self, file, loops=-1):
        if not self._ready():
            return
        try:
            pygame.mixer.music.load(file)
            pygame.mixer.music.play(loops=loops)
            self.music_playing = True
        except pygame.error:
            pass

    def stop_background_music(self):
        if self.music_playing and self._ready():
            pygame.mixer.music.stop()
            self.music_playing = False

    def play_sound_effect(self, file):
        if not self._ready():
            return
        try:
            pygame.mixer.Sound(file).play()
        except pygame.error:
            pass