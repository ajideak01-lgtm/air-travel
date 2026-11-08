AIR TRAVEL — STAGE 39: PERSONAL AI + OWNER REVIEW + UNDERCOVER

Included in this stage
1. Personal AI chat history is saved separately for each signed-in account. The server retrieves history using the authenticated account ID; the browser cannot request another member's conversation.
2. Members can clear their own saved AI chat history.
3. The existing Owner Name Review panel lets the owner approve or reject flagged usernames. Approval is still subject to the app's existing age/guardian-consent safeguards.
4. The existing Owner Undercover Mode can select any approved, active member account (including Kids World accounts), without asking for that member's password. Entry and exit are recorded in the owner audit log. Owner-only routes remain blocked while undercover.

AI SETUP REQUIRED
- An authorised adult deployment administrator must configure OPENAI_API_KEY as a server environment secret.
- Optionally set OPENAI_MODEL (default: gpt-4.1-mini).
- Never put the API key in HTML, JavaScript, a public repository, or a ZIP shared with members.
- AI requests use the server-side OpenAI Responses API, with a per-account short-term rate limit. Provider use may incur separate charges.
- If the key is not configured, the app displays a setup notice and chat requests return a clear unavailable message; no fake AI replies are shown.

PRIVACY / SAFETY
- AI history is private to the signed-in account and is not displayed in Owner HQ or undercover mode.
- Do not use undercover mode to read private AI conversations. Undercover mode is for checking the member-facing experience.
- Kids accounts receive age-appropriate assistant instructions. Keep guardian controls and supervision in place.
- AI can make mistakes. Do not enter passwords, precise location, contact details, or sensitive personal information.

INSTALL
1. Back up your existing airtravel.db before replacing project files.
2. Extract this ZIP.
3. Install dependencies with: python -m pip install -r requirements.txt
4. Configure SECRET_KEY and (when ready) OPENAI_API_KEY on the server, not in browser files.
5. Run START_AIR_TRAVEL.bat on Windows.
6. Sign in as a member and open AIR TRAVEL AI. Send a test message, refresh, and confirm your own history remains. Use Clear my chat history to remove it.
7. As owner, test Owner HQ > Name Review and Owner HQ > Test as a Member.

TEST STATUS
- Python compilation: passed.
- ZIP integrity: passed.
- Database schema and route integration: reviewed in source.
- Full Flask/browser/API integration tests were not run in this build environment because Flask is not installed and no AI API key is configured.
- Undercover Mode and Owner Name Review are carried forward from Stage 38; they were not redesigned in this stage.
