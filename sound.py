import pygame

class Sound:
    """Class to manage sound effects and background music in the Go game."""

    def __init__(self):
        """Initialize the sound system."""
        pygame.mixer.init()
        self.music_playing = False
        print("Sound system initialized.")

    def play_background_music(self, file: str) -> None:
        """Plays the background music in a loop.
        
        Args:
            file: Path to the music file.
        """
        try:
            pygame.mixer.music.load(file)
            pygame.mixer.music.play(loops=-1)
            self.music_playing = True
            print(f"Background music '{file}' is now playing.")
        except pygame.error as e:
            print(f"Failed to load and play background music: {e}")

    def stop_background_music(self) -> None:
        """Stops the background music."""
        if self.music_playing:
            pygame.mixer.music.stop()
            self.music_playing = False
            print("Background music stopped.")

    def play_sound_effect(self, file: str) -> None:
        """Plays a sound effect once.
        
        Args:
            file: Path to the sound effect file.
        """
        try:
            sound_effect = pygame.mixer.Sound(file)
            sound_effect.play()
            print(f"Sound effect '{file}' played.")
        except pygame.error as e:
            print(f"Failed to play sound effect: {e}")

