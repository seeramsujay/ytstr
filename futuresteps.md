# Future Steps for ytstr

1. **Crossfade Implementation (Spotify Mix feature)**
   Currently, songs play sequentially with a hard cut. We implemented overlapping playback with fade-out and fade-in to create a seamless mix.
   
2. **Remove Leading Silence**
   Remove the leading silence in the next song and keep it ready for a smoother crossfade.

3. **Status Output Cleanup**
   Ensure console terminal output remains clean when multiple `mpv` background jobs overlap during crossfading.

4. **Playlist Persistence & Sync**
   Allow syncing of playlists across different directories or users.
