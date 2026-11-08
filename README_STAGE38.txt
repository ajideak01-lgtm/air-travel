AIR TRAVEL — STAGE 38: PROFILE EDIT FIX

This update fixes a runtime error in the member profile display route. The profile renderer now receives safe defaults for viewer/friendship state, so opening /profile no longer references an undefined `viewer` variable. The existing /profile/customise GET/POST flow remains in place and continues to save avatar, favourite aircraft, country, background, bio and visibility.

How to use:
1. Extract this ZIP.
2. Install dependencies from requirements.txt in your Python environment.
3. Run START_AIR_TRAVEL.bat on Windows.
4. Sign in as a guest and open My Profile → Edit my profile.
5. Change a field and press Save profile; then reopen the profile to verify the changes.

This package was syntax-checked and ZIP integrity-checked. Full browser/database integration testing was not run in this environment because Flask is not installed here. Keep a backup of your existing database before replacing project files.
