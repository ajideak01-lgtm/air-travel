AIR TRAVEL — STAGE 2 SMART REGISTRATION

This update builds on Stage 1 and keeps the existing app features and database.

Guest accounts:
- Sign up with full name, age, username and password. Guest email field removed.
- Sign in with username and password.
- After automatic checks approve an account, the member is signed in and sent to Customise Your Profile.
- Profile choices include avatar, favourite aircraft, country, background and short bio.
- Existing older accounts remain in the database; their legacy email-based records are retained.

Approval and child safety:
- The included registration screening is a basic local rules-based check, NOT a connected generative AI model, identity check or age verification service.
- Registrations with rule flags go to Owner HQ for review.
- Accounts under age 13 are held pending a parent/guardian consent process; this ZIP does not implement that consent verification, so those accounts cannot be self-approved.
- Do not publish children's photos, exact birth dates, family details, school, home address or contact information.

Owner:
- Owner Login remains separate and continues to use the configured owner email/password.
- Do not deploy the default local demo owner credentials to the public internet. Set OWNER_EMAIL, OWNER_PASSWORD and a strong SECRET_KEY in environment variables before deployment.

Run locally:
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run: pip install -r requirements.txt
4. Run START_AIR_TRAVEL.bat on Windows, or: python app.py
5. Open http://127.0.0.1:5000

Testing note: Python syntax and ZIP integrity were checked. A full Flask/browser test could not be run in this environment because Flask is not installed here.

STAGE 3 – OWNER UNDERCOVER MODE + EXP WALLET

Owner Undercover Mode:
- Sign in through the separate Owner Login.
- Open Owner HQ and choose “Enter Undercover Mode”.
- Select an existing approved guest/member account.
- The app switches to that member account; owner-only routes remain unavailable.
- Use “Return to Owner” in the navigation to restore the owner session.
- To test with a fresh account, first create it through the normal Guest Sign Up flow and complete approval/profile setup.

EXP Wallet:
- Signed-in members can open EXP Wallet from the navigation or /exp-wallet.
- It shows current EXP, total recorded EXP earned, total recorded EXP spent, and up to 100 latest transactions.
- Purchases and EXP redemptions that already deduct EXP in this build are recorded in the transaction ledger.
- Owner privilege display is separate from the member EXP wallet.

Testing note: Python syntax and ZIP integrity were checked for this stage. A full Flask/browser test was not run in this environment because Flask is not installed here. Install requirements with: pip install -r requirements.txt

STAGE 4 – AIR TRAVEL AI (GENERAL-PURPOSE ASSISTANT)

What is included:
- A signed-in member page at /ai-assistant, linked in the main navigation.
- General-purpose help for learning, school explanations, science, technology, writing, creativity, travel and aviation.
- Server-side connection to the OpenAI Responses API. The API key is never sent to the browser.
- Short conversation context is held in the page while it remains open. Chat messages are not written to the AIR TRAVEL database.
- Age-aware instructions and reminders not to share passwords, home addresses, school/contact details or other private information.

IMPORTANT – CONNECTING THE AI:
- The AI connection is implemented but will not answer until an adult project administrator configures an OpenAI API key on the server.
- Set OPENAI_API_KEY as a server environment variable. Optionally set OPENAI_MODEL (default: gpt-4.1-mini).
- Never put the API key in app.py, HTML, JavaScript, a public ZIP, or a browser setting. Keep it private on the server.
- API usage may incur charges. A parent/guardian or responsible adult should manage the account, spending limits and key. Do not share payment details with children.
- If no key is configured, the assistant displays a clear setup message rather than pretending it is connected.
- This is a text assistant; web search, voice, image generation, external app actions and long-term memory are not included in Stage 4.

API reference: https://developers.openai.com/api/reference/resources/responses

Testing note: Python syntax was checked. A full Flask/browser/API test was not possible in this environment because Flask is not installed and no API key was supplied. Install requirements and configure the key before testing the live AI.


STAGE 5 — AIR TRAVEL AI ASSISTANT
--------------------------------
The general-purpose AI chat page and Flask backend are included. The assistant
supports general learning, writing, technology, travel and aviation questions.
It is NOT connected until an administrator configures an API key on the server.

SECURE SETUP (an adult administrator should do this)
1. Create/manage the API account and billing with the service provider.
2. Keep the API key private. Never paste it into app.py, HTML/JavaScript,
   screenshots, messages, or a ZIP file.
3. On the Windows computer that runs AIR TRAVEL, open PowerShell.
4. In that PowerShell window, set the key for that session:
      $env:OPENAI_API_KEY = "PASTE_THE_KEY_HERE"
   Do not share that window or the key with anyone.
5. In the same PowerShell window, start the app:
      cd "PATH_TO_THE_AIR_TRAVEL_FOLDER"
      py -m pip install -r requirements.txt
      py app.py
6. Sign in to AIR TRAVEL and open the AIR TRAVEL AI page. Test a simple
   question. Check the provider usage dashboard regularly and set a spending
   limit if available.

For a hosted deployment, configure OPENAI_API_KEY in the hosting provider's
private environment-variable / secret settings. Do not put the key in the ZIP.
Optional model setting: OPENAI_MODEL (defaults to gpt-4.1-mini).

Stage 5 safeguards in this build:
- API key is read only on the Flask server.
- AI chat requires a signed-in account.
- Per-account request throttling and message-size limits are enabled.
- Chat messages are not saved to the AIR TRAVEL database.
- The assistant is instructed to use age-appropriate responses and protect
  sensitive personal information.
- A live provider connection cannot be verified without an administrator's
  configured key and an internet-connected test.

IMPORTANT: The built-in request limiter is per app process. A public,
multi-worker deployment should use a shared rate-limit store and HTTPS.

STAGE 6 - EXP WALLET & TRANSACTION SAFETY
-----------------------------------------
- Added a database-level guard that prevents member EXP balances from going below zero.
- Hardened Airport Tycoon upgrades so the balance debit, EXP ledger entry, and upgrade happen in one SQLite transaction.
- Concurrent upgrade requests are serialized and re-check the latest balance before spending.
- If an upgrade fails, the transaction rolls back so no EXP is deducted and no upgrade is granted.
- Gift Shop and Premium EXP redemptions already use atomic transactions and are retained.
- The EXP Wallet shows the current balance, earned/spent totals, and recent ledger entries.

Testing performed for this build: Python syntax compilation, ZIP integrity, application health route, and database negative-balance guard. Live payment checkout and external AI API calls are not tested/configured by this stage.

STAGE 7 — OWNER CONTROL CENTRE & SECURITY AUDIT
------------------------------------------------
- Owner HQ now includes member account management controls.
- The owner can suspend or restore a member account from the separate Owner HQ.
- Suspended members are blocked from signing in and active member sessions are invalidated when next checked.
- Owner actions are written to a private audit log: member suspension/restoration, account approval, EXP awards and event publication.
- The Owner HQ shows the 30 most recent audit entries.
- Existing member records are migrated with account_status='active'; existing EXP balances and transaction history are preserved.

Security notes:
- These controls are not a substitute for HTTPS, secure production secrets, CSRF protection, backups or a professional security review.
- Keep owner credentials and SECRET_KEY in server environment variables. Change the local demo owner password before any deployment.
- Full Flask/browser testing was not available in the build environment because Flask could not be installed offline. Python syntax, SQLite schema, migration and ZIP integrity checks were performed.

STAGE 8 — ACCOUNT & REQUEST SECURITY HARDENING
----------------------------------------------
- Added CSRF protection to state-changing POST/PUT/PATCH/DELETE requests.
  Standard HTML POST forms receive a per-session token automatically; the AI
  JSON chat request sends the same token in an X-CSRF-Token header.
- Added temporary sign-in throttling after five failed attempts for the same
  account identifier and source IP within a 15-minute window.
- Successful sign-in clears the relevant failed-attempt counter.
- Successful sessions are marked permanent with an eight-hour lifetime.
- Added browser security headers: X-Content-Type-Options, X-Frame-Options,
  Referrer-Policy, Permissions-Policy and no-store caching for responses.
- Added COOKIE_SECURE configuration. Set COOKIE_SECURE=1 only when serving
  AIR TRAVEL over HTTPS; leave it unset for local http://127.0.0.1 testing.

Important limitations:
- The login throttle is held in process memory. A multi-worker deployment
  should use a shared rate-limit store so limits apply across workers.
- These protections do not replace HTTPS, strong production secrets, backups,
  secure hosting, dependency updates or a professional security review.
- Review all routes and test the complete application before public launch.

Stage 8 checks performed: Python syntax compilation and ZIP integrity. A full
Flask/browser test was not run in this build environment. CSRF and login
throttling should be verified in a local Flask installation before launch.

STAGE 9 — COMMUNITY SAFETY & MODERATION
---------------------------------------
- Members can report another member's visible community post using a fixed
  set of safety categories and optional short details.
- A member can submit only one report per post; duplicate reports are rejected.
- Reports are private and visible in the separate Owner HQ review panel.
- The owner can hide a reported post, dismiss a report, or permanently delete
  the post. Hiding removes it from the public community board.
- Moderation actions are recorded in the existing owner security audit log.
- Existing posts are preserved and migrated with a visible moderation status.
- Community pages remind members not to publish passwords, addresses, school
  details or private contact information.

Limitations and launch checks:
- This is a basic report-and-owner-review workflow, not automated moderation
  or real-time messaging. A human owner must review reports.
- The community board remains public to signed-in and signed-out visitors;
  reporting is available to signed-in member accounts.
- Before opening the community to children or the public, configure guardian
  consent where required, moderation coverage, privacy rules, HTTPS, backups,
  and an incident-response process. Do not treat self-entered age as proof.
- Python syntax compilation, SQLite schema checks, route-presence checks and
  ZIP integrity were performed. A live Flask/browser test was not performed
  because Flask is not installed in this build environment.


STAGE 10 — PRIVATE TRIP PLANNER
-------------------------------
- Added a member-only Trip Planner linked in the main navigation.
- Members can save trip title, origin, destination, departure/return dates,
  optional estimated budget and travel notes.
- Trip plans are stored per account and are only shown to their owner.
- Members can delete their own saved plans; one member cannot delete another
  member's plan.
- Validates required fields, date format, return date order, different
  origin/destination and budget bounds.
- Uses the existing session login and CSRF protection.
- This is an organiser only: it does not book flights, reserve hotels, verify
  visas, display live fares or process payments. Do not enter passport numbers,
  payment details, home addresses or other sensitive information.

Stage 10 checks: Python syntax compilation, ZIP integrity, schema creation,
plan insert/list isolation, date validation logic and account-scoped deletion
were checked. Full interactive browser testing was not performed.


STAGE 11 — FLIGHT ACADEMY
- Added six beginner aviation lessons: aviation basics, aircraft parts, airport journey, flight crew, weather and flying, and passenger safety.
- Members must sign in to use the Academy. Lesson completion is saved per account in the academy_progress table.
- Repeated completion submissions do not create duplicate progress records. Progress is displayed as a personal completion bar.
- Links to the existing Aviation Quiz and Games Arcade are included.
- Educational content only; it is not pilot training, live weather advice, operational guidance or an aviation licence course.
- Stage 10 Trip Planner and all prior project files are retained.

TESTING NOTE
Python syntax, database table creation, lesson completion idempotency, account-level progress isolation, route authentication and ZIP integrity were checked. Full browser/device testing and external live-service integrations were not performed.


STAGE 12 — FLIGHT ACADEMY COMPLETION CERTIFICATE
------------------------------------------------
- Members who complete all six Stage 11 Flight Academy lessons can issue one personal completion certificate.
- The certificate is linked to the signed-in account and has a unique verification code.
- Members can print it or use the browser print dialog to save a PDF.
- A public verification page confirms whether a code was issued, without revealing the member name or profile.
- The certificate is a beginner-course learning milestone only. It is not a pilot licence, professional qualification, flight training credential or proof of operational competence.
- Existing Stage 11 lesson progress is preserved. No EXP is charged for certificates.

STAGE 12 TESTING
- Python syntax compilation, database table creation, unique account issuance, verification-code lookup and ZIP integrity were checked.
- Full Flask/browser printing and navigation tests were not run in this build environment.


STAGE 13 — AVIATION CAREER & PROFESSIONAL WORLD
- Member-only Aviation Career Centre with five career paths: Pilot, Cabin Crew, Aircraft Engineer, Air Traffic Controller and Airport Manager.
- Ten introductory career challenges with account-specific completion records.
- Fictional in-app career applications; no real recruitment or contact details required.
- Owner-only Career Management page for publishing extra educational challenges; actions are added to the owner audit log.
- Career content is educational only and does not provide licences, operational training or employment.
- Existing Stage 12 academy and certificate features are retained.

STAGE 14 — AVIATION CAREER SKILLS TEST
--------------------------------------
Adds a five-question interactive career-readiness assessment at /career-assessment.
Members must be signed in. Each submission is scored and stored against that
member's account; the latest five attempts are shown. A score of 4/5 or 5/5
earns a Career Skills badge for that attempt. The activity practices teamwork,
communication, responsible escalation and record-keeping.

This is educational practice only. It is not a recruitment test, professional
assessment, licence examination or evidence of qualification. It does not
provide operational flight, maintenance or air-traffic instructions.

STAGE 14 TEST NOTES
-------------------
Run `python -m py_compile app.py` to check syntax. The database table
career_assessments is created by the normal application schema initialisation.
Interactive browser testing and production deployment testing must still be
performed in the target environment.

STAGE 15 — OWNER ANNOUNCEMENTS CENTRE
- Owner HQ now includes an announcement composer with title and message fields.
- Publishing is restricted to the separately authenticated owner account and protected by the app's existing CSRF check.
- Published announcements appear in the public Announcements Centre and the latest three appear on the homepage for all visitors/members.
- Owner HQ lists published announcements and allows the owner to delete an announcement; publish/delete actions are written to the owner audit log.
- Announcement titles are limited to 100 characters and messages to 3,000 characters. Do not include private member information in public announcements.
- Existing announcements and app data are stored in the SQLite database; the announcements table is created automatically on startup.


STAGE 14 REDESIGN (included in this Stage 15 package)
====================================================
The previous Career Skills Test page has been replaced by the Virtual Aviation Experience.
Members can complete eight short educational missions across Airport Manager, World Explorer,
Aircraft Explorer, Passenger Experience, Weather Explorer and Trip Planner themes.
Progress is saved separately for each account. Completing all eight missions earns an
in-app World Explorer badge. No EXP is charged or awarded by this activity.
The activities are fictional learning games, not aircraft controls, real ATC procedures,
professional training, travel authorisation or real job qualifications.
The Stage 15 Owner HQ Announcements Centre remains included.

Validation: Python syntax compilation, SQLite schema creation, mission answer/progress logic,
and ZIP integrity checked. Full browser testing was not performed in this build environment.

STAGE 16 — OWNER TRIBUTE & FOUNDERS HALL
========================================
- Replaces the old Founder Tribute page with a dedicated AIR TRAVEL Founders & Leadership Tribute.
- Publicly identifies AKINOLA AJIDE as Founder & Owner and JAYDINE as Co-owner, and records 2026 as the project's founding year.
- Includes a project story, development milestone cards and a clear notice that AIR TRAVEL is still in development and has not officially launched.
- Owner HQ includes a shortcut to a private tribute editor. Only the authenticated owner can update the public dedication message.
- The tribute editor enforces a 30–1,200 character limit and protects updates with the app's existing CSRF check.
- Tribute changes are recorded in the owner audit log and stored in SQLite. The database creates the tribute settings table and seeds the default message without overwriting a message already saved by the owner.

STAGE 16 VALIDATION
-------------------
Python syntax compilation, Jinja template parsing for both tribute pages, SQLite tribute-table creation and message update, owner-route protection presence, previous-stage route presence, and ZIP integrity were checked. Full Flask/browser/device testing was not performed in this build environment.


STAGE 16 PHOTO UPDATE — OWNER TRIBUTE PORTRAIT
=============================================
- Added the founder portrait supplied for the AIR TRAVEL Owner Tribute.
- The image is stored in private_media/ (outside static assets), with embedded metadata removed.
- The authenticated owner can preview it in Owner HQ → Manage Owner Tribute.
- The public tribute page keeps the crown avatar by default. The photo delivery route returns 404 unless PUBLIC_OWNER_PHOTO_APPROVED=1 is set in the hosting environment.
- A parent/guardian should approve public display first; an adult deployment administrator should then set PUBLIC_OWNER_PHOTO_APPROVED=1. Keep it at 0 to keep the portrait private.
- The owner-only preview is served through an owner-protected route with private/no-store caching.

PHOTO UPDATE VALIDATION
-----------------------
Python syntax compilation, private image file presence, image format/dimensions, no-static-folder placement, owner-only preview route, public approval-flag gate, README/.env configuration and ZIP integrity were checked. Full Flask/browser testing was not performed in this build environment.


STAGE 17 — OWNER-MANAGED FOUNDER TIMELINE
========================================
- The public Owner Tribute now reads its development milestones from SQLite.
- Added Owner HQ → Founder Timeline Manager. The authenticated owner can add,
  edit and delete timeline entries; changes appear on the public tribute page.
- Timeline fields are validated: label 2–60 characters, title 2–100, and
  description 8–300. The public timeline is limited to 12 entries.
- Four starter milestones are inserted only when the timeline table is empty.
  Reinitialising the database does not overwrite owner edits or add duplicates.
- All changes use the existing POST/CSRF and owner-only protections and are
  recorded in the owner audit log. All text is rendered through Jinja escaping.
- The founder portrait remains private by default and still requires the
  separate PUBLIC_OWNER_PHOTO_APPROVED=1 server setting after guardian approval.

STAGE 17 VALIDATION
-------------------
Python syntax compilation, schema creation, starter milestone seeding,
reinitialisation idempotency, CRUD database operations, 12-item cap logic,
route/navigation presence, and ZIP integrity were checked. Full Flask/browser
testing was not performed because Flask is not installed in this build
environment.


STAGE 18 — OWNER HQ COMMAND DASHBOARD
=====================================
- Added a separate Owner HQ → Command Dashboard page at /owner/overview.
- The overview reports aggregate counts for member accounts and account status, community posts and open reports, trip plans, passport stamps, Academy progress and certificates, career progress and applications, virtual missions, announcements, events, shop purchases and virtual EXP awards.
- A rolling seven-day summary shows new member accounts, completed Academy lessons and completed virtual missions.
- The page shows the latest 12 owner audit action labels and timestamps. The full owner audit log remains in Owner HQ.
- Added a shortcut to the overview from Owner HQ and a navigation link visible only to the authenticated owner.
- The overview is protected by the existing owner_required decorator. It is read-only and does not change member balances or records.
- Privacy by design: the overview uses aggregate metrics and does not show member names, ages, usernames, private trip notes, application motivations, private messages or contact details.
- Metrics are counts from the app's SQLite database. They do not indicate that live flight providers, payment systems or public hosting are connected.

STAGE 18 VALIDATION
-------------------
Python syntax compilation, SQLite schema and aggregate query checks, owner-only route/navigation presence, template parsing, previous-stage route/file preservation and ZIP integrity were checked. Full Flask/browser/device testing was not performed in this build environment because Flask is not installed here.


STAGE 19 — PUBLIC EVENTS CENTRE & OWNER EVENT MANAGER
====================================================
- Added a public Events Centre at /events and linked it from the main navigation and homepage.
- Members and visitors can view upcoming AIR TRAVEL activities, competitions, learning sessions and community events without signing in.
- Owner HQ event publishing now supports a category and optional event date/time. Displayed event times are labelled Nigeria time (WAT).
- Added Owner HQ → Event Manager at /owner/events. The authenticated owner can edit event titles/details/categories/dates and publish, cancel or mark events completed.
- Cancelled and completed events are retained in the public archive rather than silently deleted. Legacy Stage 18 events are preserved and migrated with a default Community category and published status; their date is shown as not specified.
- Every create, edit and status change is written to the existing owner audit log. Existing owner-only authentication and CSRF protections apply.
- Event text is rendered through Jinja auto-escaping. Event forms enforce title/details limits and an allow-list of categories/statuses.
- This is a community calendar only. It does not create real-world travel bookings, tickets, external event registrations or payment collection. Avoid publishing personal member information or private meeting details.

STAGE 19 VALIDATION
-------------------
Python syntax compilation, backwards-compatible SQLite event schema migration, legacy-event preservation, create/update/status database operations, date/category validation cases, public/owner route definitions, navigation links and ZIP integrity were checked. Full Flask/browser testing was not performed because Flask is not installed in this build environment.


STAGE 20 — SEPARATE KIDS WORLD HOME & FOUR-AREA EXPERIENCE
=========================================================
- Added a distinct, colourful, mobile-friendly Kids World homepage.
- Kids navigation and homepage show exactly four activity areas: Story Books, Movie Night, Games and Exam (plus Home and Sign out).
- Added four original short story books with individual reading pages.
- Kids Movie Night plays a parent/guardian-approved local video file selected on the device. The file is not uploaded; AIR TRAVEL does not host or bundle films.
- Kids Games provides two simple browser mini-games: Sky Star Catcher and Perfect Timing. They are fictional arcade games, not flight training.
- Added a ten-question untimed practice exam. Scores and the latest five attempts are stored privately per account; 7/10 is the practice pass threshold. The exam gives and charges no EXP and is not a school grade.
- Kids-mode accounts are restricted from opening general-mode app routes directly. The welcome ad is suppressed in Kids World.
- Owner HQ → Member management now allows the authenticated owner to set each member account to Kids World or General Experience. Changes are added to the owner audit log.
- Existing General Experience pages and features are preserved.
- A mode selector is not age verification or a complete child-safety system. A responsible adult should supervise account setup and choose approved videos. Apply guardian consent, moderation, minimal data collection and secure hosting before live use.

STAGE 20 VALIDATION
-------------------
Python syntax compilation, schema SQL execution, Kids route and navigation presence, Kids mode route restriction, Owner-only mode-management route, story content, private exam storage and ZIP integrity were checked. Full browser testing was not performed because Flask is not installed in the build environment.


STAGE 21 — KIDS WORLD STUDIO (OWNER HQ)
======================================
- Added a private Owner HQ → Kids World Studio page. Only the authenticated owner can open the Studio or change content.
- The four Kids World activities stay the same: Story Books, Movie Night, Games and Exam. No extra general-mode modules were added to Kids navigation.
- Moved the four original storybooks into a persistent database library. The owner can add original stories, edit titles/text/emojis, and publish or unpublish each story. Unpublished stories are not shown to Kids accounts.
- Moved the Kids practice exam into a persistent question bank. The owner can add and edit questions, set three answer choices and choose the correct answer, and publish or unpublish questions. Correct answers remain server-side.
- Kids exam scoring reads the currently published questions. The practice pass mark is 70% (rounded up), and each member's latest five attempts remain private to that account. The exam does not award or deduct EXP.
- The Studio shows aggregate attempt count and average score only; it does not display individual children's names or results.
- Every create, update and publish/unpublish action is recorded in the existing owner audit log. CSRF protection and owner-only route protection are applied.
- Movie Night remains a local-device video player. AIR TRAVEL does not host, upload or bundle films; a parent or guardian should select approved videos.
- Content is rendered through Jinja auto-escaping. Input lengths, paragraph counts, option count and unique answer options are validated. Story content is original text supplied by the owner.

STAGE 21 VALIDATION
-------------------
Python syntax compilation, full ZIP integrity, SQLite schema creation, Stage 20 table/data compatibility, one-time seeding of the original four stories and ten exam questions, content add/edit/publish state operations, dynamic practice scoring, route/navigation presence, Kids-mode route restriction and owner-only decorator presence were checked. Full Flask/browser/device testing was not performed because Flask is not installed in this build environment.


STAGE 22 — KIDS WORLD PRIVATE PROGRESS TRACKER
==============================================
- Kept the Kids World homepage and navigation limited to the same four activities: Story Books, Movie Night, Games and Exam. No fifth Kids section was added.
- Added a small progress strip directly on the Kids homepage: stories read, best Sky Star Catcher score, Perfect Timing wins and best practice-exam result.
- Added a “Mark as read” action to each published story. The Story Books list shows which stories the signed-in member has read.
- Kids Games now saves the member's personal best star score and successful Perfect Timing wins.
- Exam history continues to be saved privately to the signed-in member's account; the homepage shows that member's best exam result.
- Added a private per-account activity table with database constraints. Members cannot view or change another member's progress through the Kids interface.
- Owner HQ → Kids World Studio shows aggregate activity totals only, without child names or individual progress rows.
- Progress uses no EXP, money, paid items, public leaderboard or public profile. Movie Night continues to play a locally selected, parent/guardian-approved video and does not upload media.
- The progress-save endpoint is Kids-mode-only, requires the existing CSRF token, validates activity types and score ranges, and records only the current member's account.

STAGE 22 VALIDATION
-------------------
Python syntax compilation, database schema creation, progress-table constraints, account-isolated progress records, story completion idempotency, best-score aggregation, Kids endpoint whitelist and ZIP integrity were checked. Full Flask/browser/device testing was not performed because Flask is not installed in this build environment.


STAGE 23 — KIDS WORLD MASCOT COMPANION & STORY EXTRAS
=====================================================
- Added Sky, an original friendly airplane mascot, to the Kids World welcome page.
- Added a short personalised greeting that changes based on the member's private progress.
- Added a small Sky helper card on Kids pages other than the homepage. It stays inside the existing four-section Kids experience.
- Added browser-local voice playback for Sky's greeting. It uses the device/browser speech feature only; no microphone permission or external voice service is requested.
- Added “Read to me”, “Pause” and “Stop” controls to each Kids story. Browser text-to-speech reads the visible story locally; if the browser does not support speech synthesis, the story remains readable on screen.
- Added a private favourites shelf inside the existing Story Books section. Each member can add or remove published stories from their own favourites. Favourites are not public and do not create a fifth Kids section.
- Added a “Sky's Story Pick” feature within Story Books. It highlights the first currently published story in library order; this is a featured pick, not an automatically rotating weekly schedule.
- Kept the Kids homepage and navigation limited to Story Books, Movie Night, Games and Exam. No new top-level Kids area, chat, public leaderboard, paid feature or EXP mechanic was added.
- The mascot voice and story read-aloud depend on the browser/device speechSynthesis feature and may use the device's installed English voice. AIR TRAVEL does not upload story text for speech.

STAGE 23 VALIDATION
-------------------
Python syntax compilation, SQLite schema creation for the favourites table, per-account favourite isolation, favourite add/remove logic, Kids route-whitelist inclusion, Jinja template syntax parsing where the installed template parser is available, static mascot file presence and ZIP integrity were checked. Full Flask/browser/device speech testing was not performed because Flask could not be installed in this build environment and browser speech support varies by device.


STAGE 24 — KIDS WORLD HOMEPAGE REDESIGN
---------------------------------------
The Kids World landing page has been redesigned to follow the approved bright
blue-sky, globe, smiling-airplane mascot concept. It now has four large,
responsive activity cards linked to the actual Kids sections: Story Books,
Movie Night, Games and Exam. Sky's welcome message and browser speech button
remain available. The account chip shows the signed-in member's own username
(or display name) and current EXP balance. A private progress strip displays
that member's existing story, game and exam metrics. The homepage navigation
is simplified; section navigation remains available on Kids subpages.

This is a responsive HTML/CSS implementation, not a static screenshot: the
four cards are real links, profile information is dynamic, and progress values
come from the existing per-account database records. The General Experience
and Owner HQ have not been intentionally redesigned by this stage.

Checks performed for Stage 24: Python syntax compilation; full base-template and
Kids-home Jinja rendering with test account values; SQLite schema and existing
user-field migration; smoke checks of the Kids homepage progress queries; mascot
asset verification; and ZIP integrity. The rendered templates were also checked
in Chromium at desktop and 390px mobile widths; four activity cards and four
progress items displayed and no horizontal overflow was found. Flask is not
installed in the build environment, so Flask route/client integration tests were
not performed.


STAGE 25 — KIDS WORLD GAMES PACK
--------------------------------
The Kids World Games page keeps the existing Sky Star Catcher and Perfect
Timing games and adds three browser mini-games inside the existing Games
section: Airplane Memory Match, Airport Pattern Puzzle and Airport Word Search.
No fifth navigation section has been added to the Kids homepage.

Personal-best scores for the three new games are stored per signed-in Kids
account in the kids_extra_game_scores table. The score endpoint is restricted
to Kids-mode member accounts, validates the game key and score range, requires
the app's existing CSRF token, and never deducts or awards EXP. Scores are
personal progress indicators and are not official competition results or
redeemable rewards.

The new games run in the browser and do not require external game accounts.
Stage 24's illustrated Kids homepage, mascot, original Kids sections, Owner HQ,
and previous project files are retained.

Stage 25 checks: Python syntax compilation, JavaScript syntax check (when
Node.js is available), SQLite schema creation and per-account score isolation,
score validation logic review, and ZIP integrity. Full Flask/browser integration
testing is not claimed where Flask is unavailable in the build environment.


STAGE 26 — KIDS WORLD MOVIE NIGHT PLAYLIST
------------------------------------------
- Upgraded the Kids World Movie Night page with a local-device video playlist.
- Choose multiple MP4, WebM or OGG videos, play a selected item, move to the previous/next video, remove individual items, or clear the playlist.
- The next item is selected automatically when a video finishes.
- Video files are read locally by the browser using temporary object URLs; they are not uploaded to the AIR TRAVEL server.
- The queue exists only for the current page visit and is cleared when the page is left. Original files on the device are not changed.
- The Kids homepage remains the approved four-section design: Story Books, Movie Night, Games and Exam.
- The General Experience Movie Night page and existing Stage 25 games/features are preserved.
- Children should choose content with a parent/guardian; this interface does not verify content ratings or guardian approval.

STAGE 26 VALIDATION
-------------------
- Python syntax compilation and AST parsing: performed.
- Movie Night template compilation with Jinja: performed.
- JavaScript syntax check with Node.js: performed.
- JavaScript behavior checks with a mocked DOM: passed (multi-file queue, next/previous state, remove, clear, auto-next and object-URL cleanup).
- Full Chromium/browser interaction test: not completed because the environment blocks browser navigation.
- Full Flask server integration test: not performed because Flask is not installed in the build environment.
- ZIP integrity: performed.


STAGE 28 — KIDS WORLD EXAM REVIEW & LEARNING FEEDBACK
----------------------------------------------------
- After a Kids practice exam is submitted, the member sees their score and a question-by-question answer review.
- The review shows the member's selected answer, the correct answer when needed, and a simple explanation.
- Each completed attempt stores a small review snapshot so the correct answer and explanation remain consistent with the question as it appeared at test time.
- Reviews are retrieved only when the attempt belongs to the currently signed-in Kids member. Recent scores remain private to that account.
- Owner HQ → Kids World Studio now lets the owner add and edit a short explanation for each question. Explanations appear only after submission; correct answers are not displayed on the question page before the exam is submitted.
- Existing question and attempt records are preserved through backward-compatible SQLite migrations. Older questions receive a safe general explanation if no explanation was recorded.
- The approved Kids homepage remains unchanged and still has exactly four main sections: Story Books, Movie Night, Games and Exam.
- No EXP, payment, public scoreboards, child-to-child messaging, or extra Kids homepage section was added.

STAGE 28 VALIDATION
-------------------
- Python syntax compilation and AST parsing: performed.
- Jinja compilation of Kids Exam and Owner Kids Studio templates: performed.
- SQLite migration from the Stage 26 schema, repeat migration, question explanation updates, saved review snapshots, and per-account review isolation: passed.
- ZIP integrity: performed.
- Full Flask route/client and end-to-end browser testing: not performed because Flask is not installed in the build environment.

BUILD NOTE
----------
Stage 27 ZIP was not present among the available project files. Stage 28 is built directly on the latest available source, Stage 26, and therefore does not claim to include any unprovided Stage 27 changes.


STAGE 29 — AIRLINE EMPIRE (VIRTUAL AIRLINE MANAGEMENT)
------------------------------------------------------
- Added a signed-in, General Experience member page at /airline-empire.
- Each member account may create one virtual airline with a name, unique 2–4 character code, logo emoji and brand colour.
- Members can build a virtual fleet, open destination routes, recruit fictional staff teams, and schedule fictional game flights.
- A Virtual Pilot Team is required before a flight can be scheduled or completed. Aircraft and routes must belong to that member's own airline.
- Completing a due virtual flight awards a small amount of EXP and reputation. The reward is credited to the airline owner's member wallet and recorded in both the main transactions history and the airline finance ledger.
- EXP debits, purchases, rewards and flight completion are committed atomically. Insufficient balances, duplicate actions and failed transactions do not leave a partial wallet debit.
- Limits: one airline per account, 12 aircraft, 12 routes, five scheduled flights at a time, five completed game flights per Nigeria calendar day, and bounded virtual staff-team counts.
- Added an active virtual airline leaderboard, ranked by completed game flights and then reputation.
- Added Owner HQ → Airline Control. The owner can update the league challenge, inspect aggregate airline activity, and pause or restore a member's virtual airline. Owner actions enter the existing audit log.
- Airline Empire is unavailable in Kids World. The Kids homepage remains limited to Story Books, Movie Night, Games and Exam.
- All airlines, aircraft, routes, staff, schedules, flights and rewards are fictional game content. This feature does not book real tickets, publish real flight schedules, operate aircraft, control airlines, or connect to airline systems. EXP is not cash and no real-money checkout is involved.

STAGE 29 VALIDATION
-------------------
- Python syntax compilation: passed.
- SQLite Stage 29 schema creation: passed.
- One-airline-per-account and globally unique airline-code constraints: passed.
- Starter setup affordability using the standard 1,000 EXP starting balance: passed (550 EXP starter aircraft + 250 EXP pilot team + 150 EXP route).
- EXP debit/credit ledger pairing and overspend rejection checks: passed.
- One-time virtual flight completion and account-specific reward checks: passed.
- Jinja parser checks for the base layout, member Airline Empire page and Owner Airline Control page: passed.
- New template URL endpoint references: checked against view function names.
- ZIP integrity: checked.
- Full Flask server/browser end-to-end testing: not performed because Flask is not installed in the build environment.

BUILD NOTE
----------
This Stage 29 package was built from the available Stage 28 ZIP. Stage 27 was not present among the available project files, and Stage 28's own build note records that gap. Therefore this package does not claim to include any separate, unavailable Stage 27 changes.


STAGE 30 — OWNER UNDERCOVER MODE (MEMBER EXPERIENCE TESTING)
-----------------------------------------------------------
- Upgraded Owner HQ → “Test as a Member” with a clearer member chooser.
- The chooser only lists approved, active member accounts. Suspended, pending, and non-member accounts cannot be selected.
- The chooser displays only the member name/username, General or Kids World mode, and EXP balance. It does not expose email addresses, ages, password information, or other private account fields.
- Added a required confirmation explaining that this is the real selected account. Any saved action while undercover (for example, profile changes, posts, game results, or EXP purchases) affects that member's actual account.
- On entry, the owner session is replaced by the selected member identity, so the application presents the member's actual experience and owner-only routes are blocked by the existing role-based access checks.
- A persistent gold Undercover banner appears throughout the app, including Kids World, showing the selected member and experience mode, with a one-click “Exit & Return to Owner HQ” control.
- Returning restores the original authenticated owner account even if the selected member was suspended or became unavailable during the test. The return route does not rely on the member session still being valid.
- Both entry and return are recorded in the existing Owner HQ audit log. CSRF tokens are refreshed when switching identities.
- No member passwords are requested, displayed, changed, or copied. The feature uses the owner's existing authenticated session and the selected account's stored identity.

STAGE 30 VALIDATION
-------------------
- Python syntax compilation: performed.
- Jinja parsing of the base layout and Undercover chooser: performed.
- SQLite account eligibility query: passed for approved/active accounts and rejected suspended, pending, and owner accounts.
- Undercover start/return audit inserts: passed.
- Session identity transition logic: source-reviewed; the running Flask route/client integration was not performed because Flask is unavailable in the build environment.
- Owner-only access continues to use the existing owner_required role check; the switched session is a member role.
- ZIP archive integrity: passed.

BUILD NOTE
----------
Stage 30 is built from the supplied/available AIR_TRAVEL_STAGE29_AIRLINE_EMPIRE.zip. Stage 29 features are retained in the package.

STAGE 31 — SECURITY & SAFETY CENTRE
-----------------------------------
Added in this stage:
- Member Security & Safety Centre, available from the General experience navigation.
- Password update form requiring the current password, a 10-character minimum,
  matching confirmation and a password different from the current one.
- Account activity history for account creation, successful sign-in, sign-out,
  password changes and support-report submissions.
- Member support reporting for technical bugs, account-security concerns,
  community-safety concerns and other issues.
- A private Owner Security Centre to review reports and mark them reviewed or
  closed. Owner actions are recorded in the existing owner audit log.
- CSRF protection and existing security response headers continue to apply.
- Kids World keeps its four-section home/navigation; this member Security Centre
  is not added as a fifth Kids homepage section.

Important limitations:
- This stage does not implement multi-factor authentication, email/SMS account
  recovery, device-by-device session management, or automatic suspicious-login
  detection. The Security Centre states these limitations clearly.
- Account activity is an in-app audit trail, not a guarantee that every browser
  or server event is recorded.
- Support reports are stored in the local app database. They are not emailed
  automatically and require an owner to review them in Owner HQ.
- Before public deployment, an adult administrator should configure a strong
  SECRET_KEY, OWNER_EMAIL and OWNER_PASSWORD in server environment variables,
  use HTTPS, set COOKIE_SECURE=1, and arrange secure database backups.

Stage 31 checks performed:
- Python syntax compilation passed.
- SQLite schema execution passed and the new support/activity tables were found.
- ZIP archive integrity check passed after packaging.
- A full Flask/browser interaction test could not be run in this build environment
  because Flask is not installed and package installation was unavailable.


STAGE 33 - AI-ASSISTED USERNAME SAFETY
- Registration checks usernames for reserved names, vulgarity, hateful content, extremist glorification and staff impersonation.
- If OPENAI_API_KEY is configured on the server, the username (not the registrant's full name) is sent for AI-assisted contextual screening.
- If AI is unavailable, suspicious/uncertain names are held for owner review; basic checks remain active.
- Neutral identity terms such as “gay” are not disallowed by themselves.
- Rejected names cannot register; uncertain names require owner review.
- This is username screening, not identity or age verification.


STAGE 34 — OWNER NAME REVIEW PANEL
----------------------------------
- Added a private Owner HQ → Name Review panel for usernames flagged by the Stage 33 screening system.
- Registration records usernames flagged for review or rejection in a persistent database queue.
- Owners can inspect the proposed username, screening decision, reason and method, then approve or reject it.
- Approval/rejection decisions are timestamped, attributed to the owner and written to the owner audit log.
- Rejected accounts are marked rejected and cannot sign in. Approved names can sign in only when the existing age/guardian-consent rules allow it.
- The AI remains optional: configure OPENAI_API_KEY on the server for AI review. Local screening still runs without a key; uncertain cases can be sent to the owner.
- Neutral identity terms such as “gay” are not automatically treated as inappropriate. AI flags are advisory and owner review remains available.

Stage 34 checks: Python syntax compilation passed; ZIP integrity check passed; SQLite schema extraction and execution passed. Full Flask/browser interaction testing was not run because Flask is not installed in this build environment.


STAGE 35 – OWNER ABUSE ADMINISTRATION PANEL

- Added a dedicated private Owner HQ page at /owner/abuse-panel.
- Consolidates open community-post reports, member safety/support reports and pending username flags.
- Shows report context and the reported post author, with links to hide, dismiss or delete reported posts.
- Offers an evidence/reason-required member ban action for reported post authors, using the existing protected ban workflow. Owner accounts cannot be banned through this control.
- Support reports can be marked reviewed or closed; username decisions remain in the dedicated name-review workflow.
- Displays open-queue and banned-account counts and adds a direct link from Owner HQ.
- Human owner review remains the final decision; reports and automated name flags are not treated as proof.

Testing note: Python syntax compilation and ZIP integrity were checked. Runtime/browser tests are only claimed if explicitly reported separately.


STAGE 36 — CUSTOM MEMBER PROFILES
---------------------------------
- Added an editable member profile page with avatar choices, favourite aircraft, optional country, profile background and a short bio.
- Members can choose whether their profile is public or private.
- Added a personal profile preview and edit links for signed-in General members.
- Added public member profile pages for approved, active General members whose visibility is set to public. Kids World profiles are not exposed through public profile URLs.
- Added a private Owner HQ → Member Profiles directory. The owner can open member profiles for administration, including private profiles, without access to passwords, login tokens or private AI conversations.
- Existing accounts are migrated with safe default profile visibility and avatar/background values. A profile-completion flag ensures new members are prompted to customise their profile once, then sent to the home page on later sign-ins. Existing account and project records are preserved.
- No profile-photo upload is enabled in this stage. Members are warned not to publish contact details, school, home address or daily routines.

STAGE 36 VALIDATION
-------------------
- Python syntax compilation: passed.
- Database migration and profile-visibility defaults: validated separately with SQLite.
- Profile routes, visibility checks and owner-only route decorators: source-reviewed.
- Full Flask/browser testing: not performed because Flask is not installed in the build environment.


STAGE 41: See README_STAGE41.txt for live flight offer search setup and limitations.

STAGE 42 — Premium card checkout: see README_STAGE41.txt for Paystack hosted checkout setup, adult-managed merchant requirements, security behaviour and launch limitations. Card checkout stays disabled until PAYSTACK_SECRET_KEY is configured server-side.
