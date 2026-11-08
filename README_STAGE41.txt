AIR TRAVEL STAGE 41 – LIVE FLIGHT SEARCH FOUNDATION

Added a server-side Amadeus Self-Service Flight Offers Search integration. Members can use /live-flights after signing in. The backend obtains an OAuth token server-side and queries the provider Flight Offers Search endpoint. API credentials are read only from environment variables and are never placed in browser code.

SETUP (authorised adult administrator):
1. Create/maintain an Amadeus for Developers account and enable the Flight Offers Search API.
2. Keep the client ID and secret private. Set AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET as server environment variables; never paste secrets into chat, commit them, or put them in a ZIP.
3. Leave AMADEUS_ENV=test for sandbox testing. Use production only after provider approval and review of its current terms, limits and commercial requirements.
4. Install requirements and restart the Flask server.

IMPORTANT LIMITATION:
This stage implements provider-backed flight-offer SEARCH only when credentials are configured. It does not create airline reservations, issue e-tickets, accept payment, guarantee displayed fares/seats, or provide cancellation/refund handling. Real ticketing requires a provider/airline ticketing arrangement, authorised adult-managed business and payment accounts, and a separately implemented order/issuance flow. Do not collect passport or card details in this search form. Sandbox results are not purchasable tickets.

Airport codes accepted: three-letter IATA codes (LOS, ABV, PHC, etc.).

STAGE 42 — PREMIUM CARD CHECKOUT FOUNDATION
-------------------------------------------
- Added Paystack hosted-checkout initialization for Weekly, Monthly, Yearly, PRO and ROYAL Premium plans.
- Prices: ₦500 / ₦1,000 / ₦5,000 / ₦50,000 / ₦100,000 respectively. Durations: 7 days / 30 days / 365 days / 10 years / 20 years.
- Card details are entered on Paystack-hosted checkout; AIR TRAVEL does not request or store card numbers or CVV.
- The server stores a pending payment reference and activates Premium only after server-to-server Paystack verification confirms success, exact amount, NGN currency and payer email. Repeated callback visits do not activate the same payment twice.
- An adult payer email and explicit authorised-adult approval are required in the checkout form. The Paystack merchant account and settlement bank account must belong to and be managed by an authorised adult.

ADULT ADMIN SETUP (SERVER ONLY):
1. An authorised adult creates and verifies the AIR TRAVEL merchant account with Paystack and configures its settlement bank account directly with Paystack.
2. Test with Paystack test credentials first. Set PAYSTACK_SECRET_KEY in the hosting provider's server-side secret/environment settings. Never put it in app.py, HTML/JavaScript, a public repository, the ZIP, or chat.
3. Configure the deployed HTTPS site and test successful, declined, abandoned and repeated-callback scenarios before considering live mode. Keep production credentials private and only use them after Paystack approval and applicable account checks.
4. Install requirements and restart the Flask server. Without PAYSTACK_SECRET_KEY, card buttons remain disabled and no payment can be taken.

IMPORTANT LIMITATIONS:
- This is a hosted-checkout integration foundation, not proof that a merchant account, bank settlement, live payment, refund workflow, or production deployment is configured. No live payment was run during this build because no merchant credentials are available.
- Payment status is checked against Paystack from the server on the return page. Members should retain the provider receipt and contact the authorised merchant for payment/refund support. A production launch should additionally configure and test Paystack signed webhooks, reconciliation, refund handling, and monitoring.
- A parent/guardian or other authorised adult must make and manage payments for younger users. AIR TRAVEL does not store card details.
