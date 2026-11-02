# AIR TRAVEL — World Edition Review Build

This is a local review build intended for checking the website before deployment. It is **not yet a public production launch**.

## Run on a Windows laptop

1. Download and extract this ZIP into a new folder.
2. Open the extracted `AIR_TRAVEL_WORLD_EDITION` folder.
3. Click the File Explorer address bar, type `cmd`, then press Enter.
4. Run these commands one at a time:

   ```bat
   python -m pip install -r requirements.txt
   python app.py
   ```

5. Keep the black command window open.
6. Open Chrome and visit `http://127.0.0.1:5000`.

To stop the server, return to the black command window and press `Ctrl+C`.

## Turn on optional generative AI

The built-in AIR TRAVEL assistant already works without an API key for common travel and aviation questions. For more flexible generative answers:

1. Copy `.env.example` and name the copy `.env` in the project folder.
2. Add your own `OPENAI_API_KEY` to the `.env` file and keep it private.
3. Set `OPENAI_MODEL` to a model available to your account if needed.
4. Restart AIR TRAVEL.

Never share the `.env` file or commit it to GitHub. API usage may cost money according to the provider's account and pricing. Without a key, the website continues using its built-in assistant mode.

## First-time team access (local review only)

The first time the app creates its database, it seeds these temporary accounts. On first sign-in, each account is required to change its password to one with at least 12 characters.

| Role | Email | Temporary password |
|---|---|---|
| OWNER — AKINOLA AJIDE | `owner@airtravel.local` | `AirTravelOwner2026!` |
| CO-OWNER — JAYDINE | `coowner@airtravel.local` | `AirTravelCoOwner2026!` |

Use **Owner access** in the navigation, then sign in with the owner account. The owner can create additional administrator accounts from the control centre. Co-owner and administrator accounts can access the control centre; only the owner can create administrators and manage the manual advert list.

**These temporary credentials are for local review only. Do not publish the site using them.** Before public deployment, set unique secrets and passwords through the host's environment-variable settings. Existing accounts are not reset on later starts.

## Features included in this review build

- Refreshed responsive home page and mobile navigation.
- Ten-second cinematic home-page promotional video with a British English (Received Pronunciation) synthetic female voiceover and dramatic original instrumental music; it starts muted, with an option to enable sound or skip.
- Guest registration and sign-in with hashed passwords.
- Owner and co-owner seeded access; first sign-in requires a password change.
- Owner can create administrator accounts.
- Owner/co-owner/admin control centre with member and message counts.
- Owner/co-owner can publish community notices.
- Owner can create and pause manually managed sponsored listings; active listings appear with an AD label.
- Pilot text chat shared through the website database, refreshing every four seconds.
- Route idea helper for Lagos, Abuja, Port Harcourt and Kano.
- Explore Destinations page with a starter destination collection.
- Travel Tools page with a trip budget calculator, user-rate currency calculator and packing checklist.
- Aviation Quiz Centre with five interactive questions and scoring.
- AIR TRAVEL TV page with a 10-second launch advert and a narrated AI-guide app explainer video.
- AIR TRAVEL Cinema Club with Movie Night watch rooms, six-character invite codes and synced host play/pause/seek for direct authorised MP4/WebM media.
- Featured Inside Out movie spotlight linking to Disney’s official film page; the copyrighted full film is not bundled or streamed by AIR TRAVEL.
- Support form that saves requests to the database for the staff control centre.
- Private travel diary for each signed-in guest/member.
- Updated navigation and home-page feature cards.
- Flight map interface with sample records explicitly labelled as demo data.
- Basic cached home, destination, travel-tools, quiz, TV and support pages for offline revisits.
- CSRF checks on form and API submissions, password hashing, input length checks and escaped chat display.

## Feature limits / external setup required

- **Live flight tracking:** the included markers are sample positions. A compatible licensed flight-data provider, API key and provider-specific adapter are required.
- **AIR TRAVEL Smart Assistant:** the built-in response mode works without an API key for common travel and aviation questions. It is a local rule-based helper, not a full generative AI model. For more flexible generative answers, configure `OPENAI_API_KEY` and `OPENAI_MODEL` privately on the server.
- **Voice calling:** not enabled in this review build. It needs a tested WebRTC service, secure HTTPS, microphone permissions and STUN/TURN configuration.
- **Email verification and password reset:** not yet implemented; an email delivery provider and verification workflow are required.
- **VIP membership, rewards, community groups, pilot profiles/awards and live notification delivery:** currently roadmap concepts, not working membership or notification systems.
- **AIR TRAVEL TV:** includes the original 10-second promo advert and a narrated app explainer. Additional destination and community videos are still planned.
- **Movie Night:** host/join rooms and sync playback controls for direct MP4/WebM URLs. The host must have rights to show the content, and each guest needs access to the media URL. Protected streaming-service films may not play inside the site; use the distributor’s official app/site for those. The featured Inside Out card links to Disney’s official movie page and does not contain the film.
- **Push notifications:** not yet implemented.
- **Advertising network:** the owner can add manually managed sponsored listings, but automated paid ad delivery and billing are not included.
- **Offline:** the cached public pages and built-in rule-based assistant are available after they have been cached. Maps, community chat, optional generative AI, flight feeds and voice need the internet. Map tiles and Leaflet are loaded from a CDN.
- **Public hosting:** this build runs locally. No public deployment has been performed.

AIR TRAVEL is an independent community website. It must not be used to access, intercept, rebroadcast or replace cockpit radio, air-traffic-control services or official aviation communication systems.

## Before a public launch

1. Choose a hosting provider and deploy behind HTTPS. On a Linux hosting service, install `requirements-production.txt` so the Gunicorn server is included.
2. Set a strong random `SECRET_KEY`, `OWNER_EMAIL`, `OWNER_PASSWORD`, `CO_OWNER_EMAIL`, and `CO_OWNER_PASSWORD` as environment variables.
3. Set `COOKIE_SECURE=1` when HTTPS is active.
4. Add a proper database backup and persistent storage plan.
5. Complete email verification, password reset, moderation, reporting, rate limits and privacy policy.
6. Test Movie Night with multiple accounts over the deployed HTTPS host and only authorised direct media URLs.
6. Connect and test licensed flight data. For optional generative AI, set `OPENAI_API_KEY` in the hosting provider's private environment settings (never in frontend code).
7. Complete WebRTC voice testing before enabling voice calling.
8. Test Chrome, mobile layouts, offline caching and account recovery.

## New cinematic advert and AI app explainer

- The home page now opens with a 10-second AIR TRAVEL promotional video featuring dramatic visual cuts, a British English (Received Pronunciation) synthetic female voiceover, and a generated cinematic instrumental bed. The voiceover says: “The world is waiting. Welcome to Air Travel. Explore, connect and discover with your AI travel guide. Fly, connect, explore.” It starts muted because browsers restrict autoplay with sound; visitors can enable sound or skip the advert.
- AIR TRAVEL TV includes a 46-second narrated app explainer with an illustrated AI guide, chapter cards and synthetic voiceover. The illustrated character is not lip-synced or a live AI video avatar.
- Both MP4s are stored in `static/media/` and play in modern browsers. The AI explainer covers destination discovery, travel tools, the member community, the built-in assistant and upcoming ideas.
- The advert and explainer describe the current review build accurately: displayed aircraft markers are demos unless a licensed provider is connected. The AI explainer is a narrated guide, not a live person.

### Video files

- `static/media/air_travel_10s_ad.mp4` — 10-second launch advert with British English narration.
- `static/media/air_travel_ai_explainer.mp4` — narrated 46-second app explainer.

The AI assistant service itself remains separate from the promotional explainer video. The explainer does not make the optional generative AI integration live by itself.


## Movie Night Club details

- Sign in with an AIR TRAVEL account to create a room or join with a six-character code.
- A room host supplies a direct HTTPS `.mp4` or `.webm` URL, or a video file placed inside `static/media/`.
- The host controls playback. The website synchronises play, pause and seek position to members polling the shared room. Guests may need to tap Enable audio because browsers restrict automatic sound.
- For a real group on different devices, deploy AIR TRAVEL to a public HTTPS host first. `127.0.0.1` is only the local computer.
- Use only media you own or have permission to show. Some subscription services prevent their protected streams from being embedded.
- The Inside Out card links to Disney's official film information page; AIR TRAVEL does not include, upload or stream the copyrighted movie.
