| `--no-shuffle` | Play tracks in original sequential order. |
| `--gui` | Launch lightweight desktop YouTube Music interface. |
| `--login [BROWSER]` | 1-click browser login (auto, chrome, firefox, brave, edge, etc.). |
| `--logout` | Clear saved YouTube Music credentials. |
| `--list` | List all saved playlists. |
| `--add NAME URL` | Save a playlist with a friendly name. |
| `--remove NUM` | Remove a saved playlist by index. |

---

## 🖥️ YouTube Music GUI & 1-Click Browser Login

Inspired by **Sonora**, **InnerTune**, and **Metrolist**, `ytstr` now provides seamless browser authentication without requiring any manual DevTools inspection or header copying:

### How 1-Click Browser Login Works
1. Click **Log In** in the GUI (or run `ytstr --login` in terminal).
2. Click **"🌐 Open music.youtube.com in Browser"** to ensure you are signed in on your default web browser (Chrome, Firefox, Brave, Edge, etc.).
3. Click **"⚡ Import Session & Log In"**:
   - `ytstr` automatically accesses the local browser session cookie database via `yt-dlp`'s secure extractor.
   - Extracts the authenticated `SAPISID` and `__Secure-3PAPISID` YouTube session tokens.
   - Saves credentials securely to `~/.config/ytstr/ytm_auth.json`.
4. Your account is immediately activated, loading your personalized **"Listen Again"**, **"Quick Picks"**, **Liked Music**, and **Playlists**!

*(Manual header paste from DevTools is also preserved as a fallback for custom browsers.)*

---

## ⌨️ Interactive Keyboard Controls

During terminal playback:
