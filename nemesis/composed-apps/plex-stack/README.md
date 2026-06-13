# Plex Stack — How to Request Shows & Movies

## Requesting Content

Use **Overseerr** to request new shows and movies:

**https://overseerr.rt-541.io**

1. Log in with your Plex account
2. Search for a show or movie
3. Click **Request**
4. Done — it will automatically download and appear in Plex once ready

That's it. You don't need to touch anything else.

---

## What Happens Behind the Scenes

You don't need to manage any of this, but here's what runs automatically after you request something:

| Service | What it does |
|---------|-------------|
| **Sonarr** | Finds and manages TV shows |
| **Radarr** | Finds and manages movies |
| **Prowlarr** | Searches indexers for available downloads |
| **qBittorrent** | Downloads the files (routes through VPN) |
| **Plex** | Streams everything to you |

---

## Tips

- Most requests download within a few hours, sometimes faster
- TV shows: if you request a series, it will grab the whole season
- If something isn't showing up after 24 hours, let me know
- Don't request the same thing twice — it'll already be queued

---

---

## Troubleshooting — Grabbing a Specific Release

If a show or movie downloaded in the wrong quality, wrong language, or wrong version, you can manually pick a release in Sonarr or Radarr.

### TV Shows — Sonarr

**https://sonarr.rt-541.io**

1. Find the show in the library
2. Click the show, then click the season/episode you want to fix
3. Click the **search icon** (magnifying glass) on that episode
4. A list of available releases will appear — pick the one you want and click **Download**

To re-download an entire season: click the season, then **Season Search** → **Interactive Search**

---

### Movies — Radarr

**https://radarr.rt-541.io**

1. Find the movie in the library
2. Click the movie
3. Click **More** → **Interactive Search** (or the search icon at the top)
4. Pick the release you want from the list and click **Download**

---

### Tips for Picking a Release

- **Remux** = best quality, very large file
- **BluRay 1080p** = great quality, reasonable size
- **WEB-DL** = good quality, smaller — fine for most things
- Avoid releases marked **CAM**, **TS**, or **HDCAM** — those are bad rips
- If you're not sure, pick the one with the most seeders

---

## Need Access?

If you don't have a Plex account or can't log in to Overseerr, Sonarr, or Radarr, reach out and I'll get you set up.
