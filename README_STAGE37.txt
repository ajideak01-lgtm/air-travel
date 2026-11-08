AIR TRAVEL — STAGE 37: FRIENDS & FRIEND REQUESTS

Built on Stage 36 Member Profiles.

Features:
- General-mode members can search approved, active, public General-mode member profiles.
- Send, accept, decline, and cancel friend requests.
- View and remove accepted friends.
- Block and unblock members. Blocking removes an existing friendship and cancels pending requests between the accounts.
- Friend request and friendship records are stored in SQLite and tied to account IDs.
- Kids World accounts do not have friend-request features in this stage.
- Owner undercover sessions cannot use friendship actions.
- No private messaging or direct chat is included in this stage.

Safety notes:
- Only limited public profile fields are returned in member search.
- Private profiles are not listed in search.
- Blocked pairs cannot send or accept friend requests.
- Members should not put phone numbers, addresses, school names, or other private information in public profile bios.

Install/run:
1. Extract the ZIP.
2. Install dependencies from requirements.txt.
3. Run START_AIR_TRAVEL.bat on Windows.

Friendship features require a database migration on first launch; the app creates the new tables automatically without deleting existing member data.
