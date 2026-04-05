# Roadmap

Things I want to add, roughly in priority order. PRs welcome.

## Soon

- [ ] **Resume interrupted downloads** — aria2 integration for proper resume support on large ISOs
- [ ] **Download queue** — limit concurrent downloads instead of firing them all at once
- [ ] **Cover search UI** — search IGDB covers directly from the add-game modal without needing a URL
- [ ] **Folder watcher** — auto-import new files dropped into `~/roms/` without manual scan

## Medium term

- [ ] **Playtime tracking** — log sessions, last played date
- [ ] **Wishlist** — mark games you want but don't have yet, separate from the main library
- [ ] **AYN Thor sync** — detect the device over USB/network and push files directly
- [ ] **Duplicate detection** — flag when you have the same game under two different filenames
- [ ] **Multi-disc handling** — group disc 1/2/3 of PS1 games under a single card

## Nice to have

- [ ] **Mobile-optimized UI** — better touch targets for browsing from the handheld itself
- [ ] **Export to CSV/JSON** — backup your library metadata
- [ ] **Stats page** — total size on disk, games per console, completion percentage
- [ ] **Dark/light theme toggle**
- [ ] **RetroAchievements integration** — show achievement count per game

## Won't do (for now)

- Scraping metadata from anywhere other than IGDB — too fragile
- Windows support — use WSL
