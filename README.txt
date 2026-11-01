AIR TRAVEL — UPGRADED STARTER
Owner: Akinola Ajide

LOCAL WINDOWS START
1. Install Python 3 from https://www.python.org/downloads/windows/ (check “Add Python to PATH”).
2. Extract the whole ZIP folder.
3. Double-click START_AIR_TRAVEL.bat.
4. Keep the terminal window open; the app opens in your browser at http://127.0.0.1:5000.

WHAT'S NEW
- Interactive map powered by Leaflet/OpenStreetMap.
- Best-effort public ADS-B aircraft reports near Lagos via adsb.lol; automatically labels sample fallback if the feed is unavailable.
- Refreshes aircraft data about every 60 seconds.
- AI uses a connected OpenAI API only if OPENAI_API_KEY is configured; otherwise it falls back to the built-in demo responses.
- Render deployment starter files (Procfile and render.yaml).
- Community chat and photo sharing are still a prototype; messages are held in server memory and do not yet support reliable multi-instance public use.

OWNER LOGIN
Demo password: change-this-password
Set AIRTRAVEL_OWNER_PASSWORD in environment before any public deployment. Change it to a long unique password. Never share your API key or owner password.

PUTTING IT ONLINE
1. Create an account on Render.com and put this project in a GitHub repository.
2. In Render, choose New > Blueprint and select that repository; it reads render.yaml.
3. In Render Environment, set AIRTRAVEL_OWNER_PASSWORD to a new strong password. Add OPENAI_API_KEY only if you want connected AI; API usage may cost money.
4. Deploy and open the public URL Render gives you.
5. IMPORTANT: the current chat is in-memory and uploaded images are stored on the app filesystem. For a real public community, add PostgreSQL and persistent/object storage before inviting users. The free hosting filesystem may reset on redeploy.

LIMITATIONS / SAFETY
- ADS-B coverage is incomplete and the public endpoint may rate-limit or fail. Aircraft positions can be missing or delayed; never use this for navigation or flight operations.
- Aircraft data is not a complete flight plan, and destination is generally not supplied by the ADS-B feed.
- The AI is educational only and is not an operational aviation source.
- No radio scanner/transmitter or private pilot/ATC audio interception is included. Any audio services must be public and lawfully accessible.
- The owner dashboard is a basic demo, not a secure production admin system.
- Do not post personal, passenger, crew, or security-sensitive information.


NEW IN THIS VERSION
- Your supplied Air Travel Online Agency image is now the welcome and header logo.
- Member sign-up and sign-in are available in the Sign in / Join tab. User accounts are stored in a local SQLite database with hashed passwords.
- Community posting requires a signed-in account.
- Air Travel AI has a stronger built-in aviation helper and now explains when a real API connection is not configured or fails.

FULL AI SETUP (OPTIONAL)
To enable connected AI, set an OPENAI_API_KEY environment variable before launching the app. Keep the key private and do not put it in website JavaScript or share it publicly. Without a key, the built-in helper still answers common aviation questions.

ACCOUNT NOTE
This is a local prototype. Accounts and messages are stored on this computer only; they are not automatically shared across the internet. For public launch, use a production database, secure HTTPS hosting, backups, and moderation.


WELCOME PROMO & WAITING MUSIC
- The welcome screen shows an in-app Air Travel promotional message before entering the dashboard. This is house promotion, not a paid third-party ad network.
- Click “Turn waiting music on” to hear a gentle generated instrumental-style tone loop. Browser audio must be enabled by a click; there is no downloaded music track.
- Click “Enter Air Travel” and the short 3-second welcome promo will finish before the dashboard opens.
