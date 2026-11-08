import os, sqlite3, secrets, functools, json, urllib.request, urllib.error, time, re, urllib.parse
from datetime import datetime, date
from datetime import timezone, timedelta
from flask import Flask, request, redirect, url_for, session, flash, render_template_string, g, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash

from urllib.parse import urlencode

def amadeus_configured():
 return bool(os.environ.get('AMADEUS_CLIENT_ID') and os.environ.get('AMADEUS_CLIENT_SECRET'))

def amadeus_api_request(path, params=None, method='GET', data=None):
 base='https://test.api.amadeus.com' if os.environ.get('AMADEUS_ENV','test').lower()!='production' else 'https://api.amadeus.com'
 token_url=base+'/v1/security/oauth2/token'
 token_body=urlencode({'grant_type':'client_credentials','client_id':os.environ['AMADEUS_CLIENT_ID'],'client_secret':os.environ['AMADEUS_CLIENT_SECRET']}).encode()
 req=urllib.request.Request(token_url,data=token_body,headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
 with urllib.request.urlopen(req,timeout=15) as r: token=json.loads(r.read().decode()).get('access_token')
 if not token: raise RuntimeError('Flight provider did not return an access token.')
 url=base+path+(('?'+urlencode(params)) if params else '')
 body=json.dumps(data).encode() if data is not None else None
 req=urllib.request.Request(url,data=body,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req,timeout=20) as r: return json.loads(r.read().decode())


ROOT=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('DATABASE_PATH', os.path.join(ROOT,'airtravel.db'))
app=Flask(__name__)
app.jinja_env.filters['fromjson'] = lambda value: json.loads(value)
app.secret_key=os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE','0') == '1', PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
_LOGIN_ATTEMPTS = {}
_LOGIN_WINDOW = 900
_LOGIN_MAX = 5

SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', exp INTEGER NOT NULL DEFAULT 1000, mode TEXT NOT NULL DEFAULT 'general', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, moderation_status TEXT NOT NULL DEFAULT 'visible', FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS post_reports(id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL, reporter_id INTEGER NOT NULL, reason TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, reviewed_at TEXT, UNIQUE(post_id,reporter_id), FOREIGN KEY(post_id) REFERENCES posts(id), FOREIGN KEY(reporter_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, title TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL, event_date TEXT, category TEXT NOT NULL DEFAULT 'Community', event_status TEXT NOT NULL DEFAULT 'published');
CREATE TABLE IF NOT EXISTS announcements(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL, is_published INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(owner_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, amount INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_items(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, item TEXT NOT NULL, cost INTEGER NOT NULL, purchased_at TEXT NOT NULL, UNIQUE(user_id,item));
CREATE TABLE IF NOT EXISTS scheduled_rewards(event_key TEXT PRIMARY KEY, awarded_at TEXT NOT NULL, recipient_count INTEGER NOT NULL, amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS premium_trials(user_id INTEGER PRIMARY KEY, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS daily_claims(user_id INTEGER NOT NULL, claim_date TEXT NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY(user_id,claim_date));
CREATE TABLE IF NOT EXISTS premium_memberships(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, plan TEXT NOT NULL, starts_at TEXT NOT NULL, expires_at TEXT NOT NULL, payment_method TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS premium_card_payments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, plan_key TEXT NOT NULL, reference TEXT NOT NULL UNIQUE, amount_kobo INTEGER NOT NULL, payer_email TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','paid','failed')), created_at TEXT NOT NULL, paid_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS passport_stamps(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, destination TEXT NOT NULL, country TEXT NOT NULL, stamped_at TEXT NOT NULL, UNIQUE(user_id,destination), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS trip_plans(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL, origin TEXT NOT NULL, destination TEXT NOT NULL, departure_date TEXT NOT NULL, return_date TEXT, budget REAL, notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS academy_progress(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, lesson_key TEXT NOT NULL, completed_at TEXT NOT NULL, UNIQUE(user_id,lesson_key), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS academy_certificates(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE, certificate_code TEXT NOT NULL UNIQUE, issued_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS airport_state(user_id INTEGER PRIMARY KEY, terminal INTEGER NOT NULL DEFAULT 0, gates INTEGER NOT NULL DEFAULT 0, runway INTEGER NOT NULL DEFAULT 0, last_income_date TEXT, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS wheel_claims(user_id INTEGER NOT NULL, claim_date TEXT NOT NULL, amount INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,claim_date), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS owner_audit_logs(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, action TEXT NOT NULL, target_user_id INTEGER, details TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_activity(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS support_reports(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, category TEXT NOT NULL, subject TEXT NOT NULL, details TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(reviewed_by) REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_account_activity_user ON account_activity(user_id,id DESC);
CREATE INDEX IF NOT EXISTS idx_support_reports_status ON support_reports(status,id DESC);
CREATE TABLE IF NOT EXISTS account_moderation_history(id INTEGER PRIMARY KEY, target_user_id INTEGER NOT NULL, owner_id INTEGER NOT NULL, action TEXT NOT NULL CHECK(action IN ('banned','unbanned')), reason TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(target_user_id) REFERENCES users(id), FOREIGN KEY(owner_id) REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_account_moderation_target ON account_moderation_history(target_user_id,id DESC);
CREATE TABLE IF NOT EXISTS username_review_queue(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE, username TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('review','reject')), reason TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')), created_at TEXT NOT NULL, reviewed_at TEXT, reviewed_by INTEGER, FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(reviewed_by) REFERENCES users(id));
CREATE INDEX IF NOT EXISTS idx_username_review_status ON username_review_queue(status,id DESC);
CREATE TABLE IF NOT EXISTS owner_tribute_settings(id INTEGER PRIMARY KEY CHECK(id=1), dedication TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by INTEGER, FOREIGN KEY(updated_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS owner_tribute_milestones(id INTEGER PRIMARY KEY, stage_label TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS career_progress(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, career_key TEXT NOT NULL, challenge_key TEXT NOT NULL, completed_at TEXT NOT NULL, UNIQUE(user_id,career_key,challenge_key), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS career_applications(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, role_key TEXT NOT NULL, motivation TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'submitted', created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS career_challenges(id INTEGER PRIMARY KEY, career_key TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS career_assessments(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, score INTEGER NOT NULL, total INTEGER NOT NULL, passed INTEGER NOT NULL, completed_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS aviation_mission_progress(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, mission_key TEXT NOT NULL, completed_at TEXT NOT NULL, UNIQUE(user_id,mission_key), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS kids_exam_attempts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, score INTEGER NOT NULL, total INTEGER NOT NULL, passed INTEGER NOT NULL, completed_at TEXT NOT NULL, review_json TEXT NOT NULL DEFAULT '[]', FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS kids_stories(id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL, emoji TEXT NOT NULL DEFAULT '📘', content_json TEXT NOT NULL, is_published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kids_exam_questions(id INTEGER PRIMARY KEY, question TEXT NOT NULL, options_json TEXT NOT NULL, correct_index INTEGER NOT NULL CHECK(correct_index BETWEEN 0 AND 2), is_published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, explanation TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS kids_activity_progress(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, activity_type TEXT NOT NULL CHECK(activity_type IN ('story','sky_stars','perfect_timing')), item_key TEXT NOT NULL, completed_count INTEGER NOT NULL DEFAULT 0 CHECK(completed_count>=0), best_score INTEGER NOT NULL DEFAULT 0 CHECK(best_score>=0), updated_at TEXT NOT NULL, UNIQUE(user_id,activity_type,item_key), FOREIGN KEY(user_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS kids_story_favourites(user_id INTEGER NOT NULL, story_slug TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,story_slug), FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(story_slug) REFERENCES kids_stories(slug));
CREATE TABLE IF NOT EXISTS kids_extra_game_scores(user_id INTEGER NOT NULL, game_key TEXT NOT NULL CHECK(game_key IN ('memory_match','airport_sequence','word_search')), best_score INTEGER NOT NULL DEFAULT 0 CHECK(best_score BETWEEN 0 AND 100), plays INTEGER NOT NULL DEFAULT 0 CHECK(plays>=0), updated_at TEXT NOT NULL, PRIMARY KEY(user_id,game_key), FOREIGN KEY(user_id) REFERENCES users(id));
-- Stage 29: virtual airline empire simulation (no real airline operations).
CREATE TABLE IF NOT EXISTS airlines(
 id INTEGER PRIMARY KEY,
 owner_user_id INTEGER NOT NULL UNIQUE,
 name TEXT NOT NULL,
 code TEXT NOT NULL UNIQUE,
 brand_emoji TEXT NOT NULL DEFAULT '✈️',
 brand_color TEXT NOT NULL DEFAULT 'blue',
 reputation INTEGER NOT NULL DEFAULT 0 CHECK(reputation>=0),
 completed_flights INTEGER NOT NULL DEFAULT 0 CHECK(completed_flights>=0),
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
 created_at TEXT NOT NULL,
 FOREIGN KEY(owner_user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS airline_fleet(
 id INTEGER PRIMARY KEY,
 airline_id INTEGER NOT NULL,
 aircraft_key TEXT NOT NULL,
 aircraft_name TEXT NOT NULL,
 capacity INTEGER NOT NULL CHECK(capacity>0),
 purchase_cost INTEGER NOT NULL CHECK(purchase_cost>=0),
 created_at TEXT NOT NULL,
 FOREIGN KEY(airline_id) REFERENCES airlines(id)
);
CREATE TABLE IF NOT EXISTS airline_routes(
 id INTEGER PRIMARY KEY,
 airline_id INTEGER NOT NULL,
 origin TEXT NOT NULL,
 destination TEXT NOT NULL,
 route_fee INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 UNIQUE(airline_id,origin,destination),
 FOREIGN KEY(airline_id) REFERENCES airlines(id)
);
CREATE TABLE IF NOT EXISTS airline_staff(
 id INTEGER PRIMARY KEY,
 airline_id INTEGER NOT NULL,
 role_key TEXT NOT NULL,
 role_label TEXT NOT NULL,
 teams INTEGER NOT NULL DEFAULT 0 CHECK(teams>=0),
 updated_at TEXT NOT NULL,
 UNIQUE(airline_id,role_key),
 FOREIGN KEY(airline_id) REFERENCES airlines(id)
);
CREATE TABLE IF NOT EXISTS airline_flights(
 id INTEGER PRIMARY KEY,
 airline_id INTEGER NOT NULL,
 route_id INTEGER NOT NULL,
 aircraft_id INTEGER NOT NULL,
 scheduled_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','completed','cancelled')),
 reward_exp INTEGER NOT NULL DEFAULT 0 CHECK(reward_exp>=0),
 created_at TEXT NOT NULL,
 completed_at TEXT,
 FOREIGN KEY(airline_id) REFERENCES airlines(id),
 FOREIGN KEY(route_id) REFERENCES airline_routes(id),
 FOREIGN KEY(aircraft_id) REFERENCES airline_fleet(id)
);
CREATE TABLE IF NOT EXISTS airline_ledger(
 id INTEGER PRIMARY KEY,
 airline_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL,
 amount INTEGER NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(airline_id) REFERENCES airlines(id),
 FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS airline_competition(
 id INTEGER PRIMARY KEY CHECK(id=1),
 title TEXT NOT NULL,
 description TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 updated_by INTEGER,
 FOREIGN KEY(updated_by) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_airline_flights_owner_status ON airline_flights(airline_id,status,scheduled_at);
CREATE INDEX IF NOT EXISTS idx_airline_ledger_airline ON airline_ledger(airline_id,id DESC);
-- Stage 37: member-to-member friendship requests. No direct messaging is enabled.
CREATE TABLE IF NOT EXISTS friend_requests(
 id INTEGER PRIMARY KEY, sender_id INTEGER NOT NULL, recipient_id INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','declined','cancelled')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(sender_id,recipient_id), CHECK(sender_id<>recipient_id),
 FOREIGN KEY(sender_id) REFERENCES users(id), FOREIGN KEY(recipient_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_friend_requests_recipient ON friend_requests(recipient_id,status,id DESC);
CREATE TABLE IF NOT EXISTS friendships(
 user_low INTEGER NOT NULL, user_high INTEGER NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(user_low,user_high), CHECK(user_low<user_high),
 FOREIGN KEY(user_low) REFERENCES users(id), FOREIGN KEY(user_high) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS member_blocks(
 blocker_id INTEGER NOT NULL, blocked_id INTEGER NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(blocker_id,blocked_id), CHECK(blocker_id<>blocked_id),
 FOREIGN KEY(blocker_id) REFERENCES users(id), FOREIGN KEY(blocked_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS flight_booking_requests(
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, origin TEXT NOT NULL,
 destination TEXT NOT NULL, departure_date TEXT NOT NULL, return_date TEXT,
 passengers INTEGER NOT NULL CHECK(passengers BETWEEN 1 AND 9),
 airline_preference TEXT NOT NULL, cabin_class TEXT NOT NULL,
 contact_email TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','contacted','closed')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_booking_requests_status ON flight_booking_requests(status,id DESC);
CREATE TABLE IF NOT EXISTS member_ai_messages(
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','assistant')),
 content TEXT NOT NULL CHECK(length(content)<=4000), created_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_member_ai_history ON member_ai_messages(user_id,id DESC);

'''
def db():
 if 'db' not in g:
  g.db=sqlite3.connect(DB); g.db.row_factory=sqlite3.Row
 return g.db
@app.teardown_appcontext
def close_db(exc):
 c=g.pop('db',None)
 if c: c.close()
def init_db():
 with app.app_context():
  c=db(); c.executescript(SCHEMA)
  c.execute('INSERT OR IGNORE INTO airline_competition(id,title,description,updated_at,updated_by) VALUES(1,?,?,?,NULL)', ('Founders Flight League','Build your virtual airline, open destinations, recruit your virtual team and complete scheduled game flights. Rankings use completed virtual flights and reputation.','2026-11-07T00:00:00'))
  # Stage 28: add child-friendly answer feedback while preserving existing records.
  exam_attempt_cols={r['name'] for r in c.execute('PRAGMA table_info(kids_exam_attempts)').fetchall()}
  if 'review_json' not in exam_attempt_cols:
   c.execute("ALTER TABLE kids_exam_attempts ADD COLUMN review_json TEXT NOT NULL DEFAULT '[]'")
  exam_question_cols={r['name'] for r in c.execute('PRAGMA table_info(kids_exam_questions)').fetchall()}
  if 'explanation' not in exam_question_cols:
   c.execute("ALTER TABLE kids_exam_questions ADD COLUMN explanation TEXT NOT NULL DEFAULT ''")
  c.execute('INSERT OR IGNORE INTO owner_tribute_settings(id,dedication,updated_at,updated_by) VALUES(1,?,?,NULL)', ('AIR TRAVEL began in 2026 with a simple ambition: bring aviation discovery, travel planning, learning, games and community together in one place. Every development stage is another step in that journey.', datetime.utcnow().isoformat()))
  if c.execute('SELECT COUNT(*) FROM owner_tribute_milestones').fetchone()[0] == 0:
   starter_milestones = [
    ('2026 · THE BEGINNING','The AIR TRAVEL idea','The project takes shape around aviation discovery, travel, creativity and community.'),
    ('BUILDING THE EXPERIENCE','Travel & exploration','Trip planning, destination exploration and digital passport experiences become part of the project.'),
    ('LEARNING & DISCOVERY','Flight Academy','Lessons, certificates and aviation career exploration expand the learning experience.'),
    ('COMMUNITY & PLAY','Virtual Aviation World','Interactive missions, games and the Announcements Centre add more ways to participate.')
   ]
   c.executemany('INSERT INTO owner_tribute_milestones(stage_label,title,description,created_at) VALUES(?,?,?,?)', [(label,title,description,datetime.utcnow().isoformat()) for label,title,description in starter_milestones])
  # Database-level guard: member EXP balances can never become negative.
  c.execute("CREATE TRIGGER IF NOT EXISTS prevent_negative_member_exp BEFORE UPDATE OF exp ON users WHEN NEW.role!='owner' AND NEW.exp<0 BEGIN SELECT RAISE(ABORT, 'Insufficient EXP balance'); END")
  # Backward-compatible Stage 2 account/profile fields.
  cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
  for name, decl in [('username','TEXT'),('age','INTEGER'),('approval_status',"TEXT NOT NULL DEFAULT 'approved'"),('profile_picture','TEXT'),('avatar','TEXT'),('favourite_aircraft','TEXT'),('profile_background','TEXT'),('country','TEXT'),('bio','TEXT'),('profile_visibility',"TEXT NOT NULL DEFAULT 'public'"),('profile_completed',"INTEGER NOT NULL DEFAULT 0"),('account_status',"TEXT NOT NULL DEFAULT 'active'")]:
   if name not in cols: c.execute(f'ALTER TABLE users ADD COLUMN {name} {decl}')
  c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL AND username!=''")
  c.execute("UPDATE users SET profile_visibility='public' WHERE profile_visibility IS NULL OR profile_visibility NOT IN ('public','private')")
  c.execute("UPDATE users SET avatar='✈️' WHERE avatar IS NULL OR avatar=''")
  c.execute("UPDATE users SET profile_background='navy' WHERE profile_background IS NULL OR profile_background=''")
  c.execute("UPDATE users SET avatar='✈️' WHERE avatar IS NULL OR avatar=''")
  c.execute("UPDATE users SET profile_background='navy' WHERE profile_background IS NULL OR profile_background=''")
  # Stage 19: migrate older event records without deleting or rewriting them.
  event_cols={r['name'] for r in c.execute('PRAGMA table_info(events)').fetchall()}
  for name, decl in [('event_date','TEXT'),('category',"TEXT NOT NULL DEFAULT 'Community'"),('event_status',"TEXT NOT NULL DEFAULT 'published'")]:
   if name not in event_cols: c.execute(f'ALTER TABLE events ADD COLUMN {name} {decl}')
  c.execute("UPDATE events SET category='Community' WHERE category IS NULL OR category=''")
  c.execute("UPDATE events SET event_status='published' WHERE event_status IS NULL OR event_status=''")
  # Stage 21: seed the existing original Kids World content into editable tables.
  # Constants are defined below the route section but before init_db() is called at startup.
  if c.execute('SELECT COUNT(*) FROM kids_stories').fetchone()[0] == 0:
   for story in KIDS_STORIES:
    slug,title,emoji,paragraphs=story
    c.execute('INSERT OR IGNORE INTO kids_stories(slug,title,emoji,content_json,is_published,created_at,updated_at) VALUES(?,?,?,?,1,?,?)',
      (slug,title,emoji,json.dumps(paragraphs,ensure_ascii=False),datetime.utcnow().isoformat(),datetime.utcnow().isoformat()))
  if c.execute('SELECT COUNT(*) FROM kids_exam_questions').fetchone()[0] == 0:
   for question,options,correct in KIDS_QUESTIONS:
    c.execute('INSERT INTO kids_exam_questions(question,options_json,correct_index,is_published,created_at,updated_at) VALUES(?,?,?,1,?,?)',
      (question,json.dumps(options,ensure_ascii=False),correct,datetime.utcnow().isoformat(),datetime.utcnow().isoformat()))
  for question, explanation in KIDS_QUESTION_EXPLANATIONS.items():
   c.execute("UPDATE kids_exam_questions SET explanation=? WHERE question=? AND (explanation IS NULL OR TRIM(explanation)='')",(explanation,question))
  c.execute("UPDATE kids_exam_questions SET explanation='This is the correct answer. Read the question again and ask a trusted grown-up if you would like more help.' WHERE explanation IS NULL OR TRIM(explanation)=''")
  post_cols={r['name'] for r in c.execute('PRAGMA table_info(posts)').fetchall()}
  if 'moderation_status' not in post_cols: c.execute("ALTER TABLE posts ADD COLUMN moderation_status TEXT NOT NULL DEFAULT 'visible'")
  owner=os.environ.get('OWNER_EMAIL','owner@airtravel.local').strip().lower()
  pw=os.environ.get('OWNER_PASSWORD','AirTravelOwner2026!')
  row=c.execute('SELECT id FROM users WHERE email=?',(owner,)).fetchone()
  if not row:
   c.execute('INSERT INTO users(email,name,password_hash,role,exp,mode,created_at) VALUES(?,?,?,?,?,?,?)',(owner,'AKINOLA AJIDE OWNER',generate_password_hash(pw),'owner',0,'general',datetime.utcnow().isoformat()))
  c.commit()
def award_birthday_bonus_if_due():
 # Runs automatically on app requests on November 30, Nigeria time.
 # The event key prevents repeat awards if many people visit the app that day.
 today = datetime.now(timezone(timedelta(hours=1))).date()
 if today < date(2026, 11, 30):
  return
 c = db()
 event_key = 'akinola-birthday-2026-11-30'
 try:
  c.execute('BEGIN IMMEDIATE')
  if c.execute('SELECT 1 FROM scheduled_rewards WHERE event_key=?', (event_key,)).fetchone():
   c.rollback(); return
  recipients = c.execute("SELECT id FROM users WHERE role='member'").fetchall()
  now = datetime.now(timezone(timedelta(hours=1))).isoformat()
  for member in recipients:
   c.execute('UPDATE users SET exp=exp+1000000 WHERE id=?', (member['id'],))
   c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',
             (member['id'], 1000000, 'Akinola Ajide birthday celebration bonus', now))
  c.execute('INSERT INTO scheduled_rewards(event_key,awarded_at,recipient_count,amount) VALUES(?,?,?,?)',
            (event_key, now, len(recipients), 1000000))
  c.commit()
 except Exception:
  c.rollback()
  app.logger.exception('Birthday EXP distribution failed')

@app.before_request
def run_scheduled_rewards():
 award_birthday_bonus_if_due()

@app.before_request
def protect_state_changing_requests():
 # Every browser session receives a random CSRF token. All POST routes,
 # including JSON endpoints, must present the same token.
 token = session.get('csrf_token')
 if not token:
  token = secrets.token_urlsafe(32)
  session['csrf_token'] = token
 if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
  supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
  if not supplied or not secrets.compare_digest(str(supplied), str(token)):
   if request.is_json or request.path.startswith('/ai/'):
    return {'error': 'Security check failed. Refresh the page and try again.'}, 400
   flash('Your security token expired. Please try again.', 'error')
   return redirect(request.referrer or url_for('home'))

@app.after_request
def add_security_headers(response):
 response.headers.setdefault('X-Content-Type-Options', 'nosniff')
 response.headers.setdefault('X-Frame-Options', 'DENY')
 response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
 response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
 response.headers.setdefault('Cache-Control', 'no-store')
 if response.mimetype == 'text/html':
  token = session.get('csrf_token', '')
  if token:
   response.set_data(re.sub(r'(<form\b[^>]*method=[\"\']post[\"\'][^>]*>)', lambda m: m.group(1) + '<input type=\"hidden\" name=\"csrf_token\" value=\"' + token + '\">', response.get_data(as_text=True), flags=re.I))
 return response

def audit_owner_action(action, target_user_id=None, details=''):
 owner=current_user()
 if owner and owner['role']=='owner':
  db().execute('INSERT INTO owner_audit_logs(owner_id,action,target_user_id,details,created_at) VALUES(?,?,?,?,?)',
   (owner['id'],action,target_user_id,(details or '')[:500],datetime.utcnow().isoformat()))

def record_account_activity(user_id, event, details=''):
 db().execute('INSERT INTO account_activity(user_id,event,details,created_at) VALUES(?,?,?,?)',(user_id,event,(details or '')[:300],datetime.utcnow().isoformat()))

def current_user():
 if 'uid' not in session: return None
 user=db().execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone()
 if user and user['role']!='owner' and user['account_status'] in ('suspended','banned'):
  session.pop('uid',None)
  return None
 return user
def login_required(fn):
 @functools.wraps(fn)
 def wrap(*a,**kw):
  if not current_user(): flash('Please sign in first.','error'); return redirect(url_for('login'))
  return fn(*a,**kw)
 return wrap
def owner_required(fn):
 @functools.wraps(fn)
 def wrap(*a,**kw):
  u=current_user()
  if not u or u['role']!='owner': flash('Owner access is required.','error'); return redirect(url_for('owner_login'))
  return fn(*a,**kw)
 return wrap

def kids_required(fn):
 @functools.wraps(fn)
 def wrap(*a,**kw):
  u=current_user()
  if not u:
   flash('Please sign in to enter Kids World.','error')
   return redirect(url_for('login'))
  if u['role']!='member' or u['mode']!='kids':
   flash('This page is only available in Kids World.','error')
   return redirect(url_for('home'))
  return fn(*a,**kw)
 return wrap

KIDS_ALLOWED_ENDPOINTS={'home','kids_storybooks','kids_storybook','kids_story_favourite','kids_exam','cinema','games','kids_save_progress','kids_game_score','logout','static','undercover_return'}
@app.before_request
def restrict_kids_mode():
 u=current_user()
 if u and u['role']=='member' and u['mode']=='kids' and request.endpoint not in KIDS_ALLOWED_ENDPOINTS:
  flash('Kids World has four areas: Story Books, Movie Night, Games and Exam.','error')
  return redirect(url_for('home'))
BASE='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#06152d"><title>{{title}} · AIR TRAVEL</title><style>
:root{--navy:#06152d;--panel:#0b2345;--blue:#0878ff;--cyan:#22c8ff;--paper:#061329;--text:#f4f8ff}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:radial-gradient(circle at 50% 0,#123b70 0,#061329 48%,#030b19 100%);color:var(--text)}header{background:#041126ed;border-bottom:1px solid #0878ff;padding:14px 4%;display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;position:sticky;top:0;z-index:5}header a{color:#eaf6ff;text-decoration:none;margin:5px 8px;font-weight:bold}.brand{font-size:21px;letter-spacing:.7px;display:flex;align-items:center;gap:10px}.mark{width:48px;height:38px;display:inline-grid;place-items:center;font-weight:900;font-size:36px;font-style:italic;color:#27c8ff;text-shadow:0 0 12px #078bff;position:relative}.mark:after{content:'✈';font-size:17px;position:absolute;right:-3px;top:-2px;color:white;transform:rotate(-12deg)}main{max-width:1320px;margin:24px auto;padding:0 18px}.hero{background:linear-gradient(115deg,#061a3bdf,#0756a6c9),url('/static/media/ad_poster.jpg') center/cover;color:white;border:1px solid #159bff;border-radius:22px;padding:clamp(28px,5vw,58px);box-shadow:0 0 28px #0878ff35}.hero h1{font-size:clamp(30px,5vw,58px);margin:0 0 12px;line-height:1.03}.hero h1 span{color:#21c8ff}.hero p{font-size:17px;max-width:720px;line-height:1.6}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin:20px 0}.card{background:linear-gradient(145deg,#0c2344,#07172f);border:1px solid #145eaa;border-radius:16px;padding:20px;box-shadow:0 8px 24px #0005}.card h3{margin-top:0;color:#69d8ff}.btn,button{display:inline-block;border:1px solid #38caff;border-radius:10px;padding:11px 16px;background:linear-gradient(100deg,#0878ff,#00a9ed);color:white;text-decoration:none;font-weight:bold;cursor:pointer}.btn.alt{background:#071a35;color:#fff}input,textarea,select{width:100%;padding:12px;border:1px solid #27618f;background:#071a33;color:#fff;border-radius:9px;margin:6px 0 14px;font:inherit}input[type=file]{background:#0b2345}textarea{min-height:90px}.muted{color:#a8c0da}.notice{padding:12px;border-radius:10px;background:#123e63;margin:10px 0;border:1px solid #1b83c9}.error{background:#54232d}.list{padding-left:20px;line-height:1.8}footer{text-align:center;padding:30px;color:#9db6d2}.tag{display:inline-block;background:#063a66;color:#79dcff;padding:5px 9px;border-radius:20px;font-size:12px;font-weight:bold}.balance{font-size:28px;font-weight:bold;color:#36c9ff}a{color:#68d8ff}form.inline{display:inline}.inline button{padding:7px 10px}.feature-icon{font-size:30px}.tile{min-height:150px}.tile h3{font-size:19px}.stat{color:#ffcf52;font-weight:bold}.video-box{background:#020813;border:1px solid #1688d9;border-radius:16px;padding:12px}.video-box video{width:100%;max-height:520px;background:#000;border-radius:10px}.ad-overlay{position:fixed;inset:0;background:#020817f5;z-index:20;display:grid;place-items:center;padding:18px}.ad-card{width:min(760px,96vw);background:#071b38;border:1px solid #20baff;border-radius:20px;overflow:hidden;box-shadow:0 0 35px #078bff80;text-align:center}.ad-card img{width:100%;max-height:300px;object-fit:cover;display:block}.ad-copy{padding:18px}.ad-count{font-size:14px;color:#9edfff}.ad-hidden{display:none!important}@media(min-width:651px){header nav{display:flex;flex-direction:row;align-items:center;flex-wrap:nowrap;overflow-x:auto;white-space:nowrap;max-width:calc(100vw - 260px);scrollbar-width:thin}header nav a{flex:0 0 auto}}@media(max-width:650px){header{position:static;align-items:flex-start;flex-direction:column}header nav{display:flex;flex-direction:column;align-items:stretch;width:100%;gap:4px}header nav a{display:block;padding:9px 12px;margin:0;border:1px solid #17436a;border-radius:8px;background:#071a33}.brand{font-size:18px}}

/* ATW luxury aviation home refresh */
.home-shell{display:grid;gap:22px}.home-hero{position:relative;isolation:isolate;overflow:hidden;min-height:410px;border-radius:28px;border:1px solid #397fc0;background:linear-gradient(90deg,rgba(20,5,35,.76) 0%,rgba(20,5,35,.48) 48%,rgba(20,5,35,.18) 100%),url('/static/media/air_travel_official_logo.png') center/contain no-repeat,linear-gradient(135deg,#54205f,#df6ca9);box-shadow:0 24px 70px #0008;padding:clamp(26px,5vw,58px);display:flex;align-items:center}.home-hero:after{content:'✈';position:absolute;z-index:-1;right:5%;top:12%;font-size:clamp(130px,23vw,280px);color:#d9f5ff22;transform:rotate(-12deg);text-shadow:0 0 45px #22aaff55}.hero-copy{max-width:680px}.eyebrow{display:inline-flex;align-items:center;gap:9px;padding:8px 13px;border:1px solid #69cfff66;border-radius:30px;background:#06264bbd;color:#a9eaff;letter-spacing:2px;font-size:11px;font-weight:800}.home-hero h1{font-size:clamp(38px,6.2vw,76px);letter-spacing:-2px;line-height:.98;margin:22px 0 16px}.home-hero h1 span{display:block;background:linear-gradient(90deg,#fff,#5bd5ff 65%,#d9f8ff);-webkit-background-clip:text;background-clip:text;color:transparent}.home-hero p{max-width:590px;color:#d2e6f8;font-size:17px;line-height:1.7}.hero-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:24px}.hero-actions .btn{padding:14px 20px;border-radius:12px}.hero-note{margin-top:24px;color:#a9c5df;font-size:12px;letter-spacing:.4px}.home-section-head{display:flex;align-items:end;justify-content:space-between;gap:14px;flex-wrap:wrap}.home-section-head h2{margin:0;color:#f3f9ff;font-size:clamp(22px,3vw,30px)}.home-section-head p{margin:6px 0 0;color:#9bb8d5}.home-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.home-stat{padding:16px 18px;border:1px solid #1b5283;border-radius:16px;background:linear-gradient(140deg,#102d50,#07172d);box-shadow:0 8px 22px #0003}.home-stat b{display:block;color:#eaf8ff;font-size:19px;margin-bottom:4px}.home-stat span{font-size:11px;color:#91b5d5;letter-spacing:1px;text-transform:uppercase}.home-modules{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.home-module{position:relative;overflow:hidden;min-height:174px;padding:20px;border:1px solid #1c5688;border-radius:18px;background:linear-gradient(145deg,#102c4c,#07172d);text-decoration:none;color:#f4f9ff;transition:transform .18s,border-color .18s,box-shadow .18s}.home-module:hover{transform:translateY(-4px);border-color:#49c9ff;box-shadow:0 15px 35px #008dff26}.home-module:after{content:attr(data-symbol);position:absolute;right:14px;bottom:-20px;font-size:92px;opacity:.10;pointer-events:none}.module-icon{font-size:27px}.home-module h3{margin:12px 0 7px;color:#82ddff;font-size:18px}.home-module p{margin:0;color:#a9c2dc;line-height:1.5;font-size:13px;max-width:280px}.module-link{display:inline-block;margin-top:14px;color:#65d5ff;font-size:12px;font-weight:800}.home-member{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap;padding:20px 22px;border:1px solid #986f2c;border-radius:18px;background:linear-gradient(105deg,#30250f,#102541 75%)}.home-member h3{margin:0 0 5px;color:#ffe0a0}.home-member p{margin:0;color:#c6d5e4}.home-exp{font-size:clamp(23px,3vw,34px);font-weight:900;color:#ffda78}.home-member .btn{white-space:nowrap}.home-bottom{display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap;padding:18px 20px;border-radius:16px;background:#07182c;border:1px solid #173e63;color:#a9c3dd}.home-bottom strong{color:#e8f6ff}.home-bottom a{font-weight:700;text-decoration:none}
@media(max-width:850px){.home-stats{grid-template-columns:repeat(2,minmax(0,1fr))}.home-modules{grid-template-columns:repeat(2,minmax(0,1fr))}.home-hero{min-height:370px}}
@media(max-width:560px){.home-modules{grid-template-columns:1fr}.home-hero{padding:25px 21px;min-height:420px}.home-hero p{font-size:15px}.home-stats{gap:9px}.home-stat{padding:13px}.home-stat b{font-size:16px}}

/* Stage 18: private Owner HQ metrics dashboard */
.owner-metric-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:16px;margin:18px 0}
.owner-metric-group{background:linear-gradient(145deg,#0c2344,#07172f);border:1px solid #1c629c;border-radius:16px;padding:18px;box-shadow:0 8px 24px #0004}
.owner-metric-group h2{font-size:18px;color:#75dcff;margin:0 0 12px}
.owner-metric-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:11px 0;border-top:1px solid #214263}
.owner-metric-row span{color:#bad0e5;font-size:14px}
.owner-metric-row b{color:#ffdc85;font-size:20px;white-space:nowrap}
.owner-activity{border-top:1px solid #214263;padding:12px 0;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.owner-activity b{color:#b9eaff}
.owner-activity time{color:#9bb5cf;font-size:12px}
.owner-overview-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
@media(max-width:650px){.owner-metric-groups{grid-template-columns:1fr}.owner-metric-row b{font-size:18px}}

.kids-world{color:#29365d;background:linear-gradient(145deg,#fff8df,#effaff 55%,#fff0f7);border:2px solid #fff;border-radius:26px;padding:clamp(16px,4vw,34px);box-shadow:0 14px 40px #273b6520}
.kids-hero{border-radius:23px;padding:clamp(22px,5vw,44px);background:linear-gradient(120deg,#7251c4,#e875ad 60%,#ffbd72);color:#fff;box-shadow:0 12px 28px #9c5eb044}
.kids-hero h1{font-size:clamp(30px,6vw,56px);margin:12px 0;line-height:1.04}.kids-hero p{font-size:17px;line-height:1.6;max-width:650px;color:#fff}
.kids-tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:22px 0}.kids-tile{min-height:180px;border-radius:22px;padding:20px;color:#29365d;text-decoration:none;border:2px solid #fff;box-shadow:0 10px 24px #34446b18;display:flex;flex-direction:column;justify-content:space-between}.kids-tile:nth-child(1){background:linear-gradient(145deg,#fff0a9,#ffda78)}.kids-tile:nth-child(2){background:linear-gradient(145deg,#d9f4ff,#9fddff)}.kids-tile:nth-child(3){background:linear-gradient(145deg,#dff8d7,#a9e9b5)}.kids-tile:nth-child(4){background:linear-gradient(145deg,#ffe0ef,#f5b7da)}.kids-tile .big{font-size:46px}.kids-tile h2{margin:9px 0 5px;color:#29365d}.kids-tile p{margin:0;color:#405078;line-height:1.45}.kids-nav{display:flex;gap:7px;flex-wrap:wrap}.kids-nav a{background:#fff0f6;border:1px solid #f3c5dc;color:#58396d;border-radius:12px;padding:9px 12px;margin:0}.kids-card{background:#fff;border:1px solid #d7e4f4;border-radius:18px;padding:18px;color:#29365d;box-shadow:0 8px 18px #31466a12}.kids-card h2,.kids-card h3{color:#6049a8}.kids-story{max-width:820px;margin:20px auto;background:#fffdf8;color:#293454;border:2px solid #e8d9ae;border-radius:22px;padding:clamp(22px,5vw,42px);font-size:18px;line-height:1.9}.kids-story h1{color:#7150b5}.kids-exam label{display:block;background:#fff;border:1px solid #d8e3f4;border-radius:12px;padding:12px;margin:8px 0;color:#293454}.kids-exam input[type=radio]{width:auto;margin-right:8px}.kids-note{border:1px solid #c6d9f1;background:#f7fbff;color:#3b5274;border-radius:14px;padding:13px 16px;line-height:1.5}.kids-progress{margin-top:16px}.kids-progress-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.kids-progress-grid>div{padding:13px 10px;border-radius:14px;background:linear-gradient(145deg,#f7f2ff,#effaff);text-align:center;border:1px solid #e0daf5}.kids-progress-grid b{display:block;color:#6049a8;font-size:24px;margin-bottom:5px}.kids-progress-grid span{display:block;font-size:12px;color:#53617c;font-weight:700}@media(max-width:560px){.kids-progress-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}body:has(.kids-world){background:linear-gradient(180deg,#fdf8ff,#f0f9ff 54%,#fff8eb);color:#29365d}body:has(.kids-world) header{background:#fff;border-bottom:2px solid #f2d1e7}body:has(.kids-world) .brand{color:#5b4ab1}
@media(max-width:620px){.kids-tiles{grid-template-columns:1fr}.kids-tile{min-height:150px}.kids-nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));width:100%}.kids-nav a{text-align:center}}
/* Stage 23: Sky mascot companion */
.kids-home-hero{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(230px,.9fr);align-items:center;gap:12px;overflow:hidden}
.kids-home-hero .mascot-art{width:100%;max-width:390px;justify-self:center;border-radius:24px;filter:drop-shadow(0 12px 16px #3244772b)}
.kids-greeting{display:inline-block;background:#fff;border:2px solid #f4d8a7;color:#55427e;border-radius:18px;padding:12px 15px;line-height:1.45;box-shadow:0 7px 18px #34446b12;margin-top:10px}
.kids-speech-btn{background:linear-gradient(100deg,#7150bd,#e66eae);border:0;margin-top:9px}
.kids-mascot-dock{position:fixed;right:16px;bottom:16px;z-index:9;display:flex;align-items:center;gap:10px;max-width:min(370px,calc(100vw - 24px));padding:10px 13px 10px 9px;border:2px solid #fff;border-radius:22px;background:#fff;box-shadow:0 10px 30px #34446b35;color:#39456d}
.kids-mascot-dock img{width:92px;height:66px;object-fit:cover;object-position:center;border-radius:14px}
.kids-mascot-dock p{margin:3px 0;font-size:13px;line-height:1.35}.kids-mascot-dock button{padding:7px 10px;font-size:12px}
.kids-favourite{background:#fff1f6;border:1px solid #e8afcb;color:#7a3260;margin-top:8px}
.kids-story-tools{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.kids-story-tools button{background:linear-gradient(100deg,#7250bb,#bd5baf)}
@media(max-width:620px){.kids-home-hero{grid-template-columns:1fr}.kids-home-hero .mascot-art{max-width:270px;max-height:180px;object-fit:cover}.kids-mascot-dock{right:8px;bottom:8px;max-width:calc(100vw - 16px)}.kids-mascot-dock img{width:70px;height:54px}}

/* Stage 24 — Kids World homepage redesign based on the approved illustrated concept. */
body:has(.kids-dashboard){background:linear-gradient(180deg,#087be8 0%,#67c9ff 37%,#e6f8ff 72%,#b5eea5 100%);color:#14265d;min-height:100vh}
body:has(.kids-dashboard) header.kids-topbar{position:relative;top:auto;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:12px clamp(14px,3vw,38px);background:linear-gradient(110deg,#0473e8,#20a6ff);border:0;border-bottom:3px solid #9ce7ff;box-shadow:0 5px 18px #034a9c30}
body:has(.kids-dashboard) main{max-width:1540px;margin:0 auto;padding:clamp(10px,2vw,24px)}
.kids-brand{display:flex;align-items:center;gap:10px;color:#fff;text-decoration:none;filter:drop-shadow(0 2px 2px #174f9b55)}
.kids-brand-globe{font-size:clamp(34px,4vw,53px)}.kids-brand strong,.kids-brand b,.kids-brand small{display:block}.kids-brand strong{font-size:clamp(22px,3vw,34px);line-height:1;color:#fff;letter-spacing:-.5px}.kids-brand b{font-size:clamp(18px,2.4vw,27px);line-height:1;color:#ffdc42;text-shadow:2px 2px #a83c93}.kids-brand small{font-weight:800;font-size:10px;letter-spacing:1.3px;color:#fff}
.kids-account-chip{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:3px 8px;padding:9px 13px;border-radius:18px;border:2px solid #a7a0ff;background:linear-gradient(145deg,#5426b5,#32128e);color:white;box-shadow:0 8px 18px #162e7a55;min-width:185px}.kids-crown{grid-row:span 2;font-size:25px}.kids-account-name{font-weight:900;overflow-wrap:anywhere}.kids-account-chip>b{color:#ffe34e}.kids-account-chip>a{grid-column:1/-1;text-align:center;text-decoration:none;background:#fff;color:#4925a5;font-weight:900;border-radius:20px;padding:5px 10px;margin-top:4px}
.kids-dashboard{position:relative;overflow:hidden;padding:clamp(14px,2.5vw,30px);border:2px solid #fff;border-radius:28px;background:linear-gradient(180deg,#37adff 0%,#b9ecff 52%,#eaffdb 100%);box-shadow:0 16px 38px #1359a32c;isolation:isolate}
.kids-dashboard:before{content:'🌍';position:absolute;z-index:-1;right:8%;top:8%;font-size:clamp(120px,19vw,260px);opacity:.8;filter:drop-shadow(0 10px 15px #0069af33)}
.kids-dashboard:after{content:'';position:absolute;z-index:-1;left:-5%;right:-5%;bottom:-55px;height:190px;background:radial-gradient(ellipse at 15% 55%,#43c85f 0 18%,transparent 19%),radial-gradient(ellipse at 50% 75%,#5bd66f 0 24%,transparent 25%),radial-gradient(ellipse at 90% 60%,#54c85c 0 20%,transparent 21%);opacity:.75}
.kids-dashboard-hero{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(230px,.85fr);align-items:center;gap:12px;min-height:245px;position:relative}
.kids-dashboard-title .kids-tagline{display:inline-block;color:#fff;background:#0753ae88;border:1px solid #d4f5ff88;border-radius:30px;padding:7px 13px;font-size:12px;font-weight:900;letter-spacing:1px}
.kids-dashboard-title h1{font-size:clamp(32px,5.8vw,69px);line-height:.98;margin:12px 0 7px;color:#fff;text-shadow:0 4px 0 #1458a7,0 7px 16px #124b9b55;letter-spacing:-1.5px}.kids-dashboard-title h1 span{display:block;color:#ffe33e;text-shadow:0 3px 0 #aa4da9,0 6px 12px #164b9a66}
.kids-dashboard-title .kids-motto{margin:0;color:#063e91;font-weight:900;font-size:clamp(15px,2vw,22px);letter-spacing:.3px}
.kids-welcome-bubble{display:inline-block;max-width:520px;margin-top:13px;padding:12px 17px;border:2px solid #fff;border-radius:23px;background:#fff;color:#33206f;box-shadow:0 8px 20px #1764a42e;line-height:1.45}
.kids-dashboard-hero .kids-mascot-main{width:100%;max-width:470px;max-height:270px;object-fit:contain;justify-self:center;filter:drop-shadow(0 12px 16px #0752a755);animation:kidsSkyFloat 4.5s ease-in-out infinite}
@keyframes kidsSkyFloat{0%,100%{transform:translateY(0) rotate(-1deg)}50%{transform:translateY(-8px) rotate(1deg)}}
.kids-home-speak{background:linear-gradient(100deg,#6c36c4,#e54aa7);border:2px solid #fff;border-radius:22px;padding:9px 14px;margin-top:10px;box-shadow:0 5px 12px #522a9b33}
.kids-main-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px;margin:12px 0 18px;position:relative;z-index:1}
.kids-main-tile{min-height:330px;display:flex;flex-direction:column;justify-content:space-between;align-items:stretch;padding:17px 14px 14px;border:3px solid #fff;border-radius:31px;text-align:center;text-decoration:none;color:#2c1b6d;box-shadow:0 11px 22px #134f9b33;transition:transform .17s,box-shadow .17s;overflow:hidden}
.kids-main-tile:hover,.kids-main-tile:focus-visible{transform:translateY(-5px);box-shadow:0 17px 28px #134f9b45;outline:4px solid #fff7}
.kids-main-tile.story{background:linear-gradient(155deg,#ff74d2,#e934a6)}.kids-main-tile.movie{background:linear-gradient(155deg,#ffd64a,#ff981c)}.kids-main-tile.games{background:linear-gradient(155deg,#a6f35d,#45d65b)}.kids-main-tile.exam{background:linear-gradient(155deg,#e58bff,#9b42ee)}
.kids-tile-illustration{height:142px;display:grid;place-items:center;font-size:clamp(72px,8vw,112px);filter:drop-shadow(0 6px 4px #55297935)}
.kids-main-tile h2{font-size:clamp(20px,2vw,29px);line-height:1;margin:6px 0 8px;text-transform:uppercase;color:white;text-shadow:0 3px 0 #41247e,2px 4px 4px #3b276a66}
.kids-main-tile p{display:grid;place-items:center;min-height:57px;margin:0;background:#fffdf0dd;border-radius:22px;color:#34205e;font-weight:800;line-height:1.3;padding:9px;font-size:clamp(12px,1.2vw,15px)}
.kids-tile-arrow{align-self:center;display:grid;place-items:center;width:48px;height:42px;margin-top:9px;border:2px solid #ffffffb0;border-radius:24px;background:#fff;color:#5629a7;font-size:24px;font-weight:900;box-shadow:0 4px 0 #5b3186a6}
.kids-progress-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;position:relative;z-index:1;overflow:hidden;border:3px solid #fff;border-radius:24px;background:#fffdf1ee;box-shadow:0 8px 18px #17579a2b;color:#183a85}
.kids-progress-item{display:flex;align-items:center;justify-content:center;gap:10px;padding:14px 8px;text-align:center;border-right:2px solid #a9c7ff}.kids-progress-item:last-child{border-right:0}.kids-progress-item .progress-emoji{font-size:clamp(24px,3vw,39px)}.kids-progress-item b{display:block;font-size:clamp(15px,1.5vw,19px);color:#2f2181}.kids-progress-item span{display:block;font-size:11px;font-weight:800;color:#52628d}
.kids-bottom-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:14px;position:relative;z-index:1}.kids-bottom-bar a{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:11px 18px;border:2px solid #fff;border-radius:28px;background:linear-gradient(100deg,#0876e8,#1350b4);color:#fff;text-decoration:none;font-weight:900;box-shadow:0 5px 0 #17438c}.kids-bottom-bar a.logout{background:linear-gradient(100deg,#8c38db,#5621b3)}.kids-bottom-message{flex:1;text-align:center;color:#fff;font-weight:900;font-size:clamp(13px,2vw,19px);text-shadow:0 2px 4px #124b8e}
.kids-privacy-reminder{position:relative;z-index:1;margin:14px 0 0;text-align:center;color:#184a75;font-size:12px;font-weight:700}
body:has(.kids-dashboard) footer{color:#174d80;padding:16px}
@media(max-width:900px){.kids-main-tile{min-height:290px}.kids-tile-illustration{height:118px}.kids-dashboard-hero{min-height:210px}}
@media(max-width:650px){body:has(.kids-dashboard) header.kids-topbar{padding:10px 13px}.kids-account-chip{min-width:145px;grid-template-columns:auto 1fr;padding:7px 10px}.kids-account-name{font-size:13px}.kids-dashboard{padding:13px;border-radius:20px}.kids-dashboard-hero{grid-template-columns:1fr;gap:0;text-align:center}.kids-dashboard-hero .kids-mascot-main{max-width:310px;max-height:180px;grid-row:1}.kids-dashboard-title h1{font-size:clamp(32px,10vw,49px)}.kids-welcome-bubble{font-size:14px}.kids-main-tiles{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.kids-main-tile{min-height:238px;padding:12px 9px;border-radius:23px}.kids-tile-illustration{height:90px;font-size:68px}.kids-main-tile h2{font-size:19px}.kids-main-tile p{font-size:12px;min-height:50px}.kids-tile-arrow{width:40px;height:36px}.kids-progress-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.kids-progress-item{border-right:0;border-bottom:1px solid #a9c7ff;padding:10px 5px}.kids-progress-item:nth-child(odd){border-right:1px solid #a9c7ff}.kids-progress-item:nth-last-child(-n+2){border-bottom:0}.kids-bottom-bar a{padding:9px 12px;font-size:13px}.kids-bottom-message{font-size:12px}}
@media(max-width:380px){.kids-brand strong{font-size:19px}.kids-brand b{font-size:17px}.kids-account-chip{min-width:130px}.kids-main-tile{min-height:215px}.kids-tile-illustration{height:75px;font-size:58px}.kids-main-tile h2{font-size:16px}}


/* Stage 30: persistent, unmistakable Owner Undercover Mode indicator */
.undercover-ribbon{position:sticky;top:0;z-index:9;display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:wrap;padding:11px 16px;background:linear-gradient(100deg,#5a2b08,#8b4b08 55%,#5a2b08);border-bottom:2px solid #ffd36b;color:#fff4d1;font-weight:800;text-align:center;box-shadow:0 5px 18px #0005}
.undercover-ribbon strong{color:#ffe08d;letter-spacing:.7px}
.undercover-ribbon a{display:inline-block;background:#fff0bd;color:#4b2b08;text-decoration:none;padding:7px 12px;border-radius:9px;border:1px solid #ffdc7e;font-weight:900}
.undercover-panel{border:1px solid #d29a43;background:linear-gradient(145deg,#35240d,#101f35);border-radius:20px;padding:22px;box-shadow:0 12px 30px #0004}
.undercover-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}
.undercover-step{padding:14px;border:1px solid #8e652f;border-radius:13px;background:#171f2d}
.undercover-step b{display:block;color:#ffdc88;margin-bottom:5px}
.undercover-warning{padding:13px 15px;border-left:4px solid #ffca63;background:#3a2a13;border-radius:8px;color:#ffeac0;line-height:1.55}
.undercover-confirm{display:flex;align-items:flex-start;gap:10px;margin:12px 0 18px;color:#e8d8b6;line-height:1.5}
.undercover-confirm input{width:auto;margin:4px 0 0;flex:0 0 auto}
@media(max-width:650px){.undercover-ribbon{position:static;flex-direction:column;gap:7px}.undercover-panel{padding:17px}}

/* Stage 29: Airline Empire simulation */
.airline-hero{background:radial-gradient(circle at 85% 18%,#2d91cb55,transparent 30%),linear-gradient(120deg,#102e57,#061329 72%);border:1px solid #39baff;border-radius:24px;padding:clamp(22px,4vw,42px);box-shadow:0 18px 45px #0005}
.airline-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:18px 0}
.airline-card{background:linear-gradient(145deg,#102a4d,#07172c);border:1px solid #27628f;border-radius:16px;padding:18px;min-width:0}
.airline-card h3{color:#82ddff;margin-top:0}
.airline-brand{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.airline-logo{width:64px;height:64px;border-radius:18px;display:grid;place-items:center;font-size:34px;background:linear-gradient(145deg,#1b75b7,#0b2850);border:1px solid #72d8ff}
.airline-stat{font-size:24px;font-weight:900;color:#ffda78}
.airline-row{display:flex;justify-content:space-between;gap:12px;align-items:center;padding:10px 0;border-top:1px solid #234563;flex-wrap:wrap}
.airline-row small{color:#a9c0d8}
.airline-table{width:100%;border-collapse:collapse;min-width:560px}
.airline-table th,.airline-table td{text-align:left;padding:10px;border-bottom:1px solid #254561}
.airline-table th{color:#8ee1ff}
.airline-table-wrap{overflow-x:auto}
.airline-code{display:inline-block;padding:5px 8px;border:1px solid #64cfff;border-radius:8px;letter-spacing:2px;font-weight:900;color:#b7edff}
@media(max-width:650px){.airline-hero{padding:22px}.airline-grid{grid-template-columns:1fr}.airline-stat{font-size:21px}}
</style></head><body>
{% if user and user['role']=='member' and user['mode']=='kids' %}
<header class="kids-topbar">
  <a class="kids-brand" href="{{url_for('home')}}" aria-label="AIR TRAVEL Kids World home">
    <span class="kids-brand-globe" aria-hidden="true">🌍</span>
    <span><strong>AIR TRAVEL</strong><b>KIDS WORLD</b><small>LEARN · PLAY · DREAM · FLY</small></span>
  </a>
  {% if request.endpoint == 'home' %}
  <div class="kids-account-chip"><span class="kids-crown">👑</span><span class="kids-account-name">{{user['username'] or user['name']}}</span><b>⭐ {{user['exp']}} EXP</b><a href="#kidsProgress">My Progress</a></div>
  {% else %}
  <nav class="kids-nav"><a href="{{url_for('home')}}">🏡 Home</a><a href="{{url_for('kids_storybooks')}}">📚 Story Books</a><a href="{{url_for('cinema')}}">🎬 Movie Night</a><a href="{{url_for('games')}}">🎮 Games</a><a href="{{url_for('kids_exam')}}">📝 Exam</a>{% if session.get('undercover_owner_uid') %}<a href="{{url_for('undercover_return')}}">👑 Return to Owner</a>{% endif %}<a href="{{url_for('logout')}}">Log out</a></nav>
  {% endif %}
</header>
{% else %}
<header><a class="brand" href="{{url_for('home')}}"><img src="{{url_for('static',filename='media/air_travel_official_logo.png')}}" alt="AIR TRAVEL official logo" style="width:58px;height:48px;object-fit:contain;border-radius:8px"><span>AIR TRAVEL</span></a><nav><a href="{{url_for('home')}}">Home</a><a href="{{url_for('flights')}}">Flights</a><a href="{{url_for('booking_centre')}}">Book Flight</a><a href="{{url_for('live_flight_search')}}">Live Flight Search</a><a href="{{url_for('trip_planner')}}">🧳 Trip Planner</a><a href="{{url_for('games')}}">Games</a><a href="{{url_for('quiz')}}">Aviation Quiz</a><a href="{{url_for('flight_academy')}}">✈ Flight Academy</a><a href="{{url_for('career_centre')}}">🧭 Career Centre</a><a href="{{url_for('career_assessment')}}">🎮 Virtual Aviation Experience</a><a href="{{url_for('world')}}">ATW World</a><a href="{{url_for('passport')}}">Passport</a><a href="{{url_for('tycoon')}}">Airport Tycoon</a><a href="{{url_for('airline_empire')}}">✈️ Airline Empire</a><a href="{{url_for('wheel')}}">EXP Wheel</a><a href="{{url_for('achievements')}}">Achievements</a><a href="{{url_for('community')}}">ATW Chat</a><a href="{{url_for('announcements')}}">📢 Announcements</a><a href="{{url_for('events_centre')}}">🗓️ Events</a><a href="{{url_for('ai_assistant')}}">🤖 AIR TRAVEL AI</a><a href="https://discord.gg/maVTUuMQe" target="_blank" rel="noopener noreferrer">Join Discord</a><a href="{{url_for('experience')}}">EXP Shop</a>{% if user and user['role']=='member' %}<a href="{{url_for('exp_wallet')}}">EXP Wallet</a><a href="{{url_for('my_profile')}}">👤 My Profile</a><a href="{{url_for('customise_profile')}}">🎨 Edit Profile</a><a href="{{url_for('friends_centre')}}">🤝 Friends</a><a href="{{url_for('security_centre')}}">🔐 Security</a>{% endif %}<a href="{{url_for('premium')}}">Premium</a><a href="{{url_for('cinema')}}">Movie Night</a><a href="{{url_for('ideas')}}">More</a><a href="{{url_for('owner_tribute')}}">👑 Owner Tribute</a><a href="{{url_for('versions')}}">Kids / General</a><a class="owner-nav" href="{{url_for('owner_login')}}">👑 OWNER LOGIN</a>{% if user and user['role']=='owner' %}<a href="{{url_for('owner_dashboard')}}">Owner HQ</a><a href="{{url_for('owner_member_profiles')}}">👥 Member Profiles</a><a href="{{url_for('owner_security_centre')}}">🛡️ Security Centre</a><a href="{{url_for('owner_overview')}}">HQ Overview</a><a href="{{url_for('owner_event_manager')}}">Event Manager</a><a href="{{url_for('owner_airline_empire')}}">✈️ Airline Control</a><a href="{{url_for('owner_kids_studio')}}">🌈 Kids World Studio</a><a href="{{url_for('owner_careers')}}">Career Management</a><a href="{{url_for('owner_tribute_manage')}}">Edit Owner Tribute</a><a href="{{url_for('owner_milestones_manage')}}">Founder Timeline</a>{% endif %}{% if session.get('undercover_owner_uid') %}<a href="{{url_for('undercover_return')}}">👑 Return to Owner</a>{% endif %}{% if user %}<a href="{{url_for('logout')}}">Log out</a>{% else %}<a href="{{url_for('login')}}">Guest login</a><a href="{{url_for('owner_login')}}">Owner login</a>{% endif %}</nav></header>
{% endif %}
{% if session.get('undercover_owner_uid') %}<div class="undercover-ribbon"><span>🕵️ <strong>OWNER UNDERCOVER TEST</strong> · Viewing as {{session.get('undercover_member_label','a member')}} · {{session.get('undercover_member_mode','Member')}} experience</span><a href="{{url_for('undercover_return')}}">👑 Exit &amp; Return to Owner HQ</a></div>{% endif %}
<main>{% with messages=get_flashed_messages(with_categories=true) %}{% for cat,msg in messages %}<div class="notice {{'error' if cat=='error' else ''}}">{{msg}}</div>{% endfor %}{% endwith %}{{body|safe}}</main>{% if user and user['role']=='member' and user['mode']=='kids' %}{% if request.endpoint != 'home' %}<aside class="kids-mascot-dock" aria-label="Sky the Kids World helper"><img src="{{url_for('static',filename='media/kids_world_mascot.png')}}" alt="Sky, the friendly airplane mascot"><div><b>Hi, I'm Sky! ✈️</b><p id="skyTip">Take your time, have fun and ask a grown-up if you need help.</p><button class="kids-speech-btn" id="skySpeak" type="button">🔊 Hear Sky</button></div></aside>{% endif %}<script>(()=>{const b=document.getElementById('skySpeak');if(b)b.addEventListener('click',()=>{const t=document.getElementById('skyTip').textContent;if(!('speechSynthesis'in window)){b.textContent='Audio is not available';return}speechSynthesis.cancel();const u=new SpeechSynthesisUtterance('Hi, I am Sky! '+t);u.lang='en-GB';speechSynthesis.speak(u)});const h=document.getElementById('skyHomeSpeak');if(h)h.addEventListener('click',()=>{const t=document.getElementById('skyGreeting').innerText;if(!('speechSynthesis'in window)){h.textContent='Audio is not available';return}speechSynthesis.cancel();const u=new SpeechSynthesisUtterance('Hello, explorers! '+t);u.lang='en-GB';speechSynthesis.speak(u)});})();</script>{% endif %}{% if user and user['role']=='member' and user['mode']=='kids' %}<footer>🌈 AIR TRAVEL KIDS WORLD · Read · Watch · Play · Learn</footer>{% else %}<footer>AIR TRAVEL · Explore · Connect · Discover<br><small>Independent community project. Not an aviation control or radio service.</small></footer>{% endif %}
{% if not (user and user['role']=='member' and user['mode']=='kids') %}<div id="entryAd" class="ad-overlay ad-hidden" aria-label="AIR TRAVEL WORLD introduction"><div class="ad-card"><img src="/static/media/explainer_poster.jpg" alt="Air Travel World aviation introduction"><div class="ad-copy"><span class="tag">WELCOME TO AIR TRAVEL WORLD</span><h2 id="adHeadline">Your world. Your sky.</h2><p id="adNarration">Explore aviation, discover destinations and enjoy your own aviation world.</p><p class="ad-count" id="adCount">Introduction · 10 seconds</p><button id="hearAd" class="btn alt" type="button">▶ Hear introduction</button> <button id="skipAd" disabled>Continue in 10</button></div></div></div>
<script>
(()=>{const key='atw_entry_ad_seen_session';const overlay=document.getElementById('entryAd');if(!overlay||sessionStorage.getItem(key))return;overlay.classList.remove('ad-hidden');let left=10;const label=document.getElementById('adCount'),btn=document.getElementById('skipAd'),headline=document.getElementById('adHeadline'),copy=document.getElementById('adNarration');const scenes=[['Your world. Your sky.','Welcome to AIR TRAVEL, your home for travel, discovery and entertainment.'],['Explore flights','Discover aircraft information and explore flight options.'],['Play and earn','Enjoy aviation games, challenges and EXP rewards.'],['Movie Night and more','Visit Movie Night, Kids World, the Gift Shop and our community.'],['Take off with ATW','Create your account and start exploring today.']];let spoken=false;function speak(){if(!('speechSynthesis'in window)){copy.textContent='Audio narration is not supported by this browser.';return}speechSynthesis.cancel();const utter=new SpeechSynthesisUtterance(scenes.map(x=>x[1]).join(' '));utter.lang='en-GB';utter.rate=1;window.speechSynthesis.speak(utter);spoken=true}document.getElementById('hearAd').addEventListener('click',speak);const close=()=>{overlay.classList.add('ad-hidden');sessionStorage.setItem(key,'1');if('speechSynthesis'in window)speechSynthesis.cancel()};const timer=setInterval(()=>{left--;const scene=Math.min(4,Math.floor((10-left)/2));headline.textContent=scenes[scene][0];copy.textContent=scenes[scene][1];label.textContent=left>0?`Welcome tour · ${left} seconds remaining`:'Welcome aboard!';btn.textContent=left>0?`Continue in ${left}`:'Enter AIR TRAVEL';if(left<=0){btn.disabled=false;clearInterval(timer);setTimeout(close,900)}},1000);btn.addEventListener('click',()=>{if(!btn.disabled){clearInterval(timer);close()}})})();
</script>{% endif %}</body></html>'''
def page(title,body,**ctx): return render_template_string(BASE,title=title,body=render_template_string(body, user=current_user(),csrf_token=session.get('csrf_token',''),**ctx),user=current_user())
@app.route('/')
def home():
 u=current_user()
 if u and u['role']=='member' and u['mode']=='kids':
  c=db(); uid=u['id']
  story_count=c.execute("SELECT COUNT(*) FROM kids_activity_progress WHERE user_id=? AND activity_type='story' AND completed_count>0",(uid,)).fetchone()[0]
  sky_best=c.execute("SELECT COALESCE(MAX(best_score),0) FROM kids_activity_progress WHERE user_id=? AND activity_type='sky_stars'",(uid,)).fetchone()[0]
  timing_wins=c.execute("SELECT COALESCE(SUM(completed_count),0) FROM kids_activity_progress WHERE user_id=? AND activity_type='perfect_timing'",(uid,)).fetchone()[0]
  best_exam=c.execute('SELECT score,total FROM kids_exam_attempts WHERE user_id=? AND total>0 ORDER BY (score*1.0/total) DESC, id DESC LIMIT 1',(uid,)).fetchone()
  exam_label=(f"{best_exam['score']}/{best_exam['total']}" if best_exam else 'Not tried yet')
  sky_message = ('Amazing reading! You have finished some stories.' if story_count else 'Pick a story, enjoy a video, play a game or try the exam. You can do it!')
  if sky_best >= 10: sky_message = 'Wow, you have collected lots of stars! Keep practising and having fun.'
  elif best_exam and best_exam['score'] >= best_exam['total'] * 0.7: sky_message = 'Great work on your practice exam! Keep learning at your own pace.'
  return page('Kids World', r'''<div class="kids-dashboard">
<section class="kids-dashboard-hero">
  <div class="kids-dashboard-title">
    <span class="kids-tagline">WELCOME TO YOUR LITTLE WORLD</span>
    <h1>AIR TRAVEL <span>KIDS WORLD</span></h1>
    <p class="kids-motto">Learn · Play · Dream · Fly</p>
    <div class="kids-welcome-bubble" id="skyGreeting"><b>✈️ Sky says:</b> {{sky_message}} 💜</div><br>
    <button id="skyHomeSpeak" class="kids-home-speak" type="button">🔊 Hear Sky say hello</button>
  </div>
  <img class="kids-mascot-main" src="{{url_for('static',filename='media/kids_world_mascot.png')}}" alt="Sky, the friendly airplane mascot giving a thumbs-up">
</section>
<section class="kids-main-tiles" aria-label="Kids World activities">
  <a class="kids-main-tile story" href="{{url_for('kids_storybooks')}}"><div><div class="kids-tile-illustration" aria-hidden="true">📖</div><h2>Story Books</h2><p>Read amazing stories!</p></div><span class="kids-tile-arrow" aria-hidden="true">→</span></a>
  <a class="kids-main-tile movie" href="{{url_for('cinema')}}"><div><div class="kids-tile-illustration" aria-hidden="true">🎬</div><h2>Movie Night</h2><p>Watch fun videos approved by your grown-up!</p></div><span class="kids-tile-arrow" aria-hidden="true">→</span></a>
  <a class="kids-main-tile games" href="{{url_for('games')}}"><div><div class="kids-tile-illustration" aria-hidden="true">🎮</div><h2>Games</h2><p>Play and challenge yourself!</p></div><span class="kids-tile-arrow" aria-hidden="true">→</span></a>
  <a class="kids-main-tile exam" href="{{url_for('kids_exam')}}"><div><div class="kids-tile-illustration" aria-hidden="true">📝</div><h2>Exam</h2><p>Test your knowledge!</p></div><span class="kids-tile-arrow" aria-hidden="true">→</span></a>
</section>
<section class="kids-progress-strip" id="kidsProgress" aria-label="Your learning progress">
  <div class="kids-progress-item"><span class="progress-emoji">🏆</span><div><b>{{story_count}}</b><span>Stories read</span></div></div>
  <div class="kids-progress-item"><span class="progress-emoji">⭐</span><div><b>{{sky_best}}</b><span>Best game stars</span></div></div>
  <div class="kids-progress-item"><span class="progress-emoji">🎮</span><div><b>{{timing_wins}}</b><span>Game wins</span></div></div>
  <div class="kids-progress-item"><span class="progress-emoji">🌟</span><div><b>{{exam_label}}</b><span>Best exam result</span></div></div>
</section>
<div class="kids-bottom-bar"><a href="{{url_for('home')}}">🏠 Home</a><div class="kids-bottom-message">⭐ You can do it! Reach for the stars! ⭐</div>{% if session.get('undercover_owner_uid') %}<a href="{{url_for('undercover_return')}}">👑 Owner HQ</a>{% else %}<a class="logout" href="{{url_for('logout')}}">↪ Log out</a>{% endif %}</div>
<p class="kids-privacy-reminder">💜 Keep your password, address, school and phone number private. Ask a parent or guardian to help choose videos.</p>
</div>''', story_count=story_count,sky_best=sky_best,timing_wins=timing_wins,exam_label=exam_label,sky_message=sky_message)
 home_announcements=db().execute('SELECT id,title,body,created_at FROM announcements WHERE is_published=1 ORDER BY id DESC LIMIT 3').fetchall()
 return page('Home','''<div class="home-shell">
<section class="home-hero"><div class="hero-copy"><span class="eyebrow">✦ THE WORLD OF AVIATION, REIMAGINED</span><h1>YOUR WORLD.<span>YOUR SKY.</span></h1><p>Welcome to AIR TRAVEL. Explore destinations, enjoy entertainment, play games and collect rewards — all in one place.</p><div class="hero-actions"><a class="btn" href="{{url_for('flights')}}">✈ Explore Flights</a><a class="btn alt" href="{{url_for('booking_centre')}}">Book a Flight</a><a class="btn alt" href="{{url_for('community')}}">💬 ATW Chat</a><a class="btn alt" href="https://discord.gg/maVTUuMQe" target="_blank" rel="noopener noreferrer">Join our Discord ↗</a><a class="btn" href="{{url_for('owner_login')}}">👑 OWNER LOGIN</a>{% if not user %}<a class="btn alt" href="{{url_for('register')}}">Join ATW</a>{% endif %}</div><div class="hero-note">✦ DISCOVER · PLAY · CONNECT · COLLECT</div><div class="hero-actions"><button type="button" class="btn alt" id="homeMusicToggle" aria-pressed="false">♫ Play homepage music</button><span class="hero-note" id="musicStatus" aria-live="polite">Optional background music · starts when you press Play</span></div></div></section>
<script>
(()=>{const button=document.getElementById('homeMusicToggle');if(!button)return;let ctx=null,master=null,oscillators=[],playing=false,timer=null;const status=document.getElementById('musicStatus');function stop(){if(timer)clearInterval(timer);oscillators.forEach(o=>{try{o.stop()}catch(e){}});oscillators=[];if(master){try{master.gain.setTargetAtTime(0,ctx.currentTime,.15)}catch(e){}}playing=false;button.textContent='♫ Play homepage music';button.setAttribute('aria-pressed','false');status.textContent='Music paused.'}function start(){const AC=window.AudioContext||window.webkitAudioContext;if(!AC){status.textContent='This browser does not support background music.';return}ctx=ctx||new AC();ctx.resume();master=ctx.createGain();master.gain.value=.045;master.connect(ctx.destination);const notes=[261.63,329.63,392.00,329.63,293.66,349.23,440.00,349.23];let i=0;function note(){if(!playing)return;const o=ctx.createOscillator(),g=ctx.createGain();o.type='sine';o.frequency.value=notes[i%notes.length];g.gain.setValueAtTime(.0001,ctx.currentTime);g.gain.exponentialRampToValueAtTime(.24,ctx.currentTime+.12);g.gain.exponentialRampToValueAtTime(.0001,ctx.currentTime+1.05);o.connect(g);g.connect(master);o.start();o.stop(ctx.currentTime+1.1);oscillators.push(o);i++}playing=true;note();timer=setInterval(note,850);button.textContent='Ⅱ Pause homepage music';button.setAttribute('aria-pressed','true');status.textContent='Soft instrumental homepage music is playing.'}button.addEventListener('click',()=>playing?stop():start());})();
</script>
{% if home_announcements %}<section class="card" style="border-color:#e2b84c;margin-top:18px"><div class="home-section-head"><div><h2>📢 Latest Announcements</h2><p>Official messages from Owner HQ</p></div><a class="btn alt" href="{{url_for('announcements')}}">View all</a></div>{% for a in home_announcements %}<div style="border-top:1px solid #7b642f;padding:12px 0;margin-top:10px"><h3>{{a['title']}}</h3><p>{{a['body']}}</p><small class="muted">{{a['created_at'][:16]}}</small></div>{% endfor %}</section>{% endif %}
<div class="home-stats"><div class="home-stat"><b>✈ Flight World</b><span>Explore aviation</span></div><div class="home-stat"><b>🌍 ATW Universe</b><span>Discover more worlds</span></div><div class="home-stat"><b>🎬 Movie Night</b><span>Your entertainment space</span></div><div class="home-stat"><b>🏆 EXP Rewards</b><span>Play and earn</span></div></div>
<div class="home-section-head"><div><h2>Explore AIR TRAVEL WORLD</h2><p>Everything you need, one click away.</p></div><span class="tag">YOUR JOURNEY STARTS HERE</span></div>
<div class="home-modules">
<a class="home-module" href="{{url_for('flights')}}" data-symbol="✈"><div class="module-icon">🛫</div><h3>Flight Tracking</h3><p>Explore aircraft information and available flight-data features.</p><span class="module-link">OPEN FLIGHTS →</span></a>
<a class="home-module" href="{{url_for('booking_centre')}}" data-symbol="🌐"><div class="module-icon">🎫</div><h3>Flight Booking Centre</h3><p>Explore airline booking enquiries and travel options.</p><span class="module-link">FIND A FLIGHT →</span></a>
<a class="home-module" href="{{url_for('games')}}" data-symbol="🎮"><div class="module-icon">🎮</div><h3>Games Arcade</h3><p>Play Sky Dodger and Perfect Landing challenges.</p><span class="module-link">PLAY NOW →</span></a>
<a class="home-module" href="{{url_for('quiz')}}" data-symbol="🧠"><div class="module-icon">🧠</div><h3>Aviation Quiz</h3><p>Answer aviation questions, get instant feedback and track your score.</p><span class="module-link">TAKE QUIZ →</span></a>
<a class="home-module" href="{{url_for('world')}}" data-symbol="🌍"><div class="module-icon">🌍</div><h3>ATW World Globe</h3><p>Explore a rotating globe and discover destinations around the world.</p><span class="module-link">EXPLORE THE WORLD →</span></a>
<a class="home-module" href="{{url_for('passport')}}" data-symbol="🛂"><div class="module-icon">🛂</div><h3>Digital Passport</h3><p>Collect virtual destination stamps as you explore ATW.</p><span class="module-link">OPEN PASSPORT →</span></a>
<a class="home-module" href="{{url_for('tycoon')}}" data-symbol="🏙"><div class="module-icon">🏙</div><h3>Airport Tycoon</h3><p>Build terminals, gates and runways in your own virtual airport.</p><span class="module-link">BUILD AIRPORT →</span></a>
<a class="home-module" href="{{url_for('wheel')}}" data-symbol="🎡"><div class="module-icon">🎡</div><h3>Daily EXP Wheel</h3><p>One free spin each day for virtual EXP rewards. No payment required.</p><span class="module-link">SPIN DAILY →</span></a>
<a class="home-module" href="{{url_for('achievements')}}" data-symbol="🏆"><div class="module-icon">🏆</div><h3>Achievement Wall</h3><p>Show your ATW milestones and see the EXP leaderboard.</p><span class="module-link">VIEW ACHIEVEMENTS →</span></a>
<a class="home-module" href="{{url_for('cinema')}}" data-symbol="▶"><div class="module-icon">🎬</div><h3>Movie Night</h3><p>Open your cinema and play a video you own or are licensed to watch.</p><span class="module-link">ENTER CINEMA →</span></a>
<a class="home-module" href="{{url_for('experience')}}" data-symbol="✧"><div class="module-icon">🎁</div><h3>EXP Gift Shop</h3><p>Browse virtual collectibles and redeem eligible items with EXP.</p><span class="module-link">VISIT GIFT SHOP →</span></a>
<a class="home-module" href="{{url_for('premium')}}" data-symbol="♛"><div class="module-icon">👑</div><h3>Premium Lounge</h3><p>Explore Premium plans and available EXP redemption options.</p><span class="module-link">VIEW PREMIUM →</span></a>
<a class="home-module" href="{{url_for('community')}}" data-symbol="◎"><div class="module-icon">💬</div><h3>ATW Chat</h3><p>Post messages and connect with the ATW community.</p><span class="module-link">OPEN ATW CHAT →</span></a>
<a class="home-module" href="{{url_for('versions')}}" data-symbol="★"><div class="module-icon">🧸</div><h3>Kids World</h3><p>Explore the Kids experience. Adult supervision and safety controls matter.</p><span class="module-link">EXPLORE KIDS WORLD →</span></a>
<a class="home-module" href="{{url_for('events_centre')}}" data-symbol="🗓️"><div class="module-icon">🗓️</div><h3>Events Centre</h3><p>Find upcoming AIR TRAVEL competitions, aviation activities and community events.</p><span class="module-link">EXPLORE EVENTS →</span></a><a class="home-module" href="{{url_for('owner_login')}}" data-symbol="👑"><div class="module-icon">🔐</div><h3>Owner Login & HQ</h3><p>Separate secure sign-in for the AIR TRAVEL WORLD owner dashboard.</p><span class="module-link">OPEN OWNER LOGIN →</span></a>
<a class="home-module" href="{{url_for('owner_tribute')}}" data-symbol="♕"><div class="module-icon">🏅</div><h3>Founder Tribute</h3><p>Visit the founder celebration and special ATW announcements.</p><span class="module-link">VIEW TRIBUTE →</span></a>
</div>
{% if user %}<section class="home-member"><div><h3>Welcome back, {{user['name']}}!</h3><p>Your ATW journey is ready. Claim your daily reward when available.</p><div class="home-exp">{{'{:,}'.format(user['exp'])}} EXP</div></div><form method="post" action="{{url_for('daily_reward')}}"><button>Claim Daily 50 EXP</button></form></section>{% else %}<section class="home-member"><div><h3>Ready for take-off?</h3><p>Create an account to start with 1,000 EXP and explore the member experience.</p></div><div><a class="btn" href="{{url_for('register')}}">Create Account</a> <a class="btn alt" href="{{url_for('login')}}">Guest Login</a></div></section>{% endif %}
<div class="home-bottom"><span><strong>AKINOLA AJIDE OWNER</strong> · JAYDINE CO-OWNER</span><span><a href="{{url_for('owner_login')}}">Owner Login</a> &nbsp;·&nbsp; <a href="{{url_for('ideas')}}">Discover More ATW Features</a> &nbsp;·&nbsp; <a href="https://discord.gg/maVTUuMQe" target="_blank" rel="noopener noreferrer">Join ATW Discord ↗</a></span></div>
</div>''',home_announcements=home_announcements)
def _normalise_name_text(value):
 import unicodedata, re
 value=unicodedata.normalize('NFKC', value or '').casefold()
 # Remove separators to make simple punctuation/spacing evasions harder.
 return re.sub(r'[\W_]+', '', value, flags=re.UNICODE)

def screen_username_with_ai(username):
 """Return (decision, explanation, method). AI is optional; local safeguards always run."""
 import re
 clean=_normalise_name_text(username)
 reserved={'admin','owner','support','moderator','airtravel'}
 if clean in reserved:
  return 'reject','This username is reserved for official AIR TRAVEL roles.','local'
 # Clear impersonation, extremist glorification, and explicit abusive/vulgar handles.
 hard_block={'hitler','adolfhitler','nazi','nazis','heilhitler','fckyou','motherfucker','pornhub'}
 if clean in hard_block or any(term in clean for term in ('hitler','heilhitler','nazi')):
  return 'reject','This username contains hateful, extremist or abusive content. Choose a respectful name.','local'
 # “Dick” may be a legitimate given name, so send it for context review rather than
 # automatically rejecting a person's legal/display name. As a handle, review it.
 if clean in {'dick','d1ck'} or any(term in clean for term in ('fuck','shit','bitch','cunt','slur')):
  return 'review','This username may be vulgar or inappropriate and needs a safety review.','local'
 api_key=os.environ.get('OPENAI_API_KEY','').strip()
 if not api_key:
  return 'allow','Automatic basic checks passed. AI name review is not connected on this server.','local'
 # Only the proposed username is sent for moderation; the registrant's full name is not sent.
 instructions=(
  'You moderate usernames for a family-friendly aviation community used by adults and minors. '
  'Assess only whether the proposed username is clearly vulgar, sexually explicit, hateful, a slur, '
  'praising a genocidal extremist, threatening, or impersonating official staff. '
  'Do NOT reject neutral identity words or ordinary names. In particular, the word gay by itself '
  'is not offensive and must be allowed; do not treat LGBTQ identity as inappropriate. '
  'A common personal name such as Dick should be reviewed in context, not assumed to be abusive. '
  'Return only JSON: {"decision":"allow|review|reject","reason":"short neutral explanation"}. '
  'Use reject only for clearly unacceptable content; use review when uncertain.'
 )
 payload=json.dumps({'model':os.environ.get('OPENAI_MODEL','gpt-4.1-mini'),'instructions':instructions,
  'input':'Proposed username: '+username[:24],'max_output_tokens':120,'store':False}).encode('utf-8')
 req=urllib.request.Request('https://api.openai.com/v1/responses',data=payload,
  headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=8) as response: result=json.loads(response.read().decode('utf-8'))
  raw=''.join(part.get('text','') for item in result.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text').strip()
  match=re.search(r'\{.*\}',raw,re.S)
  data=json.loads(match.group(0)) if match else {}
  decision=data.get('decision')
  if decision not in {'allow','review','reject'}: raise ValueError('Invalid moderation response')
  reason=str(data.get('reason','Username reviewed.'))[:180]
  return decision,reason,'ai'
 except Exception:
  # Fail closed to human review if the AI service is configured but unavailable.
  return 'review','Automated name review could not be completed. An owner must review this username.','fallback'

def registration_screen(name, age, username):
 import re
 flags=[]
 if len(username)<3 or not re.fullmatch(r'[A-Za-z0-9_.-]+',username): flags.append('Username must be 3+ characters and use letters, numbers, dots, underscores or hyphens.')
 decision,reason,method=screen_username_with_ai(username)
 if decision=='reject': flags.append(reason)
 elif decision=='review': flags.append(reason)
 if age < 13: flags.append('A parent or guardian must complete the child-account consent process before approval.')
 return flags,decision,reason,method

@app.route('/register',methods=['GET','POST'])
def register():
 if request.method=='POST':
  name=request.form.get('name','').strip(); username=request.form.get('username','').strip(); pw=request.form.get('password','');
  try: age=int(request.form.get('age','0'))
  except ValueError: age=0
  if len(name)<2 or not 1<=age<=120 or len(pw)<10:
   flash('Enter your name, a valid age and a password of at least 10 characters.','error')
  else:
   flags,name_decision,name_reason,name_method=registration_screen(name,age,username)
   status='pending_review' if flags else 'approved'
   if age<13: status='pending_guardian'
   try:
    c=db(); internal_email=f"{username.lower()}@guest.airtravel.local"
    c.execute('INSERT INTO users(email,name,password_hash,role,exp,mode,created_at,username,age,approval_status) VALUES(?,?,?,?,?,?,?,?,?,?)',(internal_email,name,generate_password_hash(pw),'member',1000,'general',datetime.utcnow().isoformat(),username,age,status))
    uid=c.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()['id']
    if name_decision in {'review','reject'}:
     c.execute('INSERT OR IGNORE INTO username_review_queue(user_id,username,decision,reason,method,status,created_at) VALUES(?,?,?,?,?,?,?)',(uid,username,name_decision,name_reason,name_method,'pending',datetime.utcnow().isoformat()))
    c.execute('INSERT INTO account_activity(user_id,event,details,created_at) VALUES(?,?,?,?)',(uid,'Account created','Guest registration',datetime.utcnow().isoformat()))
    if status=='approved':
     start=datetime.utcnow(); finish=start+timedelta(days=3)
     c.execute('INSERT INTO premium_trials(user_id,starts_at,ends_at) VALUES(?,?,?)',(uid,start.isoformat(),finish.isoformat()))
    c.commit()
    if status=='approved':
     session.clear(); session['uid']=uid; flash('🎉 Your account has been approved! Now customise your profile.'); return redirect(url_for('customise_profile'))
    flash('Your registration was received and needs additional review or guardian consent before sign-in.','error')
    return redirect(url_for('login'))
   except sqlite3.IntegrityError: flash('That username is already taken. Please choose another.','error')
 return page('Guest registration','''<div class="card"><span class="tag">CREATE YOUR ACCOUNT</span><h2>Join AIR TRAVEL</h2><form method="post"><label>Full name</label><input name="name" maxlength="80" autocomplete="name" required><label>Age</label><input name="age" type="number" min="1" max="120" required><label>Username</label><input name="username" minlength="3" maxlength="24" pattern="[A-Za-z0-9_.-]+" autocomplete="username" required><label>Password (10+ characters)</label><input name="password" type="password" minlength="10" autocomplete="new-password" required><button>Create account</button></form><p class="muted">No email is requested for guest registration. Automated name screening checks for vulgar, hateful, extremist and impersonation-related usernames. If AI moderation is connected on the server, it also reviews unclear names; otherwise, basic checks and owner review are used. Neutral identity terms (including “gay”) are not automatically treated as inappropriate. These checks do not verify identity or real age. Accounts for children under 13 require a parent or guardian consent process before approval.</p></div>''')

def do_login(owner=False):
 if request.method=='POST':
  identity_key=(request.remote_addr or 'unknown') + '|' + (request.form.get('email' if owner else 'username','').strip().lower())
  now=time.time(); attempts=[stamp for stamp in _LOGIN_ATTEMPTS.get(identity_key,[]) if now-stamp < _LOGIN_WINDOW]
  if len(attempts) >= _LOGIN_MAX:
   return page('Sign-in temporarily limited','<div class="card"><h2>Please wait before trying again</h2><p>Too many unsuccessful sign-in attempts. Try again in about 15 minutes.</p></div>'),429
  pw=request.form.get('password','')
  if owner:
   identity=request.form.get('email','').strip().lower()
   u=db().execute('SELECT * FROM users WHERE email=?',(identity,)).fetchone()
  else:
   identity=request.form.get('username','').strip()
   u=db().execute('SELECT * FROM users WHERE username=?',(identity,)).fetchone()
  if u and check_password_hash(u['password_hash'],pw) and ((u['role']=='owner') if owner else (u['role']!='owner')):
   if not owner and u['account_status'] in ('suspended','banned'):
    flash('This account is '+('banned' if u['account_status']=='banned' else 'suspended')+'. Please contact AIR TRAVEL support if you believe this is a mistake.','error')
    return redirect(url_for('login'))
   if not owner and u['approval_status']!='approved':
    flash('This account is awaiting review or required guardian consent.','error')
    return redirect(url_for('login'))
   session.clear(); session['uid']=u['id']; session.permanent=True; record_account_activity(u['id'],'Successful sign-in','Owner sign-in' if owner else 'Member sign-in'); db().commit(); _LOGIN_ATTEMPTS.pop(identity_key,None); flash('Signed in successfully.'); return redirect(url_for('owner_dashboard' if owner else ('customise_profile' if not u['profile_completed'] else 'home')))
  attempts.append(now); _LOGIN_ATTEMPTS[identity_key]=attempts
  flash('Username or password is incorrect, or this account is using the wrong login area.','error')
 return page('Owner login' if owner else 'Guest login','''<div class="hero"><span class="tag">{{'PRIVATE OWNER AREA' if owner else 'MEMBER AREA'}}</span><h1>{{'👑 OWNER LOGIN' if owner else '✈️ GUEST LOGIN'}}</h1><p>{{'AKINOLA AJIDE OWNER · This sign-in is separate from guest accounts.' if owner else 'Sign in with your AIR TRAVEL username.'}}</p></div><div class="card"><h2>{{'Owner-only sign in' if owner else 'Guest sign in'}}</h2><form method="post">{% if owner %}<label>Owner email</label><input name="email" type="email" autocomplete="username" required>{% else %}<label>Username</label><input name="username" autocomplete="username" required>{% endif %}<label>Password</label><input name="password" type="password" autocomplete="current-password" required><button>Sign in</button></form>{% if not owner %}<p>New here? <a href="{{url_for('register')}}">Create an account</a></p>{% endif %}<p class="muted">{{'Owner sign-in stays separate from guest login.' if owner else 'Owner accounts must use the Owner Login page.'}}</p></div>''',owner=owner)

@app.route('/profile/customise',methods=['GET','POST'])
@login_required
def customise_profile():
 u=current_user()
 if u['role']=='owner': return redirect(url_for('owner_dashboard'))
 if request.method=='POST':
  country=request.form.get('country','').strip()[:60]
  bio=request.form.get('bio','').strip()[:240]
  avatar=request.form.get('avatar','').strip()[:8]
  aircraft=request.form.get('aircraft','').strip()[:60]
  background=request.form.get('background','').strip()[:30]
  visibility=request.form.get('visibility','public')
  if visibility not in ('public','private'): visibility='private'
  allowed_avatars={'✈️','🌍','🛩️','🌟','🎮','🧑‍✈️','🛫','🌈','⭐','🧭'}
  if avatar not in allowed_avatars: avatar='✈️'
  allowed_backgrounds={'navy','purple','ocean','sunset'}
  if background not in allowed_backgrounds: background='navy'
  db().execute('UPDATE users SET country=?,bio=?,avatar=?,favourite_aircraft=?,profile_background=?,profile_visibility=?,profile_completed=1 WHERE id=?',(country,bio,avatar,aircraft,background,visibility,u['id']))
  record_account_activity(u['id'],'Profile updated','Member changed their profile settings')
  db().commit(); flash('Your profile has been customised!'); return redirect(url_for('my_profile'))
 return page('Customise your profile','''<div class="hero"><span class="tag">STAGE 36 · MEMBER PROFILES</span><h1>🎨 Customise your profile</h1><p>Make your AIR TRAVEL profile feel like yours. You can change it whenever you like.</p></div>
<div class="card"><form method="post"><label>Choose your avatar</label><select name="avatar">{% for a in ['✈️','🌍','🛩️','🌟','🎮','🧑‍✈️','🛫','🌈','⭐','🧭'] %}<option value="{{a}}" {{'selected' if user['avatar']==a else ''}}>{{a}}</option>{% endfor %}</select>
<label>Favourite aircraft (optional)</label><input name="aircraft" maxlength="60" value="{{user['favourite_aircraft'] or ''}}" placeholder="e.g. Boeing 787">
<label>Country (optional)</label><input name="country" maxlength="60" value="{{user['country'] or ''}}" placeholder="Country only — never your address">
<label>Profile background</label><select name="background">{% for key,label in [('navy','Aviation Navy'),('purple','Purple Sky'),('ocean','Ocean Blue'),('sunset','Sunset')] %}<option value="{{key}}" {{'selected' if user['profile_background']==key else ''}}>{{label}}</option>{% endfor %}</select>
<label>Short bio (optional, max 240 characters)</label><textarea name="bio" maxlength="240" placeholder="Share your aviation interests or favourite games">{{user['bio'] or ''}}</textarea>
<label>Who can view your profile?</label><select name="visibility"><option value="public" {{'selected' if user['profile_visibility']!='private' else ''}}>Public — other members can view it</option><option value="private" {{'selected' if user['profile_visibility']=='private' else ''}}>Private — only you and Owner HQ can view it</option></select>
<button>Save profile</button> <a class="btn alt" href="{{url_for('my_profile')}}">Preview profile</a></form>
<p class="muted">For your safety, don't add your phone number, home address, school, daily routine or other private information. Profile photos/uploads are not enabled in this stage.</p></div>''', user=u)

@app.route('/profile')
@login_required
def my_profile():
 u=current_user()
 if u['role']=='owner': return redirect(url_for('owner_dashboard'))
 return render_member_profile(u, owner_view=False, own=True)

def render_member_profile(member, owner_view=False, own=False, viewer=None, friendship=False, incoming=False, outgoing=False, blocked=False, blocked_by_me=False):
 return page('Member profile','''<section class="card profile-card"><div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap"><div style="font-size:64px;width:104px;height:104px;display:grid;place-items:center;border-radius:24px;background:{{'#563b83' if member['profile_background']=='purple' else '#07558a' if member['profile_background']=='ocean' else '#7b4c35' if member['profile_background']=='sunset' else '#102d50'}}">{{member['avatar'] or '✈️'}}</div><div><span class="tag">{{'OWNER VIEW' if owner_view else 'MEMBER PROFILE'}}</span><h1 style="margin:8px 0 4px">{{member['name']}}</h1><p class="muted">@{{member['username'] or 'member'}}</p></div></div>
<div class="grid"><div class="card"><b>✈️ Favourite aircraft</b><p>{{member['favourite_aircraft'] or 'Not added yet'}}</p></div><div class="card"><b>🌍 Country</b><p>{{member['country'] or 'Not added'}}</p></div><div class="card"><b>🏅 Achievements</b><p>{{'{:,}'.format(member['exp'])}} EXP balance</p></div></div>
<h3>About me</h3><p style="white-space:pre-wrap">{{member['bio'] or 'This member has not added a bio yet.'}}</p>
{% if own %}<p><a class="btn" href="{{url_for('customise_profile')}}">🎨 Edit my profile</a> <a class="btn alt" href="{{url_for('friends_centre')}}">🤝 My Friends</a></p>{% elif owner_view %}<p class="muted">Private owner view. Account status: {{member['account_status']}} · Experience: {{'Kids World' if member['mode']=='kids' else 'General'}}. This page does not reveal passwords, login tokens or private AI conversations.</p><a class="btn alt" href="{{url_for('owner_member_profiles')}}">← Back to member profiles</a>{% elif viewer and viewer['role']=='member' and viewer['id']!=member['id'] and viewer['mode']=='general' and member['mode']=='general' %}<div class="card"><h3>🤝 Connect</h3>{% if blocked %}<p>Friend actions are unavailable for this account.</p>{% elif friendship %}<p>✓ You are friends.</p><form method="post" action="{{url_for('friend_action',user_id=member['id'])}}"><button class="btn alt" name="action" value="remove">Remove friend</button></form>{% elif incoming %}<p>This member sent you a friend request.</p><form method="post" action="{{url_for('friend_action',user_id=member['id'])}}"><button name="action" value="accept">Accept request</button> <button class="btn alt" name="action" value="decline">Decline</button></form>{% elif outgoing %}<p>Friend request sent.</p><form method="post" action="{{url_for('friend_action',user_id=member['id'])}}"><button class="btn alt" name="action" value="cancel">Cancel request</button></form>{% else %}<form method="post" action="{{url_for('friend_action',user_id=member['id'])}}"><button name="action" value="send">＋ Add friend</button></form>{% endif %}<form method="post" action="{{url_for('friend_action',user_id=member['id'])}}" style="margin-top:10px"><button class="btn alt" name="action" value="{{'unblock' if blocked_by_me else 'block'}}">{{'Unblock member' if blocked_by_me else 'Block member'}}</button></form></div>{% endif %}</section>''', member=member, owner_view=owner_view, own=own, viewer=viewer, friendship=friendship, incoming=incoming, outgoing=outgoing, blocked=blocked, blocked_by_me=blocked_by_me)

@app.route('/member/<username>')
def public_member_profile(username):
 member=db().execute("SELECT * FROM users WHERE username=? AND role='member' AND approval_status='approved' AND account_status='active' AND mode='general'",(username,)).fetchone()
 if not member or member['profile_visibility']!='public': abort(404)
 viewer=current_user(); friendship=incoming=outgoing=blocked=blocked_by_me=False
 if viewer and viewer['role']=='member' and viewer['id']!=member['id']:
  lo,hi=sorted((viewer['id'],member['id']))
  friendship=bool(db().execute('SELECT 1 FROM friendships WHERE user_low=? AND user_high=?',(lo,hi)).fetchone())
  incoming=bool(db().execute("SELECT 1 FROM friend_requests WHERE sender_id=? AND recipient_id=? AND status='pending'",(member['id'],viewer['id'])).fetchone())
  outgoing=bool(db().execute("SELECT 1 FROM friend_requests WHERE sender_id=? AND recipient_id=? AND status='pending'",(viewer['id'],member['id'])).fetchone())
  blocked_by_me=bool(db().execute('SELECT 1 FROM member_blocks WHERE blocker_id=? AND blocked_id=?',(viewer['id'],member['id'])).fetchone())
  blocked=blocked_by_me or bool(db().execute('SELECT 1 FROM member_blocks WHERE blocker_id=? AND blocked_id=?',(member['id'],viewer['id'])).fetchone())
 return render_member_profile(member, owner_view=False, own=False, viewer=viewer, friendship=friendship, incoming=incoming, outgoing=outgoing, blocked=blocked, blocked_by_me=blocked_by_me)

@app.route('/friends')
@login_required
def friends_centre():
 u=current_user()
 if not u or u['role']!='member': return redirect(url_for('home'))
 if u['mode']=='kids' or session.get('undercover_owner_uid'): return page('Friends','<div class="card"><h1>🌈 Friends</h1><p>Friend requests are not available in Kids World. Ask a parent or guardian for help with online connections.</p><a class="btn" href="{{url_for(\'home\')}}">Back to Kids World</a></div>')
 c=db()
 friends=c.execute("SELECT u.id,u.name,u.username,u.avatar FROM friendships f JOIN users u ON u.id=CASE WHEN f.user_low=? THEN f.user_high ELSE f.user_low END WHERE (f.user_low=? OR f.user_high=?) AND u.account_status='active' AND u.approval_status='approved' ORDER BY u.name COLLATE NOCASE",(u['id'],u['id'],u['id'])).fetchall()
 incoming=c.execute("SELECT r.id,u.id AS user_id,u.name,u.username,u.avatar,r.created_at FROM friend_requests r JOIN users u ON u.id=r.sender_id WHERE r.recipient_id=? AND r.status='pending' ORDER BY r.id DESC",(u['id'],)).fetchall()
 outgoing=c.execute("SELECT r.id,u.id AS user_id,u.name,u.username,u.avatar,r.created_at FROM friend_requests r JOIN users u ON u.id=r.recipient_id WHERE r.sender_id=? AND r.status='pending' ORDER BY r.id DESC",(u['id'],)).fetchall()
 term=request.args.get('q','').strip()[:30]; results=[]
 if term:
  results=c.execute("SELECT id,name,username,avatar FROM users WHERE role='member' AND mode='general' AND approval_status='approved' AND account_status='active' AND profile_visibility='public' AND id<>? AND (username LIKE ? OR name LIKE ?) ORDER BY name COLLATE NOCASE LIMIT 20",(u['id'],f'%{term}%',f'%{term}%')).fetchall()
 return page('Friends & Requests',r'''<section class="hero"><span class="tag">MEMBER COMMUNITY</span><h1>🤝 Friends & Friend Requests</h1><p>Find members, send requests and manage your connections. AIR TRAVEL does not enable private messaging in this stage.</p></section>
<div class="card"><h2>🔎 Find members</h2><form method="get"><input name="q" maxlength="30" value="{{term}}" placeholder="Search by name or username"><button>Search</button></form>{% for m in results %}<p>{{m['avatar'] or '✈️'}} <b>{{m['name']}}</b> · @{{m['username']}} <a class="btn alt" href="{{url_for('public_member_profile',username=m['username'])}}">View profile</a></p>{% else %}{% if term %}<p>No public profiles matched that search.</p>{% endif %}{% endfor %}</div>
<div class="grid"><div class="card"><h2>📨 Incoming requests</h2>{% for m in incoming %}<p>{{m['avatar'] or '✈️'}} <b>{{m['name']}}</b> · @{{m['username']}}</p><form method="post" action="{{url_for('friend_action',user_id=m['user_id'])}}"><button name="action" value="accept">Accept</button> <button class="btn alt" name="action" value="decline">Decline</button></form>{% else %}<p>No pending requests.</p>{% endfor %}</div><div class="card"><h2>📤 Sent requests</h2>{% for m in outgoing %}<p>{{m['avatar'] or '✈️'}} {{m['name']}} · @{{m['username']}}</p><form method="post" action="{{url_for('friend_action',user_id=m['user_id'])}}"><button class="btn alt" name="action" value="cancel">Cancel request</button></form>{% else %}<p>No sent requests.</p>{% endfor %}</div></div>
<div class="card"><h2>⭐ My friends ({{friends|length}})</h2>{% for m in friends %}<p>{{m['avatar'] or '✈️'}} <b>{{m['name']}}</b> · @{{m['username']}} <a class="btn alt" href="{{url_for('public_member_profile',username=m['username'])}}">View profile</a><form method="post" action="{{url_for('friend_action',user_id=m['id'])}}" style="display:inline"><button class="btn alt" name="action" value="remove">Remove</button></form></p>{% else %}<p>Your friends list is empty. Search for a public member profile to get started.</p>{% endfor %}</div></section>''',friends=friends,incoming=incoming,outgoing=outgoing,results=results,term=term)

@app.route('/friends/<int:user_id>/action',methods=['POST'])
@login_required
def friend_action(user_id):
 me=current_user(); c=db()
 if not me or me['role']!='member' or me['mode']=='kids' or session.get('undercover_owner_uid'): abort(403)
 if user_id==me['id']: abort(400)
 other=c.execute("SELECT id,role,mode,approval_status,account_status FROM users WHERE id=?",(user_id,)).fetchone()
 if not other or other['role']!='member' or other['mode']!='general' or other['approval_status']!='approved' or other['account_status']!='active': abort(404)
 action=request.form.get('action',''); now=datetime.utcnow().isoformat()
 blocked_me=c.execute('SELECT 1 FROM member_blocks WHERE blocker_id=? AND blocked_id=?',(me['id'],user_id)).fetchone()
 blocked_them=c.execute('SELECT 1 FROM member_blocks WHERE blocker_id=? AND blocked_id=?',(user_id,me['id'])).fetchone()
 if action=='block':
  c.execute('INSERT OR IGNORE INTO member_blocks(blocker_id,blocked_id,created_at) VALUES(?,?,?)',(me['id'],user_id,now))
  lo,hi=sorted((me['id'],user_id)); c.execute('DELETE FROM friendships WHERE user_low=? AND user_high=?',(lo,hi)); c.execute("UPDATE friend_requests SET status='cancelled',updated_at=? WHERE ((sender_id=? AND recipient_id=?) OR (sender_id=? AND recipient_id=?)) AND status='pending'",(now,me['id'],user_id,user_id,me['id']))
  flash('Member blocked. They cannot send you friend requests.')
 elif action=='unblock':
  c.execute('DELETE FROM member_blocks WHERE blocker_id=? AND blocked_id=?',(me['id'],user_id)); flash('Member unblocked.')
 elif blocked_me or blocked_them:
  flash('Friend actions are unavailable while either account has blocked the other.','error')
 elif action=='send':
  lo,hi=sorted((me['id'],user_id))
  if c.execute('SELECT 1 FROM friendships WHERE user_low=? AND user_high=?',(lo,hi)).fetchone(): flash('You are already friends.')
  elif c.execute("SELECT 1 FROM friend_requests WHERE sender_id=? AND recipient_id=? AND status='pending'",(user_id,me['id'])).fetchone():
   c.execute('INSERT OR IGNORE INTO friendships(user_low,user_high,created_at) VALUES(?,?,?)',(lo,hi,now)); c.execute("UPDATE friend_requests SET status='accepted',updated_at=? WHERE sender_id=? AND recipient_id=? AND status='pending'",(now,user_id,me['id'])); flash('Friend request accepted. You are now friends!')
  else:
   c.execute("INSERT INTO friend_requests(sender_id,recipient_id,status,created_at,updated_at) VALUES(?,?,'pending',?,?) ON CONFLICT(sender_id,recipient_id) DO UPDATE SET status='pending',created_at=excluded.created_at,updated_at=excluded.updated_at",(me['id'],user_id,now,now)); flash('Friend request sent.')
 elif action=='accept':
  cur=c.execute("UPDATE friend_requests SET status='accepted',updated_at=? WHERE sender_id=? AND recipient_id=? AND status='pending'",(now,user_id,me['id']))
  if cur.rowcount:
   lo,hi=sorted((me['id'],user_id)); c.execute('INSERT OR IGNORE INTO friendships(user_low,user_high,created_at) VALUES(?,?,?)',(lo,hi,now)); flash('Friend request accepted!')
  else: flash('That request is no longer pending.','error')
 elif action=='decline':
  c.execute("UPDATE friend_requests SET status='declined',updated_at=? WHERE sender_id=? AND recipient_id=? AND status='pending'",(now,user_id,me['id'])); flash('Friend request declined.')
 elif action=='cancel':
  c.execute("UPDATE friend_requests SET status='cancelled',updated_at=? WHERE sender_id=? AND recipient_id=? AND status='pending'",(now,me['id'],user_id)); flash('Friend request cancelled.')
 elif action=='remove':
  lo,hi=sorted((me['id'],user_id)); c.execute('DELETE FROM friendships WHERE user_low=? AND user_high=?',(lo,hi)); flash('Member removed from your friends list.')
 else: abort(400)
 c.commit(); return redirect(request.referrer or url_for('friends_centre'))

@app.route('/owner/member-profiles')
@owner_required
def owner_member_profiles():
 members=db().execute("SELECT id,name,username,avatar,bio,profile_visibility,profile_background,mode,account_status FROM users WHERE role='member' ORDER BY name COLLATE NOCASE LIMIT 300").fetchall()
 return page('Member Profile Directory','''<section class="hero"><span class="tag">PRIVATE OWNER HQ</span><h1>👥 Member Profile Directory</h1><p>View member profile details for administration. Respect members' privacy and use profile information only for AIR TRAVEL safety and support.</p><a class="btn alt" href="{{url_for('owner_dashboard')}}">← Owner HQ</a></section><div class="grid">{% for m in members %}<div class="card"><div style="font-size:38px">{{m['avatar'] or '✈️'}}</div><h3>{{m['name']}}</h3><p>@{{m['username'] or 'legacy'}} · {{m['mode']|title}}</p><p class="muted">{{'Private profile' if m['profile_visibility']=='private' else (m['bio'] or 'No bio added')}}</p><span class="tag">{{m['account_status']|upper}}</span><p><a class="btn" href="{{url_for('owner_member_profile',user_id=m['id'])}}">View profile</a></p></div>{% else %}<div class="card">No member profiles yet.</div>{% endfor %}</div>''',members=members)

@app.route('/owner/member-profile/<int:user_id>')
@owner_required
def owner_member_profile(user_id):
 member=db().execute("SELECT * FROM users WHERE id=? AND role='member'",(user_id,)).fetchone()
 if not member: abort(404)
 return render_member_profile(member, owner_view=True, own=False)

@app.route('/login',methods=['GET','POST'])
def login(): return do_login(False)
@app.route('/owner-login',methods=['GET','POST'])
def owner_login(): return do_login(True)
@app.route('/logout')
def logout():
 u=current_user()
 if u:
  record_account_activity(u['id'],'Signed out','Account sign-out'); db().commit()
 session.clear(); flash('You have been signed out.'); return redirect(url_for('home'))
@app.route('/owner/undercover')
@owner_required
def undercover_mode():
    # Only approved, active member accounts are eligible. Never expose email,
    # age, passwords, or other private account fields in the chooser.
    guests=db().execute("SELECT id,name,username,mode,exp FROM users WHERE role='member' AND approval_status='approved' AND account_status='active' ORDER BY name COLLATE NOCASE, username COLLATE NOCASE").fetchall()
    return page('Owner Undercover Mode','''<section class="undercover-panel">
<span class="tag">OWNER HQ · PRIVATE TESTING TOOL</span>
<h1>🕵️ Owner Undercover Mode</h1>
<p>Choose an approved, active member account to experience AIR TRAVEL exactly through that member's General or Kids World account.</p>
<div class="undercover-steps">
 <div class="undercover-step"><b>1 · Choose a member</b><span>Pick an active, approved member account.</span></div>
 <div class="undercover-step"><b>2 · Test their experience</b><span>Explore the app using their saved account and experience mode.</span></div>
 <div class="undercover-step"><b>3 · Return to Owner HQ</b><span>Use the always-visible gold banner to safely return.</span></div>
</div>
<div class="undercover-warning"><b>Important:</b> This is the real selected member account, not a copy. Any profile changes, EXP purchases, game results, posts, or other actions you save while undercover will affect that member's account. Do not change their password or private profile information while testing.</div>
{% if guests %}
<form method="post" action="{{url_for('undercover_start')}}">
 <label for="undercoverMember">Select approved active member</label>
 <select id="undercoverMember" name="user_id" required>
  <option value="">Choose a member account…</option>
  {% for m in guests %}
   <option value="{{m['id']}}">{{m['name']}} · @{{m['username'] or 'member'}} · {{'Kids World' if m['mode']=='kids' else 'General'}} · {{'{:,}'.format(m['exp'])}} EXP</option>
  {% endfor %}
 </select>
 <label class="undercover-confirm"><input type="checkbox" name="confirm_real_account" value="yes" required><span>I understand that this opens the selected member's real account and saved actions will affect it.</span></label>
 <button type="submit">🕵️ Enter as Selected Member</button>
</form>
{% else %}
<div class="notice">There are no approved, active member accounts available yet. Create a separate account through Guest Sign Up and complete the approval process first.</div>
{% endif %}
<p class="muted">Only Owner HQ can start Undercover Mode. While it is active, owner-only pages and controls remain unavailable. The return banner stays visible, including in Kids World.</p>
</section>''',guests=guests)

@app.route('/owner/undercover/start',methods=['POST'])
@owner_required
def undercover_start():
    owner=current_user()
    if request.form.get('confirm_real_account') != 'yes':
        flash('Please confirm that you understand this is the selected member’s real account.','error')
        return redirect(url_for('undercover_mode'))
    try:
        uid=int(request.form.get('user_id','0'))
    except (TypeError,ValueError):
        uid=0
    c=db()
    try:
        c.execute('BEGIN IMMEDIATE')
        guest=c.execute("SELECT id,name,username,mode,exp FROM users WHERE id=? AND role='member' AND approval_status='approved' AND account_status='active'",(uid,)).fetchone()
        if not guest:
            c.rollback()
            flash('That account is not an approved, active member. Choose another member.','error')
            return redirect(url_for('undercover_mode'))
        member_label='@'+(guest['username'] or guest['name'])
        member_mode='Kids World' if guest['mode']=='kids' else 'General'
        now=datetime.utcnow().isoformat()
        details=f"Entered Undercover Mode as {member_label} ({member_mode})."
        c.execute('INSERT INTO owner_audit_logs(owner_id,action,target_user_id,details,created_at) VALUES(?,?,?,?,?)',
                  (owner['id'],'undercover_started',uid,details,now))
        c.commit()
    except sqlite3.Error:
        c.rollback()
        app.logger.exception('Unable to start Owner Undercover Mode')
        flash('Undercover Mode could not be started. No member account was changed.','error')
        return redirect(url_for('undercover_mode'))

    # Replace the active owner identity with the selected member identity,
    # while retaining only the authenticated owner's return reference.
    owner_id=owner['id']
    session.clear()
    session['uid']=uid
    session['undercover_owner_uid']=owner_id
    session['undercover_target_uid']=uid
    session['undercover_member_label']=member_label
    session['undercover_member_mode']=member_mode
    session['undercover_started_at']=now
    session['csrf_token']=secrets.token_urlsafe(32)
    session.permanent=True
    flash(f'Undercover Mode is active. You are viewing AIR TRAVEL as {member_label} ({member_mode}).')
    return redirect(url_for('home'))

@app.route('/owner/undercover/return',methods=['GET','POST'])
def undercover_return():
    # Deliberately does not use @login_required: if the selected member account
    # is suspended or removed during testing, the owner must still be able to return.
    owner_id=session.get('undercover_owner_uid')
    if not owner_id:
        flash('You are not in Undercover Mode.','error')
        return redirect(url_for('home'))
    c=db()
    owner=c.execute("SELECT id FROM users WHERE id=? AND role='owner'",(owner_id,)).fetchone()
    if not owner:
        session.clear()
        flash('The original owner session is no longer available. Please sign in again.','error')
        return redirect(url_for('owner_login'))

    target_id=session.get('undercover_target_uid') or session.get('uid')
    details='Returned to Owner HQ from Undercover Mode.'
    try:
        c.execute('INSERT INTO owner_audit_logs(owner_id,action,target_user_id,details,created_at) VALUES(?,?,?,?,?)',
                  (owner_id,'undercover_returned',target_id,details,datetime.utcnow().isoformat()))
        c.commit()
    except sqlite3.Error:
        c.rollback()
        app.logger.exception('Unable to record Undercover Mode return')
        # Restoring the authenticated owner remains more important than logging.

    session.clear()
    session['uid']=owner_id
    session['csrf_token']=secrets.token_urlsafe(32)
    session.permanent=True
    flash('Welcome back! You have safely returned to Owner HQ.')
    return redirect(url_for('owner_dashboard'))

@app.route('/security-centre',methods=['GET','POST'])
@login_required
def security_centre():
 u=current_user()
 if u['role']=='owner': return redirect(url_for('owner_security_centre'))
 c=db()
 if request.method=='POST':
  action=request.form.get('action','')
  if action=='report':
   category=request.form.get('category','').strip()
   subject=request.form.get('subject','').strip()[:100]
   details=request.form.get('details','').strip()[:1500]
   if category not in {'Bug or technical issue','Account security','Community safety','Other'} or len(subject)<4 or len(details)<10:
    flash('Choose a report category and enter a short subject and details (at least 10 characters).','error')
   else:
    c.execute('INSERT INTO support_reports(user_id,category,subject,details,created_at) VALUES(?,?,?,?,?)',(u['id'],category,subject,details,datetime.utcnow().isoformat()))
    record_account_activity(u['id'],'Support report submitted',category+': '+subject)
    c.commit(); flash('Your report has been sent to the AIR TRAVEL review queue.')
  elif action=='password':
   current=request.form.get('current_password','')
   new=request.form.get('new_password','')
   confirm=request.form.get('confirm_password','')
   fresh=c.execute('SELECT password_hash FROM users WHERE id=?',(u['id'],)).fetchone()
   if not check_password_hash(fresh['password_hash'],current):
    flash('Your current password was not correct.','error')
   elif len(new)<10 or new!=confirm:
    flash('The new password must be at least 10 characters and both entries must match.','error')
   elif check_password_hash(fresh['password_hash'],new):
    flash('Choose a new password that is different from your current one.','error')
   else:
    c.execute('UPDATE users SET password_hash=? WHERE id=?',(generate_password_hash(new),u['id']))
    record_account_activity(u['id'],'Password changed','Password updated from Security Centre')
    c.commit(); flash('Password updated successfully. Keep it private and do not reuse it on other sites.')
  return redirect(url_for('security_centre'))
 activity=c.execute('SELECT event,details,created_at FROM account_activity WHERE user_id=? ORDER BY id DESC LIMIT 25',(u['id'],)).fetchall()
 reports=c.execute('SELECT category,subject,status,created_at FROM support_reports WHERE user_id=? ORDER BY id DESC LIMIT 10',(u['id'],)).fetchall()
 return page('Security Centre','''<section class="hero"><span class="tag">STAGE 31 · ACCOUNT SAFETY</span><h1>🔐 Security & Safety Centre</h1><p>Review important account activity, update your password and contact the AIR TRAVEL review team.</p></section>
<div class="grid"><div class="card"><h2>🔑 Change password</h2><p>Use a unique password with at least 10 characters. Never share it with anyone, including people claiming to be support.</p><form method="post"><input type="hidden" name="action" value="password"><label>Current password</label><input type="password" name="current_password" autocomplete="current-password" required><label>New password</label><input type="password" name="new_password" minlength="10" autocomplete="new-password" required><label>Confirm new password</label><input type="password" name="confirm_password" minlength="10" autocomplete="new-password" required><button>Update password</button></form></div>
<div class="card"><h2>🛡️ Account safety tips</h2><ul><li>Never share your password or sign-in codes.</li><li>Use a different password from your other accounts.</li><li>Do not post your address, school, phone number or private details.</li><li>Sign out on shared devices when finished.</li><li>Tell a trusted adult if someone pressures or threatens you online.</li></ul><p class="muted">This local project does not yet provide multi-factor authentication or a device-by-device session manager.</p></div></div>
<div class="card"><h2>📨 Report a problem or safety concern</h2><form method="post"><input type="hidden" name="action" value="report"><label>Category</label><select name="category" required><option value="">Choose a category</option><option>Bug or technical issue</option><option>Account security</option><option>Community safety</option><option>Other</option></select><label>Short subject</label><input name="subject" maxlength="100" minlength="4" required><label>Details</label><textarea name="details" maxlength="1500" minlength="10" required placeholder="Explain what happened. Do not include passwords or private contact details."></textarea><button>Send report</button></form></div>
<div class="card"><h2>🕘 Recent account activity</h2>{% for a in activity %}<p style="border-bottom:1px solid #245078;padding:8px 0"><b>{{a['event']}}</b><br><small>{{a['details']}} · {{a['created_at'][:16].replace('T',' ')}} UTC</small></p>{% else %}<p>No activity has been recorded yet.</p>{% endfor %}</div>
<div class="card"><h2>📋 My reports</h2>{% for r in reports %}<p style="border-bottom:1px solid #245078;padding:8px 0"><b>{{r['subject']}}</b> · {{r['status']|title}}<br><small>{{r['category']}} · {{r['created_at'][:16]}} UTC</small></p>{% else %}<p>You have not submitted a report yet.</p>{% endfor %}</div></section>''',activity=activity,reports=reports)

@app.route('/owner/member/<int:user_id>/ban', methods=['POST'])
@owner_required
def owner_ban_member(user_id):
 c=db()
 action=(request.form.get('action') or '').strip()
 reason=(request.form.get('reason') or '').strip()[:300]
 member=c.execute("SELECT id,name,account_status FROM users WHERE id=? AND role='member'",(user_id,)).fetchone()
 if not member:
  flash('Only a member account can be banned or restored. Owner accounts are protected.','error')
  return redirect(url_for('owner_security_centre'))
 if len(reason)<10:
  flash('Please provide a clear reason of at least 10 characters.','error')
  return redirect(url_for('owner_security_centre'))
 if action=='ban':
  if member['account_status']=='banned':
   flash('This member is already banned.','error')
  else:
   c.execute("UPDATE users SET account_status='banned' WHERE id=? AND role='member'",(user_id,))
   c.execute("INSERT INTO account_moderation_history(target_user_id,owner_id,action,reason,created_at) VALUES(?,?,?,?,?)",(user_id,current_user()['id'],'banned',reason,datetime.utcnow().isoformat()))
   audit_owner_action('Member banned',user_id,reason)
   c.commit(); flash(member['name']+' has been banned and cannot sign in or continue using member features.')
 elif action=='unban':
  if member['account_status']!='banned':
   flash('This account is not currently banned.','error')
  else:
   c.execute("UPDATE users SET account_status='active' WHERE id=? AND role='member'",(user_id,))
   c.execute("INSERT INTO account_moderation_history(target_user_id,owner_id,action,reason,created_at) VALUES(?,?,?,?,?)",(user_id,current_user()['id'],'unbanned',reason,datetime.utcnow().isoformat()))
   audit_owner_action('Member unbanned',user_id,reason)
   c.commit(); flash(member['name']+' has been unbanned and restored to active status.')
 else:
  flash('Choose a valid moderation action.','error')
 return redirect(url_for('owner_security_centre'))

@app.route('/owner/name-review',methods=['GET','POST'])
@owner_required
def owner_name_review():
 c=db()
 if request.method=='POST':
  try: rid=int(request.form.get('review_id','0'))
  except ValueError: rid=0
  action=request.form.get('action','')
  item=c.execute("SELECT q.*,u.age FROM username_review_queue q JOIN users u ON u.id=q.user_id WHERE q.id=? AND q.status='pending' AND u.role='member'",(rid,)).fetchone()
  if not item or action not in {'approve','reject'}:
   flash('That username review could not be updated.','error')
  elif action=='approve' and (item['age'] or 0)<13:
   flash('This account still requires the appropriate guardian-consent process before approval.','error')
  else:
   status='approved' if action=='approve' else 'rejected'
   c.execute('UPDATE username_review_queue SET status=?,reviewed_at=?,reviewed_by=? WHERE id=?',(status,datetime.utcnow().isoformat(),current_user()['id'],rid))
   c.execute('UPDATE users SET approval_status=? WHERE id=?',('approved' if action=='approve' else 'rejected',item['user_id']))
   audit_owner_action('Username '+status,item['user_id'],'@'+item['username']+' · '+item['reason'])
   c.commit(); flash('Username approved. Member can sign in.' if action=='approve' else 'Username rejected. This account cannot sign in.')
  return redirect(url_for('owner_name_review'))
 pending=c.execute("SELECT q.*,u.name,u.age FROM username_review_queue q JOIN users u ON u.id=q.user_id WHERE q.status='pending' ORDER BY q.id ASC").fetchall()
 history=c.execute("SELECT q.*,u.name FROM username_review_queue q JOIN users u ON u.id=q.user_id WHERE q.status!='pending' ORDER BY q.id DESC LIMIT 50").fetchall()
 return page('Owner Name Review', '''<section class="hero"><span class="tag">STAGE 34 · AI-ASSISTED NAME SAFETY</span><h1>📝 Owner Name Review Panel</h1><p>Review usernames flagged by automatic screening. AI suggestions are not final decisions: check context and apply community rules fairly.</p><p><a class="btn alt" href="{{url_for('owner_dashboard')}}">← Owner HQ</a> <a class="btn alt" href="{{url_for('owner_security_centre')}}">Security Centre</a></p><div class="balance">{{pending|length}} usernames awaiting review</div></section><div class="card"><h2>Pending username reviews</h2>{% for q in pending %}<article style="border-top:1px solid #245078;padding:14px 0"><h3>@{{q['username']}}</h3><p>Applicant: {{q['name']}} · Age: {{q['age'] or 'not supplied'}}<br>Screening: <b>{{q['decision']|title}}</b> · Method: {{q['method']|title}}<br>Reason: {{q['reason']}}<br><small>{{q['created_at'][:16]}} UTC</small></p><p class="muted">Approve only if the name follows the published community rules. If unsure, leave it pending while you investigate.</p><form method="post" class="inline"><input type="hidden" name="review_id" value="{{q['id']}}"><button name="action" value="approve">Approve username</button><button class="btn alt" name="action" value="reject" onclick="return confirm('Reject this username and prevent this account from signing in?')">Reject username</button></form></article>{% else %}<p>No usernames are waiting for review.</p>{% endfor %}</div><div class="card"><h2>Recent review decisions</h2>{% for q in history %}<p style="border-top:1px solid #245078;padding:9px 0"><b>@{{q['username']}}</b> · {{q['status']|title}}<br>{{q['reason']}}<br><small>{{q['reviewed_at'][:16] if q['reviewed_at'] else q['created_at'][:16]}} UTC</small></p>{% else %}<p>No decisions recorded yet.</p>{% endfor %}</div>''',pending=pending,history=history)

@app.route('/owner/security-centre',methods=['GET','POST'])
@owner_required
def owner_security_centre():
 c=db()
 if request.method=='POST':
  try: rid=int(request.form.get('report_id','0'))
  except ValueError: rid=0
  action=request.form.get('action','')
  report=c.execute("SELECT id FROM support_reports WHERE id=? AND status='open'",(rid,)).fetchone()
  if report and action in {'reviewed','closed'}:
   c.execute('UPDATE support_reports SET status=?,reviewed_at=?,reviewed_by=? WHERE id=?',('reviewed' if action=='reviewed' else 'closed',datetime.utcnow().isoformat(),current_user()['id'],rid))
   audit_owner_action('Support report '+action,None,'Report #'+str(rid)); c.commit(); flash('Report status updated.')
  else: flash('That report could not be updated.','error')
  return redirect(url_for('owner_security_centre'))
 reports=c.execute('''SELECT r.*,u.name AS member_name,u.username FROM support_reports r JOIN users u ON u.id=r.user_id ORDER BY CASE WHEN r.status='open' THEN 0 ELSE 1 END,r.id DESC LIMIT 100''').fetchall()
 members=c.execute("SELECT id,name,username,account_status,approval_status FROM users WHERE role='member' ORDER BY id DESC LIMIT 200").fetchall()
 moderation=c.execute('''SELECT h.*,u.name AS member_name,o.name AS owner_name FROM account_moderation_history h JOIN users u ON u.id=h.target_user_id JOIN users o ON o.id=h.owner_id ORDER BY h.id DESC LIMIT 50''').fetchall()
 banned_count=c.execute("SELECT COUNT(*) FROM users WHERE role='member' AND account_status='banned'").fetchone()[0]
 open_count=c.execute("SELECT COUNT(*) FROM support_reports WHERE status='open'").fetchone()[0]
 return page('Owner Security Centre','''<section class="hero"><span class="tag">PRIVATE OWNER HQ · STAGE 31</span><h1>🛡️ Security & Safety Review</h1><p>Review member reports, check their category and update report status. Avoid asking members to send passwords or sensitive personal information.</p><p><a class="btn alt" href="{{url_for('owner_dashboard')}}">← Owner HQ</a></p><div class="balance">{{open_count}} open reports</div></section><div class="card"><h2>🚫 Member account bans</h2><p class="muted">Use this only after reviewing credible evidence or a report. Suspicious-looking behaviour is a reason to investigate, not proof by itself. Record a clear reason; never ban based only on rumours or disagreement. Bans block member sign-in and active member sessions. Owner accounts cannot be banned here.</p><p class="balance">{{banned_count}} banned member accounts</p>{% for m in members %}<div style="border-top:1px solid #245078;padding:12px 0"><b>{{m['name']}}</b> · @{{m['username'] or 'member'}} · <span class="tag">{{m['account_status']|upper}}</span>{% if m['account_status']=='banned' %}<form method="post" action="{{url_for('owner_ban_member',user_id=m['id'])}}"><input type="hidden" name="action" value="unban"><label>Reason for restoring access</label><input name="reason" minlength="10" maxlength="300" placeholder="Explain why access is being restored" required><button class="btn alt" type="submit">Unban &amp; restore account</button></form>{% else %}<form method="post" action="{{url_for('owner_ban_member',user_id=m['id'])}}" onsubmit="return confirm('Ban this member account? They will lose access until you unban them.');"><input type="hidden" name="action" value="ban"><label>Reason for ban</label><input name="reason" minlength="10" maxlength="300" placeholder="Describe the evidence or safety concern" required><button type="submit" style="background:#a52d46">Ban member account</button></form>{% endif %}</div>{% else %}<p>No member accounts yet.</p>{% endfor %}</div><div class="card"><h2>🧾 Ban and unban history</h2>{% for h in moderation %}<p style="border-top:1px solid #245078;padding:9px 0"><b>{{h['action']|title}}</b> · {{h['member_name']}}<br>{{h['reason']}}<br><small>{{h['created_at'][:16]}} UTC · Action by {{h['owner_name']}}</small></p>{% else %}<p>No ban actions recorded yet.</p>{% endfor %}</div><div class="card"><h2>📨 Member reports</h2>{% for r in reports %}<article style="border-top:1px solid #245078;padding:14px 0"><div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:space-between"><b>#{{r['id']}} · {{r['subject']}}</b><span class="tag">{{r['status']|title}}</span></div><p><b>From:</b> {{r['member_name']}} · @{{r['username'] or 'member'}}<br><b>Category:</b> {{r['category']}}<br><b>Submitted:</b> {{r['created_at'][:16]}} UTC</p><p style="white-space:pre-wrap">{{r['details']}}</p>{% if r['status']=='open' %}<form method="post"><input type="hidden" name="report_id" value="{{r['id']}}"><button name="action" value="reviewed">Mark reviewed</button> <button class="btn alt" name="action" value="closed">Close report</button></form>{% endif %}</article>{% else %}<p>No reports have been submitted.</p>{% endfor %}</div>''',reports=reports,open_count=open_count,members=members,moderation=moderation,banned_count=banned_count)

@app.route('/owner/abuse-panel')
@owner_required
def owner_abuse_panel():
 c=db()
 post_reports=c.execute("""SELECT r.*,p.body AS post_body,p.moderation_status,
  reporter.name AS reporter_name,author.id AS author_id,author.name AS author_name,
  author.username AS author_username,author.account_status AS author_status
  FROM post_reports r JOIN posts p ON p.id=r.post_id
  JOIN users reporter ON reporter.id=r.reporter_id
  JOIN users author ON author.id=p.user_id
  WHERE r.status='open' ORDER BY r.id DESC LIMIT 100""").fetchall()
 support_reports=c.execute("""SELECT r.*,u.name AS member_name,u.username
  FROM support_reports r JOIN users u ON u.id=r.user_id
  WHERE r.status='open' ORDER BY r.id DESC LIMIT 100""").fetchall()
 flagged_names=c.execute("""SELECT q.*,u.name AS member_name,u.username AS current_username
  FROM username_review_queue q JOIN users u ON u.id=q.user_id
  WHERE q.status='pending' ORDER BY q.id ASC LIMIT 100""").fetchall()
 stats={
  'posts':c.execute("SELECT COUNT(*) FROM post_reports WHERE status='open'").fetchone()[0],
  'support':c.execute("SELECT COUNT(*) FROM support_reports WHERE status='open'").fetchone()[0],
  'names':c.execute("SELECT COUNT(*) FROM username_review_queue WHERE status='pending'").fetchone()[0],
  'banned':c.execute("SELECT COUNT(*) FROM users WHERE role='member' AND account_status='banned'").fetchone()[0],
 }
 return page('Abuse Administration Panel',"""
 <section class="hero"><span class="tag">PRIVATE OWNER HQ · STAGE 35</span><h1>🛡️ Abuse Administration Panel</h1>
 <p>One place to review community abuse reports, member safety reports and flagged usernames. Review the evidence and context before taking action; a report is an allegation, not proof.</p>
 <p><a class="btn alt" href="{{url_for('owner_dashboard')}}">← Owner HQ</a> <a class="btn alt" href="{{url_for('owner_security_centre')}}">Security &amp; account bans</a> <a class="btn alt" href="{{url_for('owner_name_review')}}">Username review</a></p></section>
 <div class="grid">
 <div class="card"><h3>🚩 Community reports</h3><div class="balance">{{stats.posts}}</div><small>Open post reports</small></div>
 <div class="card"><h3>📨 Safety reports</h3><div class="balance">{{stats.support}}</div><small>Open member-submitted reports</small></div>
 <div class="card"><h3>📝 Flagged names</h3><div class="balance">{{stats.names}}</div><small>Names awaiting review</small></div>
 <div class="card"><h3>🚫 Banned accounts</h3><div class="balance">{{stats.banned}}</div><small>Currently banned members</small></div></div>
 <div class="card"><h2>🚩 Community abuse reports</h2><p class="muted">Review the reported post and reporter's reason. Hide content while reviewing if needed; delete only when appropriate. You can also open the ban form for the post author.</p>
 {% for r in post_reports %}<article style="border-top:1px solid #245078;padding:14px 0"><b>Report #{{r['id']}} · {{r['reason']|title}}</b> <span class="tag">{{r['author_status']|upper}}</span>
 <p><b>Reported post:</b></p><p style="white-space:pre-wrap;background:#101d35;padding:12px;border-radius:10px">{{r['post_body']}}</p>
 <small>Reported by {{r['reporter_name']}} · Post author {{r['author_name']}} (@{{r['author_username'] or 'member'}}) · {{r['created_at'][:16]}}</small>
 <form class="inline" method="post" action="{{url_for('moderate_report',report_id=r['id'])}}"><button name="action" value="hide">Hide post</button> <button class="btn alt" name="action" value="dismiss">Dismiss report</button> <button class="btn alt" name="action" value="delete" onclick="return confirm('Permanently delete this post and its reports?')">Delete post</button></form>
 {% if r['author_status']!='banned' %}<details><summary class="btn alt" style="display:inline-block;cursor:pointer">Review account ban option</summary><form method="post" action="{{url_for('owner_ban_member',user_id=r['author_id'])}}"><input type="hidden" name="action" value="ban"><label>Evidence-based reason (at least 10 characters)</label><input name="reason" minlength="10" maxlength="300" placeholder="Explain the rule violation and evidence" required><button type="submit" style="background:#a52d46" onclick="return confirm('Ban this member after reviewing the evidence?')">Ban member</button></form></details>{% endif %}</article>
 {% else %}<p>No open community reports.</p>{% endfor %}</div>
 <div class="card"><h2>📨 Member safety and abuse reports</h2>
 {% for r in support_reports %}<article style="border-top:1px solid #245078;padding:14px 0"><b>#{{r['id']}} · {{r['subject']}}</b> <span class="tag">{{r['category']}}</span><p>From {{r['member_name']}} (@{{r['username'] or 'member'}}) · {{r['created_at'][:16]}}</p><p style="white-space:pre-wrap">{{r['details']}}</p><form method="post" action="{{url_for('owner_security_centre')}}"><input type="hidden" name="report_id" value="{{r['id']}}"><button name="action" value="reviewed">Mark reviewed</button> <button class="btn alt" name="action" value="closed">Close report</button></form></article>
 {% else %}<p>No open member safety reports.</p>{% endfor %}</div>
 <div class="card"><h2>📝 Names awaiting moderation</h2>{% for q in flagged_names %}<p style="border-top:1px solid #245078;padding:10px 0"><b>{{q['current_username'] or q['username']}}</b> · {{q['reason']}} · {{q['method']}}<br><small>Account: {{q['member_name']}}</small></p>{% else %}<p>No flagged usernames waiting for review.</p>{% endfor %}<a class="btn alt" href="{{url_for('owner_name_review')}}">Open full name review queue</a></div>
 <div class="card"><h3>⚖️ Fair moderation rules</h3><ul><li>Check the full context before deciding.</li><li>Do not ban based only on rumours, disagreement, identity or one unverified report.</li><li>Use hide/review while checking a concern; reserve permanent deletion or bans for clear rule violations.</li><li>Never request or expose passwords, home addresses, school details or other private information.</li><li>Keep moderation actions documented in the Owner audit log.</li></ul></div>
 """,post_reports=post_reports,support_reports=support_reports,flagged_names=flagged_names,stats=stats)

@app.route('/exp-wallet')
@login_required
def exp_wallet():
    u=current_user()
    if u['role']=='owner': return redirect(url_for('owner_dashboard'))
    rows=db().execute('SELECT amount,reason,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 100',(u['id'],)).fetchall()
    earned=db().execute('SELECT COALESCE(SUM(amount),0) n FROM transactions WHERE user_id=? AND amount>0',(u['id'],)).fetchone()['n']
    spent=db().execute('SELECT COALESCE(SUM(-amount),0) n FROM transactions WHERE user_id=? AND amount<0',(u['id'],)).fetchone()['n']
    return page('EXP Wallet','''<section class="hero"><span class="tag">MEMBER WALLET</span><h1>💰 EXP Wallet</h1><p>Your current virtual EXP balance and transaction history.</p><div class="balance">{{'{:,}'.format(user['exp'])}} EXP</div></section><div class="grid"><div class="card"><h3>Total earned</h3><p class="balance">{{'{:,}'.format(earned)}} EXP</p></div><div class="card"><h3>Total spent</h3><p class="balance">{{'{:,}'.format(spent)}} EXP</p></div></div><div class="card"><h2>Transaction history</h2><p class="muted">Purchases appear as negative amounts; rewards appear as positive amounts.</p><table style="width:100%;border-collapse:collapse"><tr><th align="left">Date</th><th align="left">Activity</th><th align="right">EXP</th></tr>{% for r in rows %}<tr style="border-top:1px solid #245078"><td style="padding:10px 4px">{{r['created_at'][:16]}}</td><td>{{r['reason']}}</td><td align="right" style="color:{{'#70e6a0' if r['amount']>0 else '#ff9c9c'}}">{{'+' if r['amount']>0 else ''}}{{'{:,}'.format(r['amount'])}}</td></tr>{% else %}<tr><td colspan="3">No transactions yet.</td></tr>{% endfor %}</table></div>''',rows=rows,earned=earned,spent=spent)

@app.route('/owner')
@owner_required
def owner_dashboard():
 members=db().execute("SELECT id,name,username,age,approval_status,account_status,exp,mode FROM users WHERE role!='owner' ORDER BY id DESC").fetchall(); events=db().execute('SELECT * FROM events ORDER BY id DESC').fetchall(); shop=db().execute('SELECT COALESCE(SUM(cost),0) AS total, COUNT(*) AS sales FROM user_items').fetchone(); logs=db().execute('SELECT l.*,u.name AS target_name FROM owner_audit_logs l LEFT JOIN users u ON u.id=l.target_user_id ORDER BY l.id DESC LIMIT 30').fetchall(); reports=db().execute("SELECT r.*,p.body AS post_body,u.name AS reporter_name,a.name AS author_name FROM post_reports r JOIN posts p ON p.id=r.post_id JOIN users u ON u.id=r.reporter_id JOIN users a ON a.id=p.user_id WHERE r.status='open' ORDER BY r.id DESC LIMIT 50").fetchall(); announcements=db().execute('SELECT * FROM announcements WHERE is_published=1 ORDER BY id DESC LIMIT 30').fetchall()
 return page('Owner HQ','''<div class="hero"><span class="tag">OWNER HQ</span><h1>Control Centre</h1><p>AKINOLA AJIDE OWNER · Full owner dashboard</p><p class="balance">100,000,000,000,000 EXP</p><small>Separate owner privilege display; not a member wallet.</small><p><a class="btn" href="{{url_for('undercover_mode')}}">🕵️ Test as a Member</a> <a class="btn alt" href="{{url_for('owner_security_centre')}}">🛡️ Security &amp; Reports</a> <a class="btn alt" href="{{url_for('owner_abuse_panel')}}">🚩 Abuse Admin Panel</a> <a class="btn alt" href="{{url_for('owner_name_review')}}">📝 Name Review</a> <a class="btn alt" href="{{url_for('owner_member_profiles')}}">👥 Member Profiles</a> <a class="btn alt" href="{{url_for('ai_assistant')}}">🤖 Preview Personal AI</a> <a class="btn alt" href="{{url_for('owner_overview')}}">📊 Open HQ Overview</a> <a class="btn alt" href="{{url_for('owner_event_manager')}}">🗓️ Event Manager</a> <a class="btn alt" href="{{url_for('owner_airline_empire')}}">✈️ Airline Control</a> <a class="btn alt" href="{{url_for('owner_kids_studio')}}">🌈 Kids World Studio</a></p></div><div class="grid"><div class="card"><h3>📢 Announcements</h3><p>Publish an update that appears for all members on the home page and in the Announcements Centre.</p><form method="post" action="{{url_for('publish_announcement')}}"><label>Announcement title</label><input name="title" maxlength="100" placeholder="e.g. Welcome to AIR TRAVEL!" required><label>Message</label><textarea name="body" maxlength="3000" placeholder="Write your announcement for members..." required></textarea><button>📢 Publish announcement</button></form><h4>Published announcements</h4>{% for a in announcements %}<div style="border-top:1px solid #245078;padding:10px 0"><b>{{a['title']}}</b><p>{{a['body']}}</p><small>{{a['created_at'][:16]}}</small><form class="inline" method="post" action="{{url_for('delete_announcement',announcement_id=a['id'])}}"><button class="btn alt" type="submit" onclick="return confirm('Delete this announcement?')">Delete</button></form></div>{% else %}<p>No announcements published yet.</p>{% endfor %}</div><div class="card"><h3>👑 Owner Tribute</h3><p>Manage the public founders page for AKINOLA AJIDE (Owner) and JAYDINE (Co-owner).</p><a class="btn" href="{{url_for('owner_tribute_manage')}}">Manage Owner Tribute</a> <a class="btn alt" href="{{url_for('owner_tribute')}}">View public page</a> <a class="btn alt" href="{{url_for('owner_milestones_manage')}}">Manage Founder Timeline</a></div><div class="card"><h3>Gift Shop EXP earnings</h3><p class="balance">{{'{:,}'.format(shop['total'])}} EXP</p><p>{{shop['sales']}} virtual item purchases recorded.</p><small class="muted">Separate shop total; not cash and not added to the owner's 100-trillion display balance.</small></div><div class="card"><h3>Real-money earnings</h3><p>₦0 recorded in this build.</p><small class="muted">Checkout is not connected, so no payments are collected.</small></div></div><div class="grid"><div class="card"><h3>Award member EXP</h3><form method="post" action="{{url_for('award_exp')}}"><label>Member</label><select name="user_id">{% for m in members %}<option value="{{m['id']}}">{{m['name']}} — @{{m['username'] or 'legacy'}}</option>{% endfor %}</select><label>Amount</label><input name="amount" type="number" min="1" max="100000" required><label>Reason</label><input name="reason" required><button>Award EXP</button></form></div><div class="card"><h3>🗓️ Publish an event</h3><p class="muted">Add a date and category so members can find it in the public Events Centre. Times are Nigeria time (WAT).</p><form method="post" action="{{url_for('add_event')}}"><label>Event title</label><input name="title" maxlength="100" placeholder="Event title" required><label>Category</label><select name="category"><option>Aviation</option><option>Competition</option><option>Community</option><option>Learning</option><option>Entertainment</option><option>Other</option></select><label>Date and time (Nigeria time, optional)</label><input type="datetime-local" name="event_date"><label>Event details</label><textarea name="details" maxlength="1200" placeholder="What will happen? Avoid sharing private member information." required></textarea><button>📢 Publish event</button></form><p><a class="btn alt" href="{{url_for('owner_event_manager')}}">Manage all events</a> <a class="btn alt" href="{{url_for('events_centre')}}">View public Events Centre</a></p></div></div><div class="card"><h3>Registration review</h3>{% for m in members if m['approval_status']!='approved' %}<p>{{m['name']}} · @{{m['username'] or 'legacy'}} · Age {{m['age'] or 'not supplied'}} · {{m['approval_status']}} {% if m['approval_status']=='pending_review' and (m['age'] or 0)>=13 %}<form class="inline" method="post" action="{{url_for('approve_member',user_id=m['id'])}}"><button>Approve account</button></form>{% endif %}</p>{% else %}<p>No accounts awaiting review.</p>{% endfor %}</div><div class="card"><h3>Member management</h3><p class="muted">Suspend an account that needs review, or restore access when the issue is resolved. Suspended members cannot sign in or use member features.</p>{% for m in members %}<div style="border-top:1px solid #245078;padding:12px 0"><b>{{m['name']}}</b> · @{{m['username'] or 'legacy'}}<br>{{'{:,}'.format(m['exp'])}} EXP · {{m['mode']|title}} · {{m['approval_status']}} · <span class="tag">{{m['account_status']|upper}}</span><form class="inline" method="post" action="{{url_for('set_member_status',user_id=m['id'])}}"><input type="hidden" name="status" value="{{'active' if m['account_status']=='suspended' else 'suspended'}}"><input type="hidden" name="reason" value="Owner account review"><button class="btn alt" type="submit">{{'Restore account' if m['account_status']=='suspended' else 'Suspend account'}}</button></form><form method="post" action="{{url_for('set_member_mode',user_id=m['id'])}}" style="display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;margin:6px 0"><select name="mode" style="width:auto;min-width:145px;margin:0"><option value="general" {{'selected' if m['mode']=='general' else ''}}>General</option><option value="kids" {{'selected' if m['mode']=='kids' else ''}}>Kids World</option></select><button class="btn alt" type="submit">Save experience</button></form></div>{% else %}<p>No guest members yet.</p>{% endfor %}</div><div class="card"><h3>🛡️ Community safety review</h3><p class="muted">Review member reports. Hiding a post removes it from the public community board; deleting permanently removes the post and its reports.</p>{% for r in reports %}<div style="border-top:1px solid #245078;padding:12px 0"><b>Report #{{r['id']}} · {{r['reason']}}</b><p>{{r['post_body']}}</p><small>Reported by {{r['reporter_name']}} · Post author {{r['author_name']}} · {{r['created_at'][:16]}}</small><form class="inline" method="post" action="{{url_for('moderate_report',report_id=r['id'])}}"><button name="action" value="hide">Hide post</button><button class="btn alt" name="action" value="dismiss">Dismiss report</button><button class="btn alt" name="action" value="delete" onclick="return confirm('Permanently delete this community post?')">Delete post</button></form></div>{% else %}<p>No open reports. Great!</p>{% endfor %}</div><div class="card"><h3>Owner security audit log</h3><p class="muted">Recent owner actions are recorded here for accountability.</p>{% for log in logs %}<p style="border-top:1px solid #245078;padding:8px 0"><b>{{log['action']}}</b> · {{log['target_name'] or 'System'}} · {{log['details']}}<br><small class="muted">{{log['created_at']}}</small></p>{% else %}<p>No owner actions recorded yet.</p>{% endfor %}</div><div class="card"><h3>Owner events</h3>{% for e in events %}<p><b>{{e['title']}}</b> — {{e['details']}}</p>{% else %}<p>No events yet.</p>{% endfor %}</div>''',members=members,events=events,shop=shop,logs=logs,reports=reports,announcements=announcements)
@app.route('/owner/overview')
@owner_required
def owner_overview():
 c = db()
 def metric(sql, params=()):
  row = c.execute(sql, params).fetchone()
  return int(row[0] or 0)

 # Aggregate-only reporting: this page deliberately avoids exposing member
 # names, ages, usernames, trip notes, application text or message contents.
 member_total = metric("SELECT COUNT(*) FROM users WHERE role!='owner'")
 active_members = metric("SELECT COUNT(*) FROM users WHERE role!='owner' AND account_status='active'")
 suspended_members = metric("SELECT COUNT(*) FROM users WHERE role!='owner' AND account_status='suspended'")
 pending_members = metric("SELECT COUNT(*) FROM users WHERE role!='owner' AND approval_status!='approved'")
 visible_posts = metric("SELECT COUNT(*) FROM posts WHERE moderation_status='visible'")
 open_reports = metric("SELECT COUNT(*) FROM post_reports WHERE status='open'")
 trip_plans = metric('SELECT COUNT(*) FROM trip_plans')
 passport_stamps = metric('SELECT COUNT(*) FROM passport_stamps')
 academy_lessons = metric('SELECT COUNT(*) FROM academy_progress')
 academy_certificates = metric('SELECT COUNT(*) FROM academy_certificates')
 career_challenges = metric('SELECT COUNT(*) FROM career_progress')
 career_applications = metric('SELECT COUNT(*) FROM career_applications')
 virtual_missions = metric('SELECT COUNT(*) FROM aviation_mission_progress')
 published_announcements = metric('SELECT COUNT(*) FROM announcements WHERE is_published=1')
 owner_events = metric('SELECT COUNT(*) FROM events')
 shop_items = metric('SELECT COUNT(*) FROM user_items')
 exp_awarded = metric('SELECT COALESCE(SUM(amount),0) FROM transactions WHERE amount>0')
 cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
 recent_signups = metric("SELECT COUNT(*) FROM users WHERE role!='owner' AND created_at>=?", (cutoff,))
 recent_lessons = metric('SELECT COUNT(*) FROM academy_progress WHERE completed_at>=?', (cutoff,))
 recent_missions = metric('SELECT COUNT(*) FROM aviation_mission_progress WHERE completed_at>=?', (cutoff,))
 activity = c.execute('SELECT action,created_at FROM owner_audit_logs ORDER BY id DESC LIMIT 12').fetchall()

 groups = [
  {'title':'👥 Member overview','items':[
   {'label':'Total guest accounts','value':member_total},
   {'label':'Active accounts','value':active_members},
   {'label':'Suspended accounts','value':suspended_members},
   {'label':'Awaiting review / approval','value':pending_members}]},
  {'title':'🌍 Community & travel','items':[
   {'label':'Visible community posts','value':visible_posts},
   {'label':'Open safety reports','value':open_reports},
   {'label':'Saved trip plans','value':trip_plans},
   {'label':'Passport stamps collected','value':passport_stamps}]},
  {'title':'🎓 Learning & careers','items':[
   {'label':'Academy lessons completed','value':academy_lessons},
   {'label':'Certificates issued','value':academy_certificates},
   {'label':'Career challenges completed','value':career_challenges},
   {'label':'Virtual career applications','value':career_applications}]},
  {'title':'✈️ AIR TRAVEL activity','items':[
   {'label':'Virtual missions completed','value':virtual_missions},
   {'label':'Published announcements','value':published_announcements},
   {'label':'Owner events published','value':owner_events},
   {'label':'Virtual shop purchases','value':shop_items},
   {'label':'EXP awarded (virtual)','value':exp_awarded}]}
 ]
 weekly = [
  {'label':'New member accounts','value':recent_signups},
  {'label':'Academy lessons completed','value':recent_lessons},
  {'label':'Virtual missions completed','value':recent_missions}
 ]
 return page('Owner HQ Overview','''
 <section class="hero">
  <span class="tag">OWNER HQ · STAGE 18</span>
  <h1>📊 Command Dashboard</h1>
  <p>A private, aggregate overview of AIR TRAVEL activity and learning progress.</p>
  <div class="owner-overview-actions">
   <a class="btn" href="{{url_for('owner_dashboard')}}">← Back to Owner HQ</a>
   <a class="btn alt" href="{{url_for('owner_overview')}}">↻ Refresh figures</a>
  </div>
 </section>
 <div class="owner-metric-groups">
  {% for group in groups %}
   <section class="owner-metric-group"><h2>{{group['title']}}</h2>
    {% for item in group['items'] %}
     <div class="owner-metric-row"><span>{{item['label']}}</span><b>{{'{:,}'.format(item['value'])}}</b></div>
    {% endfor %}
   </section>
  {% endfor %}
 </div>
 <section class="card">
  <span class="tag">ROLLING 7 DAYS</span><h2>Recent activity</h2>
  <div class="grid">
   {% for item in weekly %}<div class="card"><p class="muted">{{item['label']}}</p><p class="balance">{{'{:,}'.format(item['value'])}}</p></div>{% endfor %}
  </div>
 </section>
 <section class="card" style="margin-top:18px">
  <h2>🔐 Recent owner actions</h2>
  <p class="muted">A short view of the owner audit log. Open Owner HQ for the full recent log.</p>
  {% for item in activity %}
   <div class="owner-activity"><b>{{item['action']}}</b><time>{{item['created_at'][:19].replace('T',' ')}}</time></div>
  {% else %}<p class="muted">No owner actions have been recorded yet.</p>{% endfor %}
  <a class="btn alt" href="{{url_for('owner_dashboard')}}">Open full Owner HQ</a>
 </section>
 <p class="muted" style="margin:16px 2px">Privacy note: figures are aggregate counts. This page does not display member ages, private messages, trip notes, application motivations or contact details. Counts reflect data stored in this app's local database and do not prove the app is publicly launched or connected to live external services.</p>
 ''', groups=groups, weekly=weekly, activity=activity)

@app.route('/announcements')
def announcements():
 rows=db().execute('SELECT id,title,body,created_at FROM announcements WHERE is_published=1 ORDER BY id DESC').fetchall()
 return page('Announcements','''<div class="hero"><span class="tag">AIR TRAVEL NEWS</span><h1>📢 Announcements Centre</h1><p>Official updates and notices from AIR TRAVEL Owner HQ.</p></div>{% for a in rows %}<article class="card" style="margin:16px 0"><h2>{{a['title']}}</h2><p>{{a['body']}}</p><small class="muted">Published {{a['created_at'][:16]}}</small></article>{% else %}<div class="card"><p>No announcements yet. Check back soon!</p></div>{% endfor %}''',rows=rows)

@app.route('/owner/announcement/publish',methods=['POST'])
@owner_required
def publish_announcement():
 title=request.form.get('title','').strip()[:100]
 body=request.form.get('body','').strip()[:3000]
 if not title or not body:
  flash('Enter both an announcement title and message.','error')
 else:
  owner=current_user(); c=db(); now=datetime.utcnow().isoformat()
  c.execute('INSERT INTO announcements(owner_id,title,body,created_at,is_published) VALUES(?,?,?,?,1)',(owner['id'],title,body,now))
  audit_owner_action('Announcement published',None,title); c.commit(); flash('Announcement published. Members can now see it in the Announcements Centre and on the home page.')
 return redirect(url_for('owner_dashboard'))

@app.route('/owner/announcement/<int:announcement_id>/delete',methods=['POST'])
@owner_required
def delete_announcement(announcement_id):
 c=db(); row=c.execute('SELECT title FROM announcements WHERE id=?',(announcement_id,)).fetchone()
 if row:
  c.execute('DELETE FROM announcements WHERE id=?',(announcement_id,)); audit_owner_action('Announcement deleted',None,row['title']); c.commit(); flash('Announcement deleted.')
 else: flash('Announcement not found.','error')
 return redirect(url_for('owner_dashboard'))

@app.route('/owner/approve/<int:user_id>',methods=['POST'])
@owner_required
def approve_member(user_id):
 c=db(); member=c.execute("SELECT id,age,approval_status FROM users WHERE id=? AND role='member'",(user_id,)).fetchone()
 if not member or member['approval_status']!='pending_review' or (member['age'] or 0)<13:
  flash('This account cannot be approved from this review action. Guardian consent may be required.','error')
 else:
  c.execute("UPDATE users SET approval_status='approved' WHERE id=?",(user_id,)); audit_owner_action('Account approved',user_id,'Registration review approved'); c.commit(); flash('Account approved. The member can now sign in.')
 return redirect(url_for('owner_dashboard'))

@app.route('/owner/member/<int:user_id>/mode',methods=['POST'])
@owner_required
def set_member_mode(user_id):
 mode=(request.form.get('mode') or '').strip()
 if mode not in ('kids','general'):
  flash('Choose Kids World or General Experience.','error'); return redirect(url_for('owner_dashboard'))
 c=db(); target=c.execute("SELECT id,name FROM users WHERE id=? AND role!='owner'",(user_id,)).fetchone()
 if not target: abort(404)
 c.execute('UPDATE users SET mode=? WHERE id=?',(mode,user_id))
 audit_owner_action('member_experience_changed',user_id,'Set experience mode to '+mode); c.commit()
 flash(target['name']+"'s experience is now set to "+('Kids World.' if mode=='kids' else 'General Experience.'))
 return redirect(url_for('owner_dashboard'))

@app.route('/owner/member/<int:user_id>/status',methods=['POST'])
@owner_required
def set_member_status(user_id):
 status=request.form.get('status','').strip()
 reason=request.form.get('reason','').strip()[:200]
 if status not in ('active','suspended') or not reason:
  flash('Choose a valid account status and provide a reason.','error')
  return redirect(url_for('owner_dashboard'))
 c=db()
 member=c.execute("SELECT id,name,account_status FROM users WHERE id=? AND role='member'",(user_id,)).fetchone()
 if not member:
  flash('Member account was not found.','error')
 elif member['account_status']==status:
  flash('That account already has this status.','error')
 else:
  c.execute('UPDATE users SET account_status=? WHERE id=?',(status,user_id))
  audit_owner_action('Member '+status, user_id, reason)
  c.commit()
  flash('Member account '+('suspended.' if status=='suspended' else 'restored.'))
 return redirect(url_for('owner_dashboard'))

@app.route('/owner/award',methods=['POST'])
@owner_required
def award_exp():
 try: uid=int(request.form['user_id']); amount=int(request.form['amount']); reason=request.form['reason'].strip()
 except: flash('Check the EXP award details.','error'); return redirect(url_for('owner_dashboard'))
 if amount<1 or amount>100000 or not reason: flash('Invalid award.','error')
 else:
  c=db(); c.execute("UPDATE users SET exp=exp+? WHERE id=? AND role!='owner'",(amount,uid)); c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(uid,amount,reason,datetime.utcnow().isoformat())); audit_owner_action('EXP awarded',uid,f'{amount} EXP: {reason}'); c.commit(); flash('EXP award recorded.')
 return redirect(url_for('owner_dashboard'))
@app.route('/owner/event',methods=['POST'])
@owner_required
def add_event():
 title=request.form.get('title','').strip()
 details=request.form.get('details','').strip()
 category=request.form.get('category','Community').strip()
 event_date=request.form.get('event_date','').strip()
 allowed_categories={'Aviation','Competition','Community','Learning','Entertainment','Other'}
 if category not in allowed_categories: category='Other'
 if event_date:
  try: datetime.strptime(event_date,'%Y-%m-%dT%H:%M')
  except ValueError: flash('Choose a valid event date and time.','error'); return redirect(url_for('owner_dashboard'))
 else: event_date=None
 if not (2<=len(title)<=100 and 10<=len(details)<=1200):
  flash('Event title must be 2–100 characters and details 10–1,200 characters.','error')
 else:
  c=db(); now=datetime.utcnow().isoformat()
  c.execute("INSERT INTO events(title,details,created_at,event_date,category,event_status) VALUES(?,?,?,?,?,'published')",(title,details,now,event_date,category))
  audit_owner_action('Event published',None,f'{title} · {category}')
  c.commit(); flash('Event published in the public Events Centre.')
 return redirect(url_for('owner_dashboard'))

@app.route('/events')
def events_centre():
 c=db()
 # Local event times are entered/displayed as WAT by the owner; no browser-local conversion is implied.
 now_wat=datetime.now(timezone(timedelta(hours=1))).replace(tzinfo=None,second=0,microsecond=0).isoformat(timespec='minutes')
 upcoming=c.execute("SELECT * FROM events WHERE event_status='published' AND (event_date IS NULL OR event_date='' OR event_date>=?) ORDER BY CASE WHEN event_date IS NULL OR event_date='' THEN 1 ELSE 0 END,event_date ASC,id DESC LIMIT 100",(now_wat,)).fetchall()
 archive=c.execute("SELECT * FROM events WHERE event_status!='published' OR (event_date IS NOT NULL AND event_date!='' AND event_date<?) ORDER BY COALESCE(event_date,created_at) DESC,id DESC LIMIT 60",(now_wat,)).fetchall()
 return page('Events Centre','''<div class="hero"><span class="tag">AIR TRAVEL COMMUNITY CALENDAR</span><h1>🗓️ Events Centre</h1><p>Discover upcoming aviation activities, competitions, learning sessions and community events from AIR TRAVEL.</p><p class="muted">Any displayed event time is Nigeria time (WAT). Events here are virtual community activities unless an event description explicitly says otherwise. No real-world travel booking is provided.</p></div><section class="card"><h2>🚀 Upcoming events</h2>{% for e in upcoming %}<article class="event-card" style="border:1px solid #245078;border-radius:14px;padding:16px;margin:12px 0;background:#0a203a"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><span class="tag">{{e['category']}}</span><small class="muted">{{e['event_date'].replace('T',' · ') if e['event_date'] else 'Date to be announced'}}</small></div><h3>{{e['title']}}</h3><p>{{e['details']}}</p></article>{% else %}<p>No upcoming events have been published yet. Please check again soon.</p>{% endfor %}</section><section class="card" style="margin-top:18px"><h2>📚 Event archive & notices</h2>{% for e in archive %}<article style="border-top:1px solid #245078;padding:14px 0"><span class="tag">{{e['event_status']|title}} · {{e['category']}}</span><h3>{{e['title']}}</h3><p>{{e['details']}}</p><small class="muted">{{e['event_date'].replace('T',' · ') if e['event_date'] else 'Date not specified'}}</small></article>{% else %}<p>Completed and cancelled events will appear here.</p>{% endfor %}</section>''',upcoming=upcoming,archive=archive)

@app.route('/owner/events')
@owner_required
def owner_event_manager():
 events=db().execute('SELECT * FROM events ORDER BY CASE WHEN event_date IS NULL OR event_date=\'\' THEN 1 ELSE 0 END,event_date DESC,id DESC LIMIT 100').fetchall()
 return page('Owner Event Manager','''<div class="hero"><span class="tag">PRIVATE OWNER TOOL</span><h1>🗓️ Event Manager</h1><p>Create, update, publish, complete or cancel AIR TRAVEL events.</p><p><a class="btn" href="{{url_for('owner_dashboard')}}">← Owner HQ</a> <a class="btn alt" href="{{url_for('events_centre')}}">View public Events Centre</a></p></div><div class="card"><h2>Manage published events</h2><p class="muted">Edits appear on the public Events Centre. Cancelled and completed events move to the archive. Event dates and times are Nigeria time (WAT).</p>{% for e in events %}<article style="border-top:1px solid #245078;padding:18px 0"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><b>#{{e['id']}} · {{e['title']}}</b><span class="tag">{{e['event_status']|title}}</span></div><form method="post" action="{{url_for('update_owner_event',event_id=e['id'])}}"><label>Title</label><input name="title" maxlength="100" value="{{e['title']}}" required><label>Category</label><select name="category"><option {% if e['category']=='Aviation' %}selected{% endif %}>Aviation</option><option {% if e['category']=='Competition' %}selected{% endif %}>Competition</option><option {% if e['category']=='Community' %}selected{% endif %}>Community</option><option {% if e['category']=='Learning' %}selected{% endif %}>Learning</option><option {% if e['category']=='Entertainment' %}selected{% endif %}>Entertainment</option><option {% if e['category']=='Other' %}selected{% endif %}>Other</option></select><label>Date and time (Nigeria time, optional)</label><input type="datetime-local" name="event_date" value="{{e['event_date'] or ''}}"><label>Details</label><textarea name="details" maxlength="1200" required>{{e['details']}}</textarea><button>Save event changes</button></form><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px"><form method="post" action="{{url_for('set_owner_event_status',event_id=e['id'])}}"><button name="status" value="published">Publish / Restore</button><button class="btn alt" name="status" value="completed">Mark completed</button><button class="btn alt" name="status" value="cancelled">Cancel event</button></form></div></article>{% else %}<p>No events have been created yet. Use the event form in Owner HQ to publish the first one.</p>{% endfor %}</div>''',events=events)

@app.route('/owner/event/<int:event_id>/update',methods=['POST'])
@owner_required
def update_owner_event(event_id):
 title=request.form.get('title','').strip()
 details=request.form.get('details','').strip()
 category=request.form.get('category','Other').strip()
 event_date=request.form.get('event_date','').strip()
 allowed_categories={'Aviation','Competition','Community','Learning','Entertainment','Other'}
 if event_date:
  try: datetime.strptime(event_date,'%Y-%m-%dT%H:%M')
  except ValueError: flash('Choose a valid event date and time.','error'); return redirect(url_for('owner_event_manager'))
 else: event_date=None
 if category not in allowed_categories or not (2<=len(title)<=100 and 10<=len(details)<=1200):
  flash('Check the event category, title and details.','error'); return redirect(url_for('owner_event_manager'))
 c=db(); row=c.execute('SELECT id,title FROM events WHERE id=?',(event_id,)).fetchone()
 if not row: flash('Event not found.','error')
 else:
  c.execute('UPDATE events SET title=?,details=?,event_date=?,category=? WHERE id=?',(title,details,event_date,category,event_id))
  audit_owner_action('Event updated',None,f'Event #{event_id}: {row["title"]} → {title}')
  c.commit(); flash('Event changes saved.')
 return redirect(url_for('owner_event_manager'))

@app.route('/owner/event/<int:event_id>/status',methods=['POST'])
@owner_required
def set_owner_event_status(event_id):
 status=request.form.get('status','').strip()
 if status not in {'published','cancelled','completed'}:
  flash('Choose a valid event status.','error'); return redirect(url_for('owner_event_manager'))
 c=db(); row=c.execute('SELECT title,event_status FROM events WHERE id=?',(event_id,)).fetchone()
 if not row: flash('Event not found.','error')
 elif row['event_status']==status: flash('The event already has that status.')
 else:
  c.execute('UPDATE events SET event_status=? WHERE id=?',(status,event_id))
  audit_owner_action('Event status changed',None,f'{row["title"]}: {row["event_status"]} → {status}')
  c.commit(); flash('Event status updated.')
 return redirect(url_for('owner_event_manager'))
@app.route('/experience')
def experience():
 items=[('Pilot Wings Badge',250,'Aviation badge for your profile'),('Cloud Explorer Frame',400,'A sky-themed profile frame'),('Golden Aircraft Skin',800,'A gold aircraft appearance'),('Airport VIP Pass',1200,'A virtual VIP airport pass')]
 owned=set()
 if current_user() and current_user()['role']!='owner':
  owned={r['item'] for r in db().execute('SELECT item FROM user_items WHERE user_id=?',(current_user()['id'],)).fetchall()}
 return page('EXP Shop','''<div class="hero"><h1>🎁 EXP Gift Shop</h1><p>Redeem virtual aviation collectibles with your member EXP. These are digital in-app items, not physical products.</p>{% if user %}<p>Your balance: <b class="balance">{{'{:,}'.format(user['exp'])}} EXP</b></p>{% else %}<p>Sign in to redeem gifts.</p>{% endif %}</div><div class="grid">{% for name,cost,description in items %}<div class="card"><div class="feature-icon">🎁</div><h3>{{name}}</h3><p>{{description}}</p><p class="stat">{{'{:,}'.format(cost)}} EXP</p>{% if user and user['role']=='owner' %}<span class="tag">OWNER ACCESS · UNLOCKED</span>{% elif user and name in owned %}<span class="tag">ALREADY REDEEMED ✓</span>{% elif user %}<form method="post" action="{{url_for('buy_item')}}"><input type="hidden" name="item" value="{{name}}"><button type="submit">Redeem for {{cost}} EXP</button></form>{% else %}<a href="{{url_for('login')}}">Sign in to redeem</a>{% endif %}</div>{% endfor %}</div><p class="muted">Purchases use EXP only. EXP has no cash value and cannot be exchanged for money.</p>''',items=items,owned=owned)
@app.route('/experience/buy',methods=['POST'])
@login_required
def buy_item():
 u=current_user(); item=request.form.get('item','').strip()
 prices={'Pilot Wings Badge':250,'Cloud Explorer Frame':400,'Golden Aircraft Skin':800,'Airport VIP Pass':1200}
 if u['role']=='owner': flash('Owner access includes all virtual items.')
 elif item not in prices: flash('That shop item is not available.','error')
 else:
  cost=prices[item]; c=db()
  try:
   c.execute('BEGIN IMMEDIATE')
   fresh=c.execute("SELECT exp FROM users WHERE id=? AND role!='owner'",(u['id'],)).fetchone()
   if not fresh: raise ValueError('Member account not found.')
   if c.execute('SELECT 1 FROM user_items WHERE user_id=? AND item=?',(u['id'],item)).fetchone(): raise ValueError('You have already redeemed this item.')
   if fresh['exp']<cost: raise ValueError(f'You need {cost:,} EXP; your balance is {fresh["exp"]:,} EXP.')
   c.execute('UPDATE users SET exp=exp-? WHERE id=?',(cost,u['id']))
   c.execute('INSERT INTO user_items(user_id,item,cost,purchased_at) VALUES(?,?,?,?)',(u['id'],item,cost,datetime.utcnow().isoformat()))
   c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(u['id'],-cost,'Redeemed '+item,datetime.utcnow().isoformat()))
   c.commit(); flash('Success! '+item+' has been added to your collection.')
  except sqlite3.IntegrityError:
   c.rollback(); flash('This item is already in your collection.','error')
  except ValueError as e:
   c.rollback(); flash(str(e),'error')
 return redirect(url_for('experience'))
@app.route('/premium', methods=['GET','POST'])
def premium():
 u=current_user()
 plans={
  'weekly':('Weekly',100000,7),
  'monthly':('Monthly',500000,30),
  'yearly':('Yearly',1000000,365),
 }
 if request.method=='POST':
  if not u:
   flash('Please sign in to redeem Premium with EXP.','error'); return redirect(url_for('login'))
  if u['role']=='owner':
   flash('Owner account already has full Premium access.'); return redirect(url_for('premium'))
  key=request.form.get('plan','')
  if key not in plans:
   flash('That EXP Premium plan is not available.','error'); return redirect(url_for('premium'))
  label,cost,days=plans[key]; c=db()
  try:
   c.execute('BEGIN IMMEDIATE')
   fresh=c.execute("SELECT exp FROM users WHERE id=? AND role='member'",(u['id'],)).fetchone()
   if not fresh: raise ValueError('A member account is required.')
   if fresh['exp']<cost: raise ValueError(f'You need {cost:,} EXP for {label} Premium. Your balance is {fresh["exp"]:,} EXP.')
   now=datetime.now(timezone(timedelta(hours=1)))
   existing=c.execute('SELECT expires_at FROM premium_memberships WHERE user_id=? ORDER BY id DESC LIMIT 1',(u['id'],)).fetchone()
   base=max(now,datetime.fromisoformat(existing['expires_at'])) if existing else now
   expires=base+timedelta(days=days)
   c.execute('UPDATE users SET exp=exp-? WHERE id=?',(cost,u['id']))
   c.execute('INSERT INTO premium_memberships(user_id,plan,starts_at,expires_at,payment_method) VALUES(?,?,?,?,?)',(u['id'],label,now.isoformat(),expires.isoformat(),'EXP'))
   c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(u['id'],-cost,'Premium '+label+' redeemed with EXP',now.isoformat()))
   c.commit(); flash(f'Success! {label} Premium was redeemed with EXP until {expires.strftime("%d %b %Y %H:%M")} Nigeria time.')
  except (ValueError,sqlite3.Error) as e:
   c.rollback(); flash(str(e) if isinstance(e,ValueError) else 'Could not complete the redemption. Please try again.','error')
  return redirect(url_for('premium'))
 if u and u['role']=='owner':
  return page('Premium', '<div class="hero"><h1>Owner Premium Access</h1><p>Your owner account has full access to Premium features.</p></div>')
 trial=db().execute('SELECT starts_at,ends_at FROM premium_trials WHERE user_id=?',(u['id'],)).fetchone() if u else None
 active=bool(trial and datetime.utcnow() < datetime.fromisoformat(trial['ends_at']))
 end_label=trial['ends_at'][:16].replace('T',' ')+' UTC' if trial else 'No trial available'
 membership=db().execute('SELECT plan,expires_at FROM premium_memberships WHERE user_id=? ORDER BY id DESC LIMIT 1',(u['id'],)).fetchone() if u else None
 body='''<div class="hero"><span class="tag">PREMIUM MEMBERSHIP</span><h1>Enjoy 3 Days of Premium Free</h1><p>{% if user %}{% if active %}<b>Your trial is active until {{end_label}} UTC.</b>{% else %}<b>Your trial has ended or is unavailable.</b>{% endif %}{% else %}Create an account to receive the eligible free trial and use EXP to redeem plans.{% endif %}</p>{% if membership %}<p class="notice">Current EXP membership: {{membership['plan']}} · expires {{membership['expires_at'][:16].replace('T',' ')}}</p>{% endif %}</div>
 <div class="grid"><div class="card"><h2>Free Trial</h2><p>3 days of Premium access, once per account.</p><span class="tag">{% if active %}TRIAL ACTIVE{% else %}TRIAL INACTIVE / SIGN UP{% endif %}</span></div>
 <div class="card"><h2>Premium Weekly</h2><p class="balance">₦500 / 100,000 EXP</p><p>7 days of Premium membership.</p>{% if user %}<form method="post"><input type="hidden" name="plan" value="weekly"><button>Redeem with 100,000 EXP</button></form>{% else %}<a class="btn" href="{{url_for('login')}}">Sign in to use EXP</a>{% endif %}<form method="post" action="{{url_for('premium_card_initialize')}}"><input type="hidden" name="plan" value="weekly"><label>Adult payer email</label><input type="email" name="payer_email" required><label><input type="checkbox" name="adult_authorized" value="yes" required> An authorised adult approves this purchase.</label><button {% if not paystack_ready %}disabled{% endif %}>Pay by card · ₦500</button></form><p class="muted">Secure card checkout requires adult merchant setup.</p></div>
 <div class="card"><h2>Premium Monthly</h2><p class="balance">₦1,000 / 500,000 EXP</p><p>30 days of Premium membership.</p>{% if user %}<form method="post"><input type="hidden" name="plan" value="monthly"><button>Redeem with 500,000 EXP</button></form>{% else %}<a class="btn" href="{{url_for('login')}}">Sign in to use EXP</a>{% endif %}<form method="post" action="{{url_for('premium_card_initialize')}}"><input type="hidden" name="plan" value="monthly"><label>Adult payer email</label><input type="email" name="payer_email" required><label><input type="checkbox" name="adult_authorized" value="yes" required> An authorised adult approves this purchase.</label><button {% if not paystack_ready %}disabled{% endif %}>Pay by card · ₦1,000</button></form><p class="muted">Secure card checkout requires adult merchant setup.</p></div>
 <div class="card"><h2>Premium Yearly</h2><p class="balance">₦5,000 / 1,000,000 EXP</p><p>365 days of Premium membership.</p>{% if user %}<form method="post"><input type="hidden" name="plan" value="yearly"><button>Redeem with 1,000,000 EXP</button></form>{% else %}<a class="btn" href="{{url_for('login')}}">Sign in to use EXP</a>{% endif %}<form method="post" action="{{url_for('premium_card_initialize')}}"><input type="hidden" name="plan" value="yearly"><label>Adult payer email</label><input type="email" name="payer_email" required><label><input type="checkbox" name="adult_authorized" value="yes" required> An authorised adult approves this purchase.</label><button {% if not paystack_ready %}disabled{% endif %}>Pay by card · ₦5,000</button></form><p class="muted">Secure card checkout requires adult merchant setup.</p></div>
 <div class="card"><h2>PRO · 10 Years</h2><p class="balance">₦50,000</p><p>Long-term PRO membership.</p><form method="post" action="{{url_for('premium_card_initialize')}}"><input type="hidden" name="plan" value="pro"><label>Adult payer email</label><input type="email" name="payer_email" required><label><input type="checkbox" name="adult_authorized" value="yes" required> Authorised adult approval</label><button {% if not paystack_ready %}disabled{% endif %}>Pay by card · ₦50,000</button></form></div>
 <div class="card"><h2>👑 ROYAL · 20 Years</h2><p class="balance">₦100,000</p><p>Our highest membership tier.</p><form method="post" action="{{url_for('premium_card_initialize')}}"><input type="hidden" name="plan" value="royal"><label>Adult payer email</label><input type="email" name="payer_email" required><label><input type="checkbox" name="adult_authorized" value="yes" required> Authorised adult approval</label><button {% if not paystack_ready %}disabled{% endif %}>Pay by card · ₦100,000</button></form><span class="tag">ROYAL TIER</span></div></div>
 <div class="card"><h3>Two ways to get Premium</h3><p>EXP redemption is active for Weekly, Monthly and Yearly plans when signed in. Naira prices are displayed, but real-money checkout is not connected yet, so no cash payment can be taken in this build. A secure payment provider, verified payment confirmation, receipts and refund handling must be integrated before cash purchases can work. Younger users need parent or guardian approval for payments.</p></div>'''
 return page('Premium',body,active=active,end_label=end_label,membership=membership,paystack_ready=bool(os.environ.get('PAYSTACK_SECRET_KEY')))


PREMIUM_CARD_PLANS={'weekly':('Weekly',50000,7),'monthly':('Monthly',100000,30),'yearly':('Yearly',500000,365),'pro':('PRO',5000000,3650),'royal':('ROYAL',10000000,7300)}
def paystack_request(path,payload=None):
 secret=os.environ.get('PAYSTACK_SECRET_KEY','').strip()
 if not secret: raise RuntimeError('Card checkout is not configured. An authorised adult must complete merchant setup first.')
 data=json.dumps(payload).encode() if payload is not None else None
 req=urllib.request.Request('https://api.paystack.co'+path,data=data,headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'},method='POST' if payload is not None else 'GET')
 with urllib.request.urlopen(req,timeout=20) as response: return json.loads(response.read().decode())

@app.route('/premium/card/initialize',methods=['POST'])
@login_required
def premium_card_initialize():
 u=current_user()
 if u['role']!='member': abort(403)
 plan=request.form.get('plan',''); payer=(request.form.get('payer_email') or '').strip().lower()
 if plan not in PREMIUM_CARD_PLANS or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',payer) or request.form.get('adult_authorized')!='yes':
  flash('Choose a plan and enter an authorised adult payer email with their approval.','error'); return redirect(url_for('premium'))
 if not os.environ.get('PAYSTACK_SECRET_KEY'):
  flash('Card checkout is not live yet. The authorised adult merchant account must be configured on the server. No payment was taken.','error'); return redirect(url_for('premium'))
 label,amount_kobo,days=PREMIUM_CARD_PLANS[plan]; reference='ATW_'+secrets.token_urlsafe(20).replace('-','').replace('_','')
 try:
  result=paystack_request('/transaction/initialize',{'email':payer,'amount':amount_kobo,'currency':'NGN','reference':reference,'callback_url':url_for('premium_card_verify',_external=True),'metadata':{'user_id':u['id'],'plan':plan,'app':'AIR TRAVEL'}})
  if not result.get('status') or not result.get('data',{}).get('authorization_url'): raise RuntimeError('Payment provider did not return a checkout link.')
  c=db(); c.execute("INSERT INTO premium_card_payments(user_id,plan_key,reference,amount_kobo,payer_email,status,created_at) VALUES(?,?,?,?,?,'pending',?)",(u['id'],plan,reference,amount_kobo,payer,datetime.utcnow().isoformat())); c.commit()
  return redirect(result['data']['authorization_url'])
 except Exception:
  app.logger.exception('Premium checkout initialization failed'); flash('Could not start secure checkout. No payment was taken.','error'); return redirect(url_for('premium'))

@app.route('/premium/card/verify')
@login_required
def premium_card_verify():
 u=current_user(); reference=(request.args.get('reference') or request.args.get('trxref') or '').strip()
 if not reference or len(reference)>100: flash('Payment reference is missing.','error'); return redirect(url_for('premium'))
 c=db(); payment=c.execute('SELECT * FROM premium_card_payments WHERE reference=? AND user_id=?',(reference,u['id'])).fetchone()
 if not payment: flash('This payment reference was not found on your account.','error'); return redirect(url_for('premium'))
 if payment['status']=='paid': flash('This payment was already confirmed. Your Premium access is active.'); return redirect(url_for('premium'))
 try:
  result=paystack_request('/transaction/verify/'+urllib.parse.quote(reference,safe='')); info=result.get('data') or {}
  if not result.get('status') or info.get('status')!='success' or info.get('reference')!=reference or info.get('amount')!=payment['amount_kobo'] or info.get('currency')!='NGN' or (info.get('customer') or {}).get('email','').lower()!=payment['payer_email'].lower():
   flash('Payment is not confirmed yet. Premium has not been activated. If your account was charged, contact the authorised merchant for help.','error'); return redirect(url_for('premium'))
  label,_,days=PREMIUM_CARD_PLANS[payment['plan_key']]; now=datetime.now(timezone(timedelta(hours=1))); c.execute('BEGIN IMMEDIATE')
  fresh=c.execute('SELECT status FROM premium_card_payments WHERE id=?',(payment['id'],)).fetchone()
  if fresh['status']!='paid':
   existing=c.execute('SELECT expires_at FROM premium_memberships WHERE user_id=? ORDER BY id DESC LIMIT 1',(u['id'],)).fetchone(); base=max(now,datetime.fromisoformat(existing['expires_at'])) if existing else now; expires=base+timedelta(days=days)
   c.execute("UPDATE premium_card_payments SET status='paid',paid_at=? WHERE id=? AND status='pending'",(now.isoformat(),payment['id']))
   if c.execute('SELECT changes()').fetchone()[0]==1: c.execute('INSERT INTO premium_memberships(user_id,plan,starts_at,expires_at,payment_method) VALUES(?,?,?,?,?)',(u['id'],label,now.isoformat(),expires.isoformat(),'Paystack card'))
  c.commit(); flash('Payment verified. '+label+' Premium is now active. Keep your provider receipt for your records.')
 except Exception:
  c.rollback(); app.logger.exception('Premium payment verification failed'); flash('We could not verify this payment right now. Premium has not been activated. Please retry later.','error')
 return redirect(url_for('premium'))

@app.route('/community',methods=['GET','POST'])
def community():
 if request.method=='POST':
  u=current_user(); body=request.form.get('body','').strip()
  if not u: flash('Sign in to post.','error')
  elif body and len(body)<=500:
   c=db(); c.execute("INSERT INTO posts(user_id,body,created_at,moderation_status) VALUES(?,?,?,'visible')",(u['id'],body,datetime.utcnow().isoformat())); c.commit(); flash('Message posted.')
  return redirect(url_for('community'))
 posts=db().execute("SELECT posts.id,posts.body,posts.created_at,users.name,users.id AS author_id FROM posts JOIN users ON users.id=posts.user_id WHERE posts.moderation_status='visible' ORDER BY posts.id DESC LIMIT 60").fetchall()
 return page('ATW Chat','''<div class="card"><span class="tag">ATW COMMUNITY</span><h2>💬 ATW Chat</h2><p>Share aviation interests, travel ideas and friendly updates. This is a moderated message board, not live instant messaging or an aviation radio channel. Be respectful and never post private contact details.</p>{% if user and user['role']=='member' %}<form method="post"><textarea name="body" maxlength="500" placeholder="Write a community message…" required></textarea><button>Post message</button></form>{% elif not user %}<a class="btn" href="{{url_for('login')}}">Sign in to chat</a>{% endif %}</div><div class="card"><h2>🌐 Join our Discord</h2><p>Visit the AIR TRAVEL community Discord.</p><a class="btn" href="https://discord.gg/maVTUuMQe" target="_blank" rel="noopener noreferrer">Join ATW on Discord ↗</a></div><div class="card"><h3>Community messages</h3>{% for p in posts %}<div style="border-bottom:1px solid #245078;padding:12px 0"><b>{{p['name']}}</b> <small class="muted">{{p['created_at'][:16]}}</small><br>{{p['body']}}{% if user and user['role']=='member' and user['id']!=p['author_id'] %}<form method="post" action="{{url_for('report_post',post_id=p['id'])}}" style="margin-top:8px"><select name="reason" required><option value="">Report reason…</option><option>Bullying or harassment</option><option>Spam</option><option>Personal information</option><option>Inappropriate content</option><option>Other safety concern</option></select><input name="details" maxlength="200" placeholder="Optional details"><button class="btn alt">Report post</button></form>{% endif %}</div>{% else %}<p>No messages yet.</p>{% endfor %}</div><div class="notice">If a post makes you uncomfortable, report it. Do not share your phone number, home address, school details or passwords.</div>''',posts=posts)

@app.route('/community/report/<int:post_id>',methods=['POST'])
@login_required
def report_post(post_id):
 u=current_user()
 if u['role']!='member': flash('Reports are submitted from member accounts.','error'); return redirect(url_for('community'))
 reason=request.form.get('reason','').strip(); details=request.form.get('details','').strip()[:200]
 allowed={'Bullying or harassment','Spam','Personal information','Inappropriate content','Other safety concern'}
 c=db(); post=c.execute('SELECT id,user_id,moderation_status FROM posts WHERE id=?',(post_id,)).fetchone()
 if not post or post['moderation_status']!='visible' or post['user_id']==u['id'] or reason not in allowed:
  flash('This report could not be submitted.','error')
 else:
  try:
   c.execute('INSERT INTO post_reports(post_id,reporter_id,reason,details,created_at) VALUES(?,?,?,?,?)',(post_id,u['id'],reason,details,datetime.utcnow().isoformat())); c.commit(); flash('Thank you. Your report has been sent to the owner for review.')
  except sqlite3.IntegrityError: flash('You have already reported this post.','error')
 return redirect(url_for('community'))

@app.route('/owner/community/report/<int:report_id>',methods=['POST'])
@owner_required
def moderate_report(report_id):
 action=request.form.get('action',''); c=db(); report=c.execute('SELECT id,post_id,status FROM post_reports WHERE id=?',(report_id,)).fetchone()
 if not report or report['status']!='open' or action not in {'hide','dismiss','delete'}:
  flash('That report is no longer open.','error'); return redirect(url_for('owner_dashboard'))
 now=datetime.utcnow().isoformat()
 if action=='hide':
  c.execute("UPDATE posts SET moderation_status='hidden' WHERE id=?",(report['post_id'],)); c.execute("UPDATE post_reports SET status='reviewed',reviewed_at=? WHERE post_id=? AND status='open'",(now,report['post_id'])); audit_owner_action('Community post hidden',None,'Post ID '+str(report['post_id']))
 elif action=='dismiss':
  c.execute("UPDATE post_reports SET status='dismissed',reviewed_at=? WHERE id=?",(now,report_id)); audit_owner_action('Community report dismissed',None,'Report ID '+str(report_id))
 else:
  c.execute('DELETE FROM post_reports WHERE post_id=?',(report['post_id'],)); c.execute('DELETE FROM posts WHERE id=?',(report['post_id'],)); audit_owner_action('Community post deleted',None,'Post ID '+str(report['post_id']))
 c.commit(); flash('Community moderation action completed.'); return redirect(url_for('owner_dashboard'))

@app.route('/live-flights',methods=['GET','POST'])
@login_required
def live_flight_search():
 results=[]; error=''; searched=False
 if request.method=='POST':
  origin=request.form.get('origin','').strip().upper()
  destination=request.form.get('destination','').strip().upper()
  departure=request.form.get('departure_date','').strip()
  returning=request.form.get('return_date','').strip()
  adults=request.form.get('adults','1').strip()
  cabin=request.form.get('cabin','ECONOMY').strip().upper()
  currency=request.form.get('currency','NGN').strip().upper()
  searched=True
  try:
   if not re.fullmatch(r'[A-Z]{3}',origin) or not re.fullmatch(r'[A-Z]{3}',destination) or origin==destination: raise ValueError('Enter valid three-letter airport codes, such as LOS and ABV.')
   dep=date.fromisoformat(departure)
   if dep<date.today(): raise ValueError('Departure date must be today or later.')
   if returning:
    ret=date.fromisoformat(returning)
    if ret<dep: raise ValueError('Return date cannot be before departure.')
   if adults not in {'1','2','3','4','5','6','7','8','9'}: raise ValueError('Choose between 1 and 9 adult passengers.')
   if cabin not in {'ECONOMY','PREMIUM_ECONOMY','BUSINESS','FIRST'}: raise ValueError('Choose a valid cabin class.')
   if not amadeus_configured():
    error='Live flight search is not connected yet. An authorised adult administrator must create a provider account and configure AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET on the server.'
   else:
    params={'originLocationCode':origin,'destinationLocationCode':destination,'departureDate':departure,'adults':adults,'travelClass':cabin,'currencyCode':currency,'max':10}
    if returning: params['returnDate']=returning
    payload=amadeus_api_request('/v2/shopping/flight-offers',params)
    for item in payload.get('data',[]):
     itineraries=item.get('itineraries',[]); first=itineraries[0]['segments'][0] if itineraries and itineraries[0].get('segments') else {}
     last=itineraries[0]['segments'][-1] if itineraries and itineraries[0].get('segments') else {}
     results.append({'id':item.get('id'),'price':item.get('price',{}).get('grandTotal'),'currency':item.get('price',{}).get('currency',currency),'airline':', '.join(item.get('validatingAirlineCodes',[])),'depart':first.get('departure',{}).get('at',''),'arrive':last.get('arrival',{}).get('at',''),'stops':max(0,len(itineraries[0].get('segments',[]))-1) if itineraries else 0,'seats':item.get('numberOfBookableSeats')})
    if not results: error='No live offers were returned for those dates and airports. Try different dates or airports.'
  except ValueError as e: error=str(e)
  except urllib.error.HTTPError as e:
   try: detail=json.loads(e.read().decode()).get('errors',[{}])[0].get('detail','')
   except Exception: detail=''
   error='The flight provider could not complete the search. '+(detail or 'Please check the airport codes and provider account settings.')
  except Exception: error='Live search is temporarily unavailable. Please try again later.'
 return page('Live Flight Search',r'''<section class="hero"><h1>🌍 Live Flight Search</h1><p>Search flight offers supplied by our connected booking provider.</p><span class="tag">LIVE SEARCH · NOT A TICKET</span></section><div class="card"><form method="post"><div class="grid"><div><label>From airport code</label><input name="origin" maxlength="3" placeholder="LOS" pattern="[A-Za-z]{3}" required value="{{request.form.get('origin','')}}"></div><div><label>To airport code</label><input name="destination" maxlength="3" placeholder="ABV" pattern="[A-Za-z]{3}" required value="{{request.form.get('destination','')}}"></div></div><div class="grid"><div><label>Departure</label><input type="date" name="departure_date" min="{{today}}" required value="{{request.form.get('departure_date','')}}"></div><div><label>Return (optional)</label><input type="date" name="return_date" min="{{today}}" value="{{request.form.get('return_date','')}}"></div></div><div class="grid"><div><label>Adult passengers</label><input type="number" name="adults" min="1" max="9" value="{{request.form.get('adults','1')}}"></div><div><label>Cabin</label><select name="cabin"><option value="ECONOMY">Economy</option><option value="PREMIUM_ECONOMY">Premium Economy</option><option value="BUSINESS">Business</option><option value="FIRST">First</option></select></div></div><label>Currency</label><select name="currency"><option>NGN</option><option>USD</option><option>EUR</option><option>GBP</option></select><button type="submit">Search live flight offers</button></form><p class="muted">Use three-letter IATA airport codes (Lagos LOS, Abuja ABV, Port Harcourt PHC). Prices and seats can change before booking.</p></div>{% if error %}<div class="card" role="status"><b>{{error}}</b></div>{% endif %}{% if results %}<h2>Available offers</h2><div class="grid">{% for f in results %}<article class="card"><h3>{{f.airline or 'Airline offer'}}</h3><p><b>{{f.price}} {{f.currency}}</b></p><p>{{f.depart}} → {{f.arrive}}</p><p>{{f.stops}} stop(s) · {{f.seats or 'Seat count not supplied'}} bookable seats</p><p class="muted">Offer {{f.id}} · Availability and price must be rechecked at booking.</p></article>{% endfor %}</div><p class="muted">These are search offers only. No reservation or ticket has been created and no payment has been taken.</p>{% endif %}''',results=results,error=error,today=date.today().isoformat())

@app.route('/booking-centre',methods=['GET','POST'])
@login_required
def booking_centre():
 u=current_user(); c=db()
 if request.method=='POST':
  origin=request.form.get('origin','').strip()[:100]
  destination=request.form.get('destination','').strip()[:100]
  departure=request.form.get('travel_date','').strip()
  returning=request.form.get('return_date','').strip() or None
  airline=request.form.get('airline','Any available airline').strip()[:80]
  cabin=request.form.get('cabin_class','Economy').strip()[:30]
  notes=request.form.get('notes','').strip()[:1000]
  try:
   dep=date.fromisoformat(departure)
   ret=date.fromisoformat(returning) if returning else None
   passengers=int(request.form.get('passengers','1'))
   if not origin or not destination or origin.casefold()==destination.casefold(): raise ValueError()
   if dep < date.today() or (ret and ret < dep): raise ValueError()
   if passengers<1 or passengers>9: raise ValueError()
   c.execute('''INSERT INTO flight_booking_requests(user_id,origin,destination,departure_date,return_date,passengers,airline_preference,cabin_class,contact_email,notes,status,created_at,updated_at)
    VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?)''',(u['id'],origin,destination,departure,returning,passengers,airline,cabin,u['email'],notes,datetime.utcnow().isoformat(),datetime.utcnow().isoformat()))
   c.commit(); flash('Your booking request was submitted. It is awaiting review; this is not a confirmed ticket and no payment was taken.')
  except (ValueError,TypeError):
   c.rollback(); flash('Please check the airports, dates and passenger count. Dates must be today or later, and return date cannot be before departure.','error')
  return redirect(url_for('booking_centre'))
 requests=c.execute('SELECT * FROM flight_booking_requests WHERE user_id=? ORDER BY id DESC LIMIT 20',(u['id'],)).fetchall()
 return page('Flight Booking Centre',r'''<section class="hero"><h1>✈ Flight Booking Centre</h1><p>Send a flight booking request and track its progress from your account.</p><span class="tag">BOOKING REQUESTS · NOT LIVE TICKETING</span></section>
 <div class="card"><h2>Request a flight</h2><form method="post"><div class="grid"><div><label>From airport / city</label><input name="origin" maxlength="100" placeholder="e.g. Lagos (LOS)" required></div><div><label>To airport / city</label><input name="destination" maxlength="100" placeholder="e.g. Abuja (ABV)" required></div></div>
 <div class="grid"><div><label>Departure date</label><input type="date" name="travel_date" min="{{today}}" required></div><div><label>Return date (optional)</label><input type="date" name="return_date" min="{{today}}"></div></div>
 <div class="grid"><div><label>Passengers (1–9)</label><input type="number" name="passengers" min="1" max="9" value="1" required></div><div><label>Cabin</label><select name="cabin_class"><option>Economy</option><option>Premium Economy</option><option>Business</option><option>First</option></select></div></div>
 <label>Airline preference</label><select name="airline"><option>Any available airline</option><option>Air Peace</option><option>United Nigeria Airlines</option><option>Ibom Air</option><option>Green Africa Airways</option><option>International airline</option></select>
 <label>Extra request (optional)</label><textarea name="notes" maxlength="1000" placeholder="Accessibility needs or other non-sensitive travel preferences"></textarea><button type="submit">Submit booking request</button></form>
 <p class="muted">This saves a request for review. It does not check live fares or seat availability, issue tickets, or take payment. Never enter passport numbers or payment-card details here. A real booking requires a verified airline or authorised booking-provider integration.</p></div>
 <h2>Your booking requests</h2><div class="grid">{% for b in requests %}<article class="card"><b>{{b['origin']}} → {{b['destination']}}</b><p>Departure: {{b['departure_date']}}{% if b['return_date'] %}<br>Return: {{b['return_date']}}{% endif %}</p><p>{{b['passengers']}} passenger(s) · {{b['cabin_class']}} · {{b['airline_preference']}}</p><span class="tag">{{b['status']|upper}}</span><p class="muted">Request #{{b['id']}} · {{b['created_at'][:10]}}</p></article>{% else %}<div class="card">You have not submitted a booking request yet.</div>{% endfor %}</div>''',requests=requests,today=date.today().isoformat())

@app.route('/owner/booking-requests',methods=['GET','POST'])
@owner_required
def owner_booking_requests():
 c=db()
 if request.method=='POST':
  try: rid=int(request.form.get('request_id','0'))
  except ValueError: rid=0
  status=request.form.get('status','')
  if status not in {'pending','contacted','closed'}: flash('Invalid booking request status.','error')
  else:
   row=c.execute('SELECT id FROM flight_booking_requests WHERE id=?',(rid,)).fetchone()
   if row:
    c.execute('UPDATE flight_booking_requests SET status=?,updated_at=? WHERE id=?',(status,datetime.utcnow().isoformat(),rid)); c.commit(); audit_owner_action('Flight booking request status updated',None,f'Request #{rid}: {status}'); flash('Booking request updated.')
   else: flash('Booking request not found.','error')
  return redirect(url_for('owner_booking_requests'))
 rows=c.execute('''SELECT b.*,u.username,u.name FROM flight_booking_requests b JOIN users u ON u.id=b.user_id ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'contacted' THEN 1 ELSE 2 END,b.id DESC LIMIT 200''').fetchall()
 return page('Booking Requests',r'''<section class="hero"><h1>👑 Flight Booking Requests</h1><p>Review member enquiries. Updating a status does not confirm or issue a ticket.</p></section><div class="grid">{% for b in rows %}<article class="card"><h3>{{b['origin']}} → {{b['destination']}}</h3><p>Member: {{b['username']}} ({{b['name']}})</p><p>Departure: {{b['departure_date']}} · Return: {{b['return_date'] or 'One way'}}</p><p>{{b['passengers']}} passenger(s) · {{b['cabin_class']}} · {{b['airline_preference']}}</p><p>Contact: {{b['contact_email']}}</p><p>{{b['notes']}}</p><span class="tag">{{b['status']|upper}}</span><form method="post"><input type="hidden" name="request_id" value="{{b['id']}}"><select name="status"><option value="pending" {% if b['status']=='pending' %}selected{% endif %}>Pending</option><option value="contacted" {% if b['status']=='contacted' %}selected{% endif %}>Contacted</option><option value="closed" {% if b['status']=='closed' %}selected{% endif %}>Closed</option></select><button>Update status</button></form></article>{% else %}<div class="card">No booking requests yet.</div>{% endfor %}</div>''',rows=rows)

@app.route('/trip-planner', methods=['GET','POST'])
@login_required
def trip_planner():
 u=current_user(); c=db()
 if request.method=='POST':
  title=request.form.get('title','').strip()[:70]
  origin=request.form.get('origin','').strip()[:80]
  destination=request.form.get('destination','').strip()[:80]
  departure=request.form.get('departure_date','').strip()
  returning=request.form.get('return_date','').strip() or None
  notes=request.form.get('notes','').strip()[:1200]
  budget_raw=request.form.get('budget','').strip()
  try:
   dep=date.fromisoformat(departure)
   ret=date.fromisoformat(returning) if returning else None
   if ret and ret < dep: raise ValueError('Return date must be on or after departure date.')
   budget=float(budget_raw) if budget_raw else None
   if budget is not None and (budget < 0 or budget > 1000000000): raise ValueError('Enter a valid budget amount.')
   if not title or not origin or not destination: raise ValueError('Please complete the trip title, origin and destination.')
   if origin.casefold()==destination.casefold(): raise ValueError('Origin and destination must be different.')
   c.execute('INSERT INTO trip_plans(user_id,title,origin,destination,departure_date,return_date,budget,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(u['id'],title,origin,destination,departure,returning,budget,notes,datetime.utcnow().isoformat()))
   c.commit(); flash('Your trip plan has been saved!')
  except (ValueError, TypeError):
   c.rollback(); flash('Please check the dates and budget. Return date cannot be before departure.','error')
  return redirect(url_for('trip_planner'))
 plans=c.execute('SELECT * FROM trip_plans WHERE user_id=? ORDER BY departure_date,id DESC',(u['id'],)).fetchall()
 return page('My Trip Planner', r'''<section class="hero"><span class="tag">STAGE 10 · TRAVEL & DISCOVERY</span><h1>🧳 My Trip Planner</h1><p>Organise your travel ideas in one place. Save destinations, dates, an optional budget and notes. Your plans are private to your account.</p><span class="tag">SAVED TO YOUR ACCOUNT</span></section>
 <div class="card"><h2>＋ Create a trip plan</h2><form method="post"><label>Trip title</label><input name="title" maxlength="70" placeholder="e.g. Summer holiday" required><div class="grid"><div><label>Leaving from</label><input name="origin" maxlength="80" placeholder="City or airport" required></div><div><label>Going to</label><input name="destination" maxlength="80" placeholder="City or airport" required></div></div><div class="grid"><div><label>Departure date</label><input type="date" name="departure_date" required></div><div><label>Return date (optional)</label><input type="date" name="return_date"></div></div><label>Estimated budget (optional; planning only)</label><input type="number" name="budget" min="0" max="1000000000" step="0.01" placeholder="Enter an amount"><label>Notes / checklist</label><textarea name="notes" maxlength="1200" placeholder="Things to remember, places to visit, packing notes…"></textarea><button>Save trip plan</button></form><p class="muted">This planner does not book tickets, reserve hotels, verify visas or process payments. Do not enter passport numbers, payment details, home addresses or other sensitive information.</p></div>
 <div class="home-section-head"><div><h2>Your saved trips</h2><p>Only you can view and manage these plans.</p></div><span class="tag">{{plans|length}} SAVED</span></div><div class="grid">{% for p in plans %}<article class="card"><span class="tag">TRIP PLAN</span><h3>{{p['title']}}</h3><p><b>{{p['origin']}}</b> → <b>{{p['destination']}}</b></p><p>Depart: {{p['departure_date']}}{% if p['return_date'] %}<br>Return: {{p['return_date']}}{% endif %}</p>{% if p['budget'] is not none %}<p>Estimated budget: {{'%.2f'|format(p['budget'])}}</p>{% endif %}{% if p['notes'] %}<p style="white-space:pre-wrap">{{p['notes']}}</p>{% endif %}<form method="post" action="{{url_for('trip_delete',plan_id=p['id'])}}" onsubmit="return confirm('Delete this saved trip plan?')"><button class="btn alt">Delete plan</button></form></article>{% else %}<div class="card"><h3>Your travel board is empty</h3><p>Create your first trip plan above.</p></div>{% endfor %}</div>''',plans=plans)

@app.route('/trip-planner/<int:plan_id>/delete', methods=['POST'])
@login_required
def trip_delete(plan_id):
 c=db(); cur=c.execute('DELETE FROM trip_plans WHERE id=? AND user_id=?',(plan_id,current_user()['id']))
 c.commit()
 flash('Trip plan deleted.' if cur.rowcount else 'That trip plan was not found.')
 return redirect(url_for('trip_planner'))

@app.route('/flights')
def flights():
 return page('Flight tracking','''<div class="hero"><h1>Live Flight Tracking</h1><p>Real aircraft data only — no invented aircraft markers.</p><span class="tag">LIVE PROVIDER NOT CONNECTED</span></div><div class="card"><h3>Why is the map not showing aircraft?</h3><p>A licensed flight-data provider, written permission and secure API credentials must be configured before real aircraft positions can be displayed. This review build does not pretend demo data is live.</p><p>Offline mode can show saved information, but cannot provide current aircraft positions.</p></div><div class="grid"><div class="card"><h3>Aircraft information</h3><p>Planned: callsign, aircraft identifier, altitude, speed and last update.</p></div><div class="card"><h3>Nigeria airspace</h3><p>Planned provider-backed regional view after permission and integration.</p></div></div>''')
@app.route('/quiz', methods=['GET'])
def quiz():
 return page('Aviation Quiz', r'''<section class="hero"><span class="tag">ATW KNOWLEDGE CHALLENGE</span><h1>🧠 Aviation Quiz</h1><p>10 beginner-friendly aviation questions. Choose an answer to get feedback, then see your final score.</p></section>
<div class="card" id="quizCard"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><span class="tag" id="qProgress">Question 1 of 10</span><strong id="qScore">Score: 0</strong></div><div style="height:8px;background:#18385a;border-radius:20px;margin:16px 0"><div id="qBar" style="height:8px;width:10%;background:#22c8ff;border-radius:20px"></div></div><h2 id="qText">Loading question…</h2><div id="qOptions" class="grid" style="grid-template-columns:1fr 1fr"></div><p id="qFeedback" class="notice" aria-live="polite">Select your answer.</p><button id="qNext" type="button" disabled>Next question →</button></div>
<div class="card" id="quizResult" hidden><h2>Quiz complete!</h2><p id="qFinal" class="balance"></p><p id="qMessage"></p><button type="button" id="qRestart">Play again</button> <a class="btn alt" href="{{url_for('games')}}">Go to Games Arcade</a></div>
<script>
const quizItems=[
 {q:'Which part of an aircraft produces most of its lift during normal flight?',o:['Wings','Landing gear','Tail wheel','Cabin windows'],a:0,e:'The wings are designed to generate most of the lift that supports the aircraft.'},
 {q:'In aviation, what does “ATC” stand for?',o:['Air Traffic Control','Aircraft Travel Cabin','Aviation Terminal Check','Air Transport Cargo'],a:0,e:'ATC means Air Traffic Control, the service that helps manage aircraft movement.'},
 {q:'Which instrument helps a pilot know the aircraft’s altitude?',o:['Altimeter','Compass','Clock','Fuel gauge'],a:0,e:'An altimeter indicates altitude, commonly using atmospheric pressure.'},
 {q:'What is the main purpose of an airport runway?',o:['Aircraft take-off and landing','Passenger shopping','Aircraft painting','Storing luggage'],a:0,e:'Runways are prepared surfaces used for aircraft take-offs and landings.'},
 {q:'Which control surface primarily helps an aircraft roll left or right?',o:['Ailerons','Rudder','Flaps','Elevator'],a:0,e:'Ailerons move differentially on the wings to control roll.'},
 {q:'What does a passenger boarding pass usually show?',o:['Flight and seat details','The pilot’s home address','The aircraft engine serial history','Weather for the whole year'],a:0,e:'A boarding pass normally includes details such as flight number, boarding time and seat.'},
 {q:'Which direction does a compass needle point toward?',o:['Magnetic north','The nearest airport','The equator','The sun at all times'],a:0,e:'A magnetic compass aligns with Earth’s magnetic field and indicates magnetic north.'},
 {q:'What is the purpose of an aircraft’s landing gear?',o:['Support the aircraft on the ground','Generate electrical storms','Control cabin temperature','Measure cloud height'],a:0,e:'Landing gear supports the aircraft during taxi, take-off and landing.'},
 {q:'Which of these is a common international airport code format?',o:['Three letters','Two colours','Six numbers only','A full sentence'],a:0,e:'Many airports use three-letter IATA codes, such as LOS for Lagos.'},
 {q:'What does a seat belt help protect a passenger from?',o:['Unexpected movement or turbulence','Low fuel in the aircraft','Changes in the flight route','Loud engine noise'],a:0,e:'A seat belt helps keep a passenger securely seated during movement and turbulence.'}
];
quizItems.forEach(x=>{const correct=x.o[x.a];for(let i=x.o.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[x.o[i],x.o[j]]=[x.o[j],x.o[i]]}x.a=x.o.indexOf(correct)});
let qi=0,score=0,locked=false;const $=id=>document.getElementById(id);
function showQ(){locked=false;const x=quizItems[qi];$('qProgress').textContent=`Question ${qi+1} of ${quizItems.length}`;$('qScore').textContent=`Score: ${score}`;$('qBar').style.width=`${(qi+1)*10}%`;$('qText').textContent=x.q;$('qFeedback').textContent='Choose one answer.';$('qNext').disabled=true;$('qNext').textContent=qi===quizItems.length-1?'See my result':'Next question →';$('qOptions').innerHTML='';x.o.forEach((v,i)=>{const b=document.createElement('button');b.type='button';b.textContent=v;b.style.textAlign='left';b.addEventListener('click',()=>answer(i,b));$('qOptions').appendChild(b)})}
function answer(i,b){if(locked)return;locked=true;const x=quizItems[qi];if(i===x.a){score++;b.style.borderColor='#4ade80';$('qFeedback').textContent='✅ Correct! '+x.e}else{$('qFeedback').textContent='Not quite. '+x.e;$('qOptions').children[x.a].style.borderColor='#4ade80'}$('qScore').textContent=`Score: ${score}`;$('qNext').disabled=false}
$('qNext').addEventListener('click',()=>{if(!locked)return;if(qi<quizItems.length-1){qi++;showQ()}else{$('quizCard').hidden=true;$('quizResult').hidden=false;$('qFinal').textContent=`${score} / ${quizItems.length}`;$('qMessage').textContent=score>=8?'Excellent flying knowledge!':score>=5?'Good effort — keep learning!':'Good first flight. Try again and improve your score!'}});
$('qRestart').addEventListener('click',()=>{qi=0;score=0;$('quizResult').hidden=true;$('quizCard').hidden=false;showQ()});showQ();
</script>''')

# Stage 11: beginner Flight Academy with account-specific lesson completion.
ACADEMY_LESSONS = [
 ('aviation-basics','1','Aviation Basics','Learn what aviation means, the difference between an aircraft and an airport, and the main parts of a passenger journey.','Aviation is the operation and use of aircraft. An airport is a place where aircraft arrive and depart. A typical passenger journey includes check-in, security screening, boarding, flight and arrival.'),
 ('aircraft-parts','2','Getting to Know an Aircraft','Explore the fuselage, wings, tail, engines and landing gear.','The fuselage is the main body. Wings help generate lift. The tail contributes to stability and control. Engines provide thrust. Landing gear supports the aircraft on the ground.'),
 ('airport-journey','3','Inside an Airport','Understand terminals, gates, runways, taxiways and baggage areas.','A terminal serves passengers. A gate is where passengers wait to board. Runways are used for take-off and landing. Taxiways connect runways with other airport areas. Baggage systems move checked bags.'),
 ('flight-crew','4','Who Works on a Flight?','Meet the flight deck crew, cabin crew, air traffic controllers and ground teams.','Pilots operate the aircraft within approved procedures. Cabin crew look after passenger safety and service. Air traffic controllers provide traffic-management instructions. Ground teams support aircraft turnaround and passenger operations.'),
 ('weather-flight','5','Weather and Flying','Learn why wind, visibility, clouds and storms matter to aviation.','Weather affects flight planning and operations. Pilots and dispatch teams use official forecasts and reports. Airlines may delay, reroute or cancel flights when conditions are unsuitable. Never treat a learning page as live weather guidance.'),
 ('passenger-safety','6','Being a Safe Passenger','Learn the purpose of seat belts, safety briefings, signs and crew instructions.','Listen to the cabin crew safety briefing, read the safety information, follow seat-belt signs and crew instructions, and keep aisles clear. In an actual flight, follow the crew and airline instructions rather than an app or game.')
]

@app.route('/flight-academy', methods=['GET','POST'])
@login_required
def flight_academy():
 c=db(); uid=current_user()['id']
 if request.method=='POST':
  key=(request.form.get('lesson_key') or '').strip()
  lesson=next((x for x in ACADEMY_LESSONS if x[0]==key),None)
  if not lesson:
   flash('That lesson was not found.','error')
  else:
   c.execute('INSERT OR IGNORE INTO academy_progress(user_id,lesson_key,completed_at) VALUES(?,?,?)',(uid,key,datetime.utcnow().isoformat()))
   c.commit(); flash('Lesson marked complete. Great learning!')
  return redirect(url_for('flight_academy'))
 rows=c.execute('SELECT lesson_key FROM academy_progress WHERE user_id=?',(uid,)).fetchall()
 completed={r['lesson_key'] for r in rows}
 lessons=[{'key':x[0],'number':x[1],'title':x[2],'summary':x[3],'content':x[4],'done':x[0] in completed} for x in ACADEMY_LESSONS]
 count=len(completed); total=len(ACADEMY_LESSONS)
 return page('Flight Academy', r"""<section class="hero"><span class="tag">STAGE 11 · FLIGHT ACADEMY</span><h1>✈ Your Flight Academy</h1><p>Learn aviation step by step with six beginner-friendly lessons. Your progress is saved to your own account.</p><div class="notice"><strong>{{count}} / {{total}} lessons completed</strong><div style="height:10px;background:#18385a;border-radius:20px;margin-top:10px;overflow:hidden"><div style="height:100%;width:{{(count/total*100)|round(0)}}%;background:linear-gradient(90deg,#22c8ff,#58e0b5)"></div></div></div></section>
<div class="grid">{% for lesson in lessons %}<article class="card"><div class="tag">LESSON {{lesson.number}} {% if lesson.done %}· COMPLETED ✓{% else %}· READY TO LEARN{% endif %}</div><h2>{{lesson.title}}</h2><p>{{lesson.summary}}</p><details><summary>Open lesson notes</summary><p style="line-height:1.8">{{lesson.content}}</p></details>{% if lesson.done %}<p class="notice">✓ Saved as complete on your account.</p>{% else %}<form method="post"><input type="hidden" name="lesson_key" value="{{lesson.key}}"><button type="submit">Mark lesson complete</button></form>{% endif %}</article>{% endfor %}</div>
<div class="card"><h2>🎓 What’s next?</h2><p>After studying the lessons, test what you remember in the Aviation Quiz.</p><a class="btn" href="{{url_for('quiz')}}">Take Aviation Quiz →</a> <a class="btn alt" href="{{url_for('games')}}">Visit Games Arcade</a>{% if count == total %}<p class="notice">🏅 You completed every lesson! Your personal Flight Academy certificate is ready.</p><a class="btn" href="{{url_for('academy_certificate')}}">View my certificate →</a>{% endif %}</div>
<div class="notice">Learning only: this academy is not pilot training, an aviation licence course, live weather advice or instructions for operating an aircraft. Always follow qualified instructors and official aviation procedures.</div>""", lessons=lessons,count=count,total=total)


# Stage 12: private, account-bound Flight Academy completion certificate.
@app.route('/flight-academy/certificate', methods=['GET','POST'])
@login_required
def academy_certificate():
 c=db(); uid=current_user()['id']
 total=len(ACADEMY_LESSONS)
 placeholders=','.join('?' for _ in ACADEMY_LESSONS)
 keys=[x[0] for x in ACADEMY_LESSONS]
 done=c.execute('SELECT COUNT(*) AS n FROM academy_progress WHERE user_id=? AND lesson_key IN (%s)' % placeholders, (uid, *keys)).fetchone()['n']
 if done != total:
  flash('Complete all six Flight Academy lessons before requesting your certificate.','error')
  return redirect(url_for('flight_academy'))
 cert=c.execute('SELECT certificate_code,issued_at FROM academy_certificates WHERE user_id=?',(uid,)).fetchone()
 if request.method=='POST' and not cert:
  code=secrets.token_urlsafe(12).replace('-','').replace('_','')[:16].upper()
  try:
   c.execute('INSERT INTO academy_certificates(user_id,certificate_code,issued_at) VALUES(?,?,?)',(uid,code,datetime.utcnow().isoformat()))
   c.commit()
  except sqlite3.IntegrityError:
   c.rollback()
  cert=c.execute('SELECT certificate_code,issued_at FROM academy_certificates WHERE user_id=?',(uid,)).fetchone()
 if not cert:
  return page('Flight Academy Certificate', '<section class="card"><h1>🏅 Your certificate is ready</h1><p>You have completed all six beginner lessons.</p><form method="post"><button type="submit">Issue my certificate</button></form></section>')
 issued=cert['issued_at'][:10]; code=cert['certificate_code']
 return page('Flight Academy Certificate', r'''<section class="card" style="max-width:850px;margin:20px auto;text-align:center;border:3px solid #58caff;background:linear-gradient(135deg,#10223e,#18385a);padding:34px"><div class="tag">AIR TRAVEL · FLIGHT ACADEMY</div><h1 style="font-size:clamp(30px,6vw,52px)">🏅 Certificate of Completion</h1><p>This recognises that</p><h2 style="font-size:32px;color:#8eeaff">{{member_name}}</h2><p>has completed all six beginner lessons in the AIR TRAVEL Flight Academy.</p><p><strong>Course:</strong> Aviation Basics · Beginner Level</p><p><strong>Date issued:</strong> {{issued}}</p><p><strong>Certificate code:</strong> {{code}}</p><p class="muted">This is a learning milestone only; it is not a pilot licence, professional qualification or proof of flight training.</p><a class="btn" href="{{url_for('verify_academy_certificate',code=code)}}">Verification page</a> <button type="button" onclick="window.print()">Print / Save as PDF</button></section><style>@media print{header,footer,.notice{display:none!important}body{background:white!important;color:#111!important}.card{break-inside:avoid}}</style>''', member_name=current_user()['name'],issued=issued,code=code)

@app.route('/certificate/verify/<code>')
def verify_academy_certificate(code):
 cert=db().execute('SELECT issued_at FROM academy_certificates WHERE certificate_code=?',(code.strip().upper(),)).fetchone()
 if not cert:
  return page('Certificate Verification','<section class="card"><h1>Certificate not found</h1><p>This code does not match an issued AIR TRAVEL Flight Academy certificate.</p></section>'),404
 return page('Certificate Verification', '<section class="card"><h1>✓ Certificate verified</h1><p>This code matches an AIR TRAVEL Flight Academy beginner-course completion record.</p><p><strong>Issued:</strong> '+cert['issued_at'][:10]+'</p><p>No member name or personal profile details are displayed on this public verification page.</p><p>This is not a pilot licence or professional aviation qualification.</p></section>')

@app.route('/kids/games/score', methods=['POST'])
@kids_required
def kids_game_score():
 data = request.get_json(silent=True) or {}
 game_key = str(data.get('game_key', '')).strip()
 allowed = {'memory_match', 'airport_sequence', 'word_search'}
 raw_score = data.get('score')
 if game_key not in allowed or isinstance(raw_score, bool):
  return {'ok': False, 'error': 'Invalid game result.'}, 400
 try:
  score = int(raw_score)
 except (TypeError, ValueError):
  return {'ok': False, 'error': 'Invalid score.'}, 400
 if score < 0 or score > 100 or str(raw_score).strip() != str(score):
  return {'ok': False, 'error': 'Score must be a whole number from 0 to 100.'}, 400
 uid = current_user()['id']
 now = datetime.utcnow().isoformat()
 c = db()
 c.execute("INSERT INTO kids_extra_game_scores(user_id,game_key,best_score,plays,updated_at) VALUES(?,?,?,1,?) ON CONFLICT(user_id,game_key) DO UPDATE SET best_score=MAX(kids_extra_game_scores.best_score,excluded.best_score),plays=kids_extra_game_scores.plays+1,updated_at=excluded.updated_at", (uid, game_key, score, now))
 row = c.execute('SELECT best_score,plays FROM kids_extra_game_scores WHERE user_id=? AND game_key=?',
                 (uid, game_key)).fetchone()
 c.commit()
 return {'ok': True, 'best_score': row['best_score'], 'plays': row['plays']}

@app.route('/games')
def games():
 u=current_user()
 if u and u['role']=='member' and u['mode']=='kids':
  score_rows=db().execute('SELECT game_key,best_score FROM kids_extra_game_scores WHERE user_id=?',(u['id'],)).fetchall()
  scores={row['game_key']:row['best_score'] for row in score_rows}
  return page('Kids Games', '''<div class="kids-world"><section class="kids-hero"><h1>🎮 Games Corner</h1><p>Play friendly mini-games and take breaks. These are just games, not real flight training.</p></section><section class="kids-card"><h2>⭐ Sky Star Catcher</h2><p>Press Start, then use the left and right arrow keys or buttons to collect stars and avoid clouds.</p><button id="kidStart">Start / Restart</button> <b id="kidScore">Stars: 0</b><canvas id="kidCanvas" width="600" height="300" style="display:block;width:100%;max-width:600px;background:linear-gradient(#a5e4ff,#fff3c9);border-radius:14px;margin-top:12px;touch-action:none"></canvas><p><button id="kidLeft">⬅ Left</button> <button id="kidRight">Right ➡</button></p><p id="kidMsg" aria-live="polite">Ready to play!</p></section><section class="kids-card"><h2>🛬 Perfect Timing</h2><p>Stop the moving marker in the green zone.</p><div style="height:30px;position:relative;background:#dce9f7;border-radius:9px;overflow:hidden"><div style="position:absolute;left:43%;width:14%;height:100%;background:#68d391"></div><div id="kidMarker" style="position:absolute;left:0;width:7px;height:100%;background:#6552b8"></div></div><button id="kidLandStart">Start</button> <button id="kidLandStop" disabled>Stop!</button><p id="kidLandResult">Ready?</p></section>
<section class="kids-card" id="memoryMatchGame"><h2>🧠 Airplane Memory Match</h2><p>Turn over two cards. Find all four matching pairs. Your score is a personal best, not a competition prize.</p><p><b>Best score:</b> <span id="memoryBest">{{scores.get('memory_match',0)}}/100</span> · <b>Moves:</b> <span id="memoryMoves">0</span> · <b>Pairs:</b> <span id="memoryPairs">0/4</span></p><div id="memoryBoard" class="kids-memory-board" aria-label="Memory matching cards"></div><p id="memoryMessage" aria-live="polite">Press New Game to begin.</p><button type="button" id="memoryNew">New Game</button></section>
<section class="kids-card" id="airportSequenceGame"><h2>🧩 Airport Pattern Puzzle</h2><p>Look at the pattern and choose what should come next. Complete five friendly puzzles.</p><p><b>Best score:</b> <span id="sequenceBest">{{scores.get('airport_sequence',0)}}/100</span> · <b>Question:</b> <span id="sequenceNumber">0/5</span></p><h3 id="sequencePrompt">Press Start to play.</h3><div id="sequenceOptions" class="kids-choice-grid"></div><p id="sequenceMessage" aria-live="polite">Ready when you are!</p><button type="button" id="sequenceStart">Start Puzzle</button></section>
<section class="kids-card" id="wordSearchGame"><h2>🔎 Airport Word Search</h2><p>Find AIR, SKY, WING and PILOT. Tap the letters from left to right across each row.</p><p><b>Best score:</b> <span id="wordBest">{{scores.get('word_search',0)}}/100</span> · <b>Words found:</b> <span id="wordFound">0/4</span></p><div id="wordGrid" class="kids-word-grid" aria-label="Letter puzzle"></div><p id="wordMessage" aria-live="polite">Find the four hidden aviation words!</p><button type="button" id="wordReset">Restart Word Search</button></section>
<div id="kidsGameStatus" class="kids-note" role="status" aria-live="polite">Game scores are saved privately to your account. No EXP is spent or awarded.</div>
<a class="btn alt" href="{{url_for('home')}}">← Kids Home</a></div><link rel="stylesheet" href="{{url_for('static',filename='kids_stage25.css')}}"><div id="kidsGameSave" data-endpoint="{{url_for('kids_game_score')}}" data-csrf="{{csrf_token}}"></div><script src="{{url_for('static',filename='kids_games_stage25.js')}}" defer></script><script>(()=>{const c=document.getElementById('kidCanvas'),x=c.getContext('2d'),$=id=>document.getElementById(id);const saveKidsProgress=(activity,payload)=>fetch('{{url_for("kids_save_progress")}}',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'{{csrf_token}}'},body:JSON.stringify({activity,...payload})}).catch(()=>{});let p=300,stars=[],score=0,run=false,keys={},raf=0,last=0,tm=0;function draw(){x.clearRect(0,0,600,300);x.font='28px Arial';stars.forEach(a=>x.fillText(a.star?'⭐':'☁️',a.x,a.y));x.font='38px Arial';x.fillText('🛩️',p-18,270)}function loop(t){if(!run)return;let d=Math.min(.05,(t-last)/1000||0);last=t;if(keys.left)p-=220*d;if(keys.right)p+=220*d;p=Math.max(20,Math.min(580,p));tm+=d;if(tm>.7){tm=0;stars.push({x:20+Math.random()*560,y:-10,star:Math.random()>.3})}stars.forEach(a=>a.y+=110*d);stars=stars.filter(a=>{if(a.y>250&&a.y<280&&Math.abs(a.x-p)<30){if(a.star)score++;else{run=false;saveKidsProgress('sky_stars',{score});$('kidMsg').textContent='A cloud bumped the plane. Stars: '+score+' · Best score saved to your progress';return false}return false}return a.y<320});$('kidScore').textContent='Stars: '+score;draw();if(run)raf=requestAnimationFrame(loop)}function start(){cancelAnimationFrame(raf);p=300;stars=[];score=0;tm=0;last=performance.now();run=true;$('kidMsg').textContent='Collect stars!';raf=requestAnimationFrame(loop)}$('kidStart').onclick=start;function hold(id,k){const b=$(id);b.onpointerdown=e=>{e.preventDefault();keys[k]=true};['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>keys[k]=false))}hold('kidLeft','left');hold('kidRight','right');window.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')keys.left=true;if(e.key==='ArrowRight')keys.right=true});window.addEventListener('keyup',e=>{if(e.key==='ArrowLeft')keys.left=false;if(e.key==='ArrowRight')keys.right=false});draw();let pos=0,dir=1,active=false,anim=0;function move(){if(!active)return;pos+=dir*1.8;if(pos>98||pos<0)dir*=-1;$('kidMarker').style.left=pos+'%';anim=requestAnimationFrame(move)}$('kidLandStart').onclick=()=>{pos=0;dir=1;active=true;$('kidLandStart').disabled=true;$('kidLandStop').disabled=false;move()};$('kidLandStop').onclick=()=>{active=false;cancelAnimationFrame(anim);$('kidLandStart').disabled=false;$('kidLandStop').disabled=true;const success=pos>=43&&pos<=57;$('kidLandResult').textContent=success?'🌟 Great timing! Your win is saved.':'💜 Nice try. Try again!';if(success)saveKidsProgress('perfect_timing',{success:true});};})();</script>''',scores=scores)
 return page('Games Arcade', r'''<section class="hero"><span class="tag">ATW ARCADE · PLAY IN YOUR BROWSER</span><h1>🎮 Air Travel Games Arcade</h1><p>Two playable mini-games. Use your keyboard or touch controls. No downloads or external game accounts needed.</p></section>
<div class="grid"><section class="card"><h2>🌤 Sky Dodger</h2><p>Move your aircraft left and right to collect stars and avoid clouds. Survive for 30 seconds!</p><div style="display:flex;gap:10px;flex-wrap:wrap"><button id="skyStart">Start / Restart</button><strong id="skyScore">Score: 0</strong><strong id="skyTime">Time: 30s</strong></div><canvas id="skyCanvas" width="640" height="360" style="width:100%;max-width:640px;background:linear-gradient(#6ac7f4,#e5f7ff);border:2px solid #39bfff;border-radius:14px;margin-top:12px;touch-action:none"></canvas><div style="display:flex;justify-content:center;gap:18px;margin-top:10px"><button id="skyLeft" aria-label="Move left">⬅ Left</button><button id="skyRight" aria-label="Move right">Right ➡</button></div><p class="muted" id="skyMsg" aria-live="polite">Press Start. Keyboard: ← → or A / D.</p></section>
<section class="card"><h2>🛬 Perfect Landing</h2><p>Stop the moving marker inside the green landing zone. This is an arcade timing game, not real flight training.</p><div style="font-size:15px;margin:14px 0">Landing approach speed: <strong id="landSpeed">0</strong></div><div style="height:34px;background:#18385a;border:2px solid #58caff;border-radius:10px;position:relative;overflow:hidden"><div style="position:absolute;left:43%;width:14%;height:100%;background:#24a85a;opacity:.85"></div><div id="landMarker" style="position:absolute;left:0;width:8px;height:100%;background:#fff;box-shadow:0 0 8px #fff"></div></div><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px"><button id="landStart">Start approach</button><button id="landStop" disabled>Land now!</button></div><h3 id="landResult" aria-live="polite">Ready for your approach?</h3><p class="muted">Tip: press “Land now!” when the marker is inside the green zone.</p></section></div>
<div class="card"><h2>🏙 Airport Tycoon</h2><p>Build terminals, gates and runways, then collect one daily virtual airport income reward.</p><a class="btn" href="{{url_for('tycoon')}}">Play Airport Tycoon</a></div><div class="card"><h2>🏆 More challenges coming to ATW</h2><p>Sky Dodger, Perfect Landing and Airport Tycoon are playable locally. Multiplayer and shared online leaderboards need additional server features and are not switched on yet.</p></div>
<script>
(()=>{const c=document.getElementById('skyCanvas'),ctx=c.getContext('2d'),$=id=>document.getElementById(id);let running=false,player=320,items=[],score=0,time=30,last=0,raf=0,keys={},spawn=0;
function draw(){ctx.clearRect(0,0,c.width,c.height);ctx.fillStyle='#ffffff';for(let i=0;i<8;i++){let x=(i*97+40)%640,y=(i*61+20)%340;ctx.beginPath();ctx.arc(x,y,15,0,Math.PI*2);ctx.fill()}items.forEach(o=>{ctx.fillStyle=o.type==='star'?'#ffb900':'#64748b';ctx.beginPath();ctx.arc(o.x,o.y,o.r,0,Math.PI*2);ctx.fill();ctx.fillStyle=o.type==='star'?'#fff7c2':'#e2e8f0';ctx.fillText(o.type==='star'?'★':'☁',o.x-8,o.y+5)});ctx.font='34px Arial';ctx.fillText('✈️',player-18,315)}
function end(msg){running=false;cancelAnimationFrame(raf);$('skyMsg').textContent=msg;$('skyStart').disabled=false}
function loop(ts){if(!running)return;let dt=Math.min(.05,(ts-last)/1000||0);last=ts;time-=dt;if(keys.ArrowLeft||keys.a||keys.A)player-=260*dt;if(keys.ArrowRight||keys.d||keys.D)player+=260*dt;player=Math.max(20,Math.min(620,player));spawn+=dt;if(spawn>.7){spawn=0;items.push({x:25+Math.random()*590,y:-10,r:14,type:Math.random()>.42?'star':'cloud',v:105+Math.random()*85})}items.forEach(o=>o.y+=o.v*dt);items=items.filter(o=>{if(o.y>300&&o.y<335&&Math.abs(o.x-player)<27){if(o.type==='star'){score+=10;return false}else{end('A cloud bumped your plane! Final score: '+score);return false}}return o.y<380});$('skyScore').textContent='Score: '+score;$('skyTime').textContent='Time: '+Math.max(0,Math.ceil(time))+'s';draw();if(!running)return;if(time<=0){end('Time up! Final score: '+score);return}raf=requestAnimationFrame(loop)}
function start(){cancelAnimationFrame(raf);running=true;player=320;items=[];score=0;time=30;spawn=0;last=performance.now();$('skyStart').disabled=true;$('skyMsg').textContent='Fly carefully and collect the stars!';raf=requestAnimationFrame(loop)}
$('skyStart').addEventListener('click',start);window.addEventListener('keydown',e=>{keys[e.key]=true;if(['ArrowLeft','ArrowRight',' '].includes(e.key))e.preventDefault()});window.addEventListener('keyup',e=>keys[e.key]=false);function hold(id,key){const b=$(id);b.addEventListener('pointerdown',e=>{e.preventDefault();keys[key]=true});['pointerup','pointerleave','pointercancel'].forEach(ev=>b.addEventListener(ev,()=>keys[key]=false))}hold('skyLeft','ArrowLeft');hold('skyRight','ArrowRight');draw();
let landX=0,landDir=1,landTimer=null,landActive=false;function moveLand(){if(!landActive)return;landX+=landDir*1.7;if(landX>98||landX<0)landDir*=-1;$('landMarker').style.left=landX+'%';$('landSpeed').textContent=Math.round(landX*2.4)+' km/h';landTimer=requestAnimationFrame(moveLand)}$('landStart').addEventListener('click',()=>{cancelAnimationFrame(landTimer);landX=0;landDir=1;landActive=true;$('landResult').textContent='Approach started — watch the marker.';$('landStart').disabled=true;$('landStop').disabled=false;moveLand()});$('landStop').addEventListener('click',()=>{if(!landActive)return;landActive=false;cancelAnimationFrame(landTimer);$('landStart').disabled=false;$('landStop').disabled=true;$('landResult').textContent=landX>=43&&landX<=57?'🟢 Smooth landing! Great timing.':'🟠 Landing missed the target. Try again!'});
})();
</script>''')
@app.route('/world')
def world():
 destinations=[('Lagos','Nigeria','🇳🇬'),('Abuja','Nigeria','🇳🇬'),('London','United Kingdom','🇬🇧'),('Paris','France','🇫🇷'),('Dubai','United Arab Emirates','🇦🇪'),('New York','United States','🇺🇸'),('Tokyo','Japan','🇯🇵'),('Cape Town','South Africa','🇿🇦')]
 return page('ATW World','''<section class="hero"><span class="tag">ATW UNIVERSE</span><h1>🌍 Explore the world</h1><p>Spin the globe, discover destinations and collect virtual passport stamps. This is an educational game map, not live aircraft tracking.</p></section>
 <style>.globe-wrap{display:grid;place-items:center;padding:26px}.globe{width:min(66vw,310px);aspect-ratio:1;border-radius:50%;background:radial-gradient(circle at 32% 28%,#8eeaff 0 4%,#167bd0 24%,#064078 63%,#02152f 100%);box-shadow:inset -22px -18px 40px #0009,0 0 45px #1daaff66;position:relative;overflow:hidden;border:2px solid #67d8ff}.globe:before{content:' ';position:absolute;inset:-15%;border-radius:50%;background:repeating-linear-gradient(90deg,transparent 0 29px,#b9f5ff55 30px 31px,transparent 32px 60px);animation:spinGlobe 12s linear infinite}.globe:after{content:'🌍';position:absolute;inset:0;display:grid;place-items:center;font-size:150px;filter:drop-shadow(0 8px 12px #001)}@keyframes spinGlobe{to{transform:rotate(360deg)}}.dest-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.dest{background:#0a2342;border:1px solid #23669b;border-radius:13px;padding:13px}.dest form{margin-top:9px}</style>
 <div class="card globe-wrap"><div class="globe" aria-label="Decorative rotating globe"></div><p class="muted">A world of destinations is waiting for you.</p></div><div class="card"><h2>Destination Explorer</h2><p>Sign in to add a destination stamp to your digital passport.</p><div class="dest-grid">{% for city,country,flag in destinations %}<div class="dest"><div style="font-size:25px">{{flag}}</div><b>{{city}}</b><div class="muted">{{country}}</div>{% if user %}<form method="post" action="{{url_for('passport_stamp')}}"><input type="hidden" name="destination" value="{{city}}"><input type="hidden" name="country" value="{{country}}"><button type="submit">Collect stamp</button></form>{% else %}<a href="{{url_for('login')}}">Sign in to collect</a>{% endif %}</div>{% endfor %}</div></div>''',destinations=destinations)

@app.route('/passport')
@login_required
def passport():
 stamps=db().execute('SELECT destination,country,stamped_at FROM passport_stamps WHERE user_id=? ORDER BY stamped_at DESC',(current_user()['id'],)).fetchall()
 return page('Digital Passport','''<section class="hero"><span class="tag">YOUR ATW JOURNEY</span><h1>🛂 Digital Passport</h1><p>Collect virtual stamps by exploring destinations in ATW World.</p><p class="balance">{{stamps|length}} destinations collected</p><a class="btn" href="{{url_for('world')}}">Explore destinations</a></section><div class="grid">{% for s in stamps %}<div class="card"><h3>📍 {{s['destination']}}</h3><p>{{s['country']}}</p><small class="muted">Collected {{s['stamped_at'][:10]}}</small><div class="tag">ATW STAMP</div></div>{% else %}<div class="card"><h3>Your passport is waiting!</h3><p>Visit ATW World and collect your first destination stamp.</p></div>{% endfor %}</div>''',stamps=stamps)

@app.route('/passport/stamp',methods=['POST'])
@login_required
def passport_stamp():
 u=current_user(); city=request.form.get('destination','')[:60]; country=request.form.get('country','')[:60]
 allowed={'Lagos':'Nigeria','Abuja':'Nigeria','London':'United Kingdom','Paris':'France','Dubai':'United Arab Emirates','New York':'United States','Tokyo':'Japan','Cape Town':'South Africa'}
 if allowed.get(city)!=country:
  flash('That destination is not available in the passport yet.','error')
 else:
  try:
   db().execute('INSERT INTO passport_stamps(user_id,destination,country,stamped_at) VALUES(?,?,?,?)',(u['id'],city,country,datetime.utcnow().isoformat())); db().commit(); flash(f'Passport stamp collected: {city}!')
  except sqlite3.IntegrityError: flash(f'You already collected the {city} stamp.','error')
 return redirect(url_for('passport'))

@app.route('/tycoon',methods=['GET','POST'])
@login_required
def tycoon():
 u=current_user(); c=db(); c.execute('INSERT OR IGNORE INTO airport_state(user_id) VALUES(?)',(u['id'],)); c.commit()
 if request.method=='POST':
  action=request.form.get('action'); costs={'terminal':200,'gates':150,'runway':300}
  if action in costs:
   cost=costs[action]
   try:
    # Lock the wallet row and the upgrade together so simultaneous requests
    # cannot overspend or grant an upgrade without its matching ledger entry.
    c.execute('BEGIN IMMEDIATE')
    fresh=c.execute('SELECT role,exp FROM users WHERE id=?',(u['id'],)).fetchone()
    if not fresh: raise ValueError('Member account not found.')
    if fresh['role']!='owner' and fresh['exp']<cost:
     raise ValueError('Not enough EXP for this upgrade. Play games and quizzes to earn more.')
    if fresh['role']!='owner':
     changed=c.execute('UPDATE users SET exp=exp-? WHERE id=? AND exp>=?',(cost,u['id'],cost)).rowcount
     if changed!=1: raise ValueError('Your EXP balance changed. Please try again.')
     c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(u['id'],-cost,'Airport Tycoon: '+action,datetime.utcnow().isoformat()))
    c.execute(f'UPDATE airport_state SET {action}={action}+1 WHERE user_id=?',(u['id'],))
    c.commit(); flash(f'Airport upgraded: {action.title()} level increased!')
   except ValueError as e:
    c.rollback(); flash(str(e),'error')
   except sqlite3.Error:
    c.rollback(); app.logger.exception('Airport upgrade transaction failed'); flash('The upgrade could not be completed. No EXP was deducted. Please try again.','error')
  elif action=='income':
   today=datetime.now(timezone(timedelta(hours=1))).date().isoformat()
   try:
    c.execute('BEGIN IMMEDIATE'); state=c.execute('SELECT * FROM airport_state WHERE user_id=?',(u['id'],)).fetchone()
    if state['last_income_date']==today:
     c.rollback(); flash('Airport income has already been collected today.','error')
    else:
     amount=50+state['terminal']*30+state['gates']*20+state['runway']*40
     c.execute('UPDATE users SET exp=exp+? WHERE id=?',(amount,u['id'])); c.execute('UPDATE airport_state SET last_income_date=? WHERE user_id=?',(today,u['id'])); c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(u['id'],amount,'Airport Tycoon daily virtual income',datetime.utcnow().isoformat())); c.commit(); flash(f'Your airport earned {amount:,} EXP today!')
   except Exception:
    c.rollback(); raise
  return redirect(url_for('tycoon'))
 state=c.execute('SELECT * FROM airport_state WHERE user_id=?',(u['id'],)).fetchone(); return page('Airport Tycoon','''<section class="hero"><span class="tag">BUILD · UPGRADE · COLLECT</span><h1>🏙 Airport Tycoon</h1><p>Build a virtual airport with terminals, gates and runways. Earn one daily virtual income reward. This is a game economy, not real money.</p><p class="balance">{{'{:,}'.format(user['exp'])}} EXP</p></section><div class="grid"><div class="card"><h3>🏢 Terminal</h3><p>Level: <b>{{state['terminal']}}</b></p><p>Cost: 200 EXP</p><form method="post"><input type="hidden" name="action" value="terminal"><button>Upgrade terminal</button></form></div><div class="card"><h3>🚪 Gates</h3><p>Level: <b>{{state['gates']}}</b></p><p>Cost: 150 EXP</p><form method="post"><input type="hidden" name="action" value="gates"><button>Build gates</button></form></div><div class="card"><h3>🛫 Runway</h3><p>Level: <b>{{state['runway']}}</b></p><p>Cost: 300 EXP</p><form method="post"><input type="hidden" name="action" value="runway"><button>Extend runway</button></form></div></div><div class="card"><h2>Daily airport income</h2><p>Base 50 EXP + bonuses for each upgrade level.</p><form method="post"><input type="hidden" name="action" value="income"><button>Collect today's airport income</button></form><p class="muted">One claim per day. Owner account can preview upgrades without EXP deduction.</p></div>''',state=state)

@app.route('/wheel',methods=['GET','POST'])
@login_required
def wheel():
 u=current_user(); c=db(); today=datetime.now(timezone(timedelta(hours=1))).date().isoformat()
 if request.method=='POST':
  amount=secrets.choice([25,50,50,75,100,150])
  try:
   c.execute('BEGIN IMMEDIATE'); c.execute('INSERT INTO wheel_claims(user_id,claim_date,amount,created_at) VALUES(?,?,?,?)',(u['id'],today,amount,datetime.utcnow().isoformat()))
   if u['role']!='owner':
    c.execute('UPDATE users SET exp=exp+? WHERE id=?',(amount,u['id'])); c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(u['id'],amount,'Free daily EXP wheel',datetime.utcnow().isoformat()))
   c.commit(); flash(f'Your free daily spin won {amount} EXP!')
  except sqlite3.IntegrityError: c.rollback(); flash('You have already used today’s free spin. Come back tomorrow.','error')
 claim=c.execute('SELECT amount FROM wheel_claims WHERE user_id=? AND claim_date=?',(u['id'],today)).fetchone()
 return page('Daily EXP Wheel','''<section class="hero"><span class="tag">FREE DAILY REWARD</span><h1>🎡 EXP Wheel</h1><p>One free spin each day. Rewards are virtual EXP only. There are no paid spins or cash prizes.</p><div class="balance">{{'{:,}'.format(user['exp'])}} EXP</div></section><div class="card" style="text-align:center"><style>@keyframes atwSpin{to{transform:rotate(1440deg)}}.wheel-spinning{animation:atwSpin 1.8s cubic-bezier(.15,.7,.2,1) both}</style><div id="wheelFace" class="{{'wheel-spinning' if claim else ''}}" style="margin:15px auto 22px;width:min(72vw,290px);aspect-ratio:1;border-radius:50%;border:8px solid #70dfff;background:conic-gradient(#0b83d8 0 60deg,#08264c 60deg 120deg,#18a9e7 120deg 180deg,#08264c 180deg 240deg,#0b83d8 240deg 300deg,#08264c 300deg);display:grid;place-items:center;font-size:28px;font-weight:900;box-shadow:0 0 30px #1aaeff66">ATW</div><p>Possible rewards: 25 · 50 · 75 · 100 · 150 EXP</p>{% if claim %}<h2>Today's reward: {{claim['amount']}} EXP</h2><p>Come back tomorrow for another free spin.</p>{% else %}<form method="post"><button id="spinBtn">Spin free wheel</button></form>{% endif %}</div>''',claim=claim)

@app.route('/achievements')
@login_required
def achievements():
 u=current_user(); c=db(); stamps=c.execute('SELECT COUNT(*) n FROM passport_stamps WHERE user_id=?',(u['id'],)).fetchone()['n']; state=c.execute('SELECT * FROM airport_state WHERE user_id=?',(u['id'],)).fetchone(); level=0 if not state else state['terminal']+state['gates']+state['runway']; leaders=c.execute("SELECT name,exp FROM users WHERE role='member' ORDER BY exp DESC LIMIT 10").fetchall()
 badges=[('First Destination','Collect your first passport stamp.',stamps>=1),('World Explorer','Collect five destination stamps.',stamps>=5),('Airport Builder','Upgrade your airport for the first time.',level>=1),('Airport Architect','Reach five total airport upgrade levels.',level>=5),('EXP Collector','Reach 5,000 EXP.',u['exp']>=5000)]
 return page('Achievement Wall','''<section class="hero"><span class="tag">YOUR ATW MILESTONES</span><h1>🏆 Achievement Wall</h1><p>Collect stamps, build your airport and grow your EXP balance.</p></section><div class="grid">{% for title,desc,unlocked in badges %}<div class="card"><div style="font-size:30px">{{'🏅' if unlocked else '🔒'}}</div><h3>{{title}}</h3><p>{{desc}}</p><span class="tag">{{'UNLOCKED' if unlocked else 'LOCKED'}}</span></div>{% endfor %}</div><div class="card"><h2>🌟 ATW EXP Leaderboard</h2><p class="muted">Top 10 member accounts by current EXP. Owner accounts are not ranked here.</p><ol class="list">{% for m in leaders %}<li>{{m['name']}} — {{'{:,}'.format(m['exp'])}} EXP</li>{% else %}<li>No member scores yet.</li>{% endfor %}</ol></div>''',badges=badges,leaders=leaders)


# Stage 21 — Owner HQ Kids World Studio. This manages only original text content
# and the Kids practice question bank; movie files remain local to a user's device.
@app.route('/owner/kids-studio')
@owner_required
def owner_kids_studio():
 c=db()
 stories=c.execute('SELECT * FROM kids_stories ORDER BY id DESC').fetchall()
 questions=c.execute('SELECT * FROM kids_exam_questions ORDER BY id DESC').fetchall()
 stats=c.execute('SELECT COUNT(*) attempts, COALESCE(AVG(CASE WHEN total>0 THEN score*100.0/total END),0) average_score FROM kids_exam_attempts').fetchone()
 activity_stats=c.execute('SELECT activity_type,COALESCE(SUM(completed_count),0) total FROM kids_activity_progress GROUP BY activity_type').fetchall()
 activity_totals={r['activity_type']:r['total'] for r in activity_stats}
 return page('Kids World Studio', r'''<section class="hero"><span class="tag">OWNER HQ · STAGE 22</span><h1>🌈 Kids World Studio</h1><p>Manage the original storybook library and the Kids practice exam from one private Owner HQ page.</p></section>
 <div class="grid"><div class="card"><h2>📚 Story Books</h2><p><b>{{stories|length}}</b> stories · <b>{{stories|selectattr('is_published')|list|length}}</b> published</p><p>Add original stories, update their wording and publish or unpublish them. Unpublished stories are hidden from Kids accounts.</p></div><div class="card"><h2>📝 Practice Exam</h2><p><b>{{questions|length}}</b> questions · <b>{{questions|selectattr('is_published')|list|length}}</b> published</p><p>Maintain a three-option multiple-choice question bank. Correct answers are stored server-side and not displayed on the Kids page.</p></div><div class="card"><h2>📊 Learning activity</h2><p><b>{{stats['attempts']}}</b> exam attempts recorded.</p><p>Average score: {{'%.1f'|format(stats['average_score'])}}%.</p><p>Stories marked read: <b>{{activity_totals.get('story',0)}}</b> · Games completed: <b>{{activity_totals.get('sky_stars',0)}}</b> · Perfect Timing wins: <b>{{activity_totals.get('perfect_timing',0)}}</b></p><small>Aggregate statistics only; no individual member details are shown here.</small></div></div>
 <section class="card"><h2>➕ Add a Story Book</h2><form method="post" action="{{url_for('owner_kids_story_save')}}"><label>Story title</label><input name="title" minlength="3" maxlength="80" required><label>Story emoji</label><input name="emoji" maxlength="8" value="📘"><label>Story text (separate paragraphs with a blank line)</label><textarea name="content" minlength="60" maxlength="3000" rows="8" required></textarea><button>Save and publish story</button></form></section>
 <section class="card"><h2>Manage Story Books</h2>{% for st in stories %}<details style="border-top:1px solid #245078;padding:12px 0"><summary><b>{{st['emoji']}} {{st['title']}}</b> · {{'PUBLISHED' if st['is_published'] else 'UNPUBLISHED'}}</summary><form method="post" action="{{url_for('owner_kids_story_update',story_id=st['id'])}}"><label>Title</label><input name="title" value="{{st['title']}}" minlength="3" maxlength="80" required><label>Emoji</label><input name="emoji" value="{{st['emoji']}}" maxlength="8"><label>Story text (blank line between paragraphs)</label><textarea name="content" rows="7" minlength="60" maxlength="3000" required>{{st['content_json']|fromjson|join('\n\n')}}</textarea><button>Save changes</button></form><form method="post" action="{{url_for('owner_kids_story_toggle',story_id=st['id'])}}"><button class="btn alt">{{'Unpublish' if st['is_published'] else 'Publish'}}</button></form></details>{% else %}<p>No stories yet.</p>{% endfor %}</section>
 <section class="card"><h2>➕ Add an Exam Question</h2><form method="post" action="{{url_for('owner_kids_question_save')}}"><label>Question</label><textarea name="question" minlength="8" maxlength="240" required></textarea><div class="grid"><div><label>Option A</label><input name="option_a" maxlength="120" required></div><div><label>Option B</label><input name="option_b" maxlength="120" required></div><div><label>Option C</label><input name="option_c" maxlength="120" required></div></div><label>Correct answer</label><select name="correct_index"><option value="0">Option A</option><option value="1">Option B</option><option value="2">Option C</option></select><label>Simple explanation (shown after the exam is submitted)</label><textarea name="explanation" minlength="10" maxlength="400" rows="3" required placeholder="Explain why the correct answer is right."></textarea><button>Save and publish question</button></form></section>
 <section class="card"><h2>Manage Exam Questions</h2>{% for q in questions %}<details style="border-top:1px solid #245078;padding:12px 0"><summary><b>{{q['question']}}</b> · {{'PUBLISHED' if q['is_published'] else 'UNPUBLISHED'}}</summary>{% set opts=q['options_json']|fromjson %}<form method="post" action="{{url_for('owner_kids_question_update',question_id=q['id'])}}"><label>Question</label><textarea name="question" minlength="8" maxlength="240" required>{{q['question']}}</textarea><div class="grid"><div><label>Option A</label><input name="option_a" value="{{opts[0]}}" maxlength="120" required></div><div><label>Option B</label><input name="option_b" value="{{opts[1]}}" maxlength="120" required></div><div><label>Option C</label><input name="option_c" value="{{opts[2]}}" maxlength="120" required></div></div><label>Correct answer</label><select name="correct_index">{% for i in range(3) %}<option value="{{i}}" {{'selected' if i==q['correct_index'] else ''}}>Option {{'ABC'[i]}}</option>{% endfor %}</select><label>Simple explanation (shown after the exam is submitted)</label><textarea name="explanation" minlength="10" maxlength="400" rows="3" required>{{q['explanation'] or "This is the correct answer. Explain why it is right."}}</textarea><button>Save question</button></form><form method="post" action="{{url_for('owner_kids_question_toggle',question_id=q['id'])}}"><button class="btn alt">{{'Unpublish' if q['is_published'] else 'Publish'}}</button></form></details>{% else %}<p>No questions yet.</p>{% endfor %}</section>
 <div class="notice">Kids World remains limited to Story Books, Movie Night, Games and Exam. Movie Night still plays a parent/guardian-approved video selected locally on the device; this Studio does not upload, host or distribute films. Only publish original child-appropriate content. Never add children's names, contact details, school information or other private information to stories or questions.</div>
 <a class="btn alt" href="{{url_for('owner_dashboard')}}">← Back to Owner HQ</a>''', stories=stories, questions=questions, stats=stats,activity_totals=activity_totals)

@app.route('/owner/kids-studio/story/save', methods=['POST'])
@owner_required
def owner_kids_story_save():
 title=(request.form.get('title') or '').strip(); emoji=(request.form.get('emoji') or '📘').strip()[:8]
 paragraphs=[p.strip() for p in re.split(r'\n\s*\n', (request.form.get('content') or '').strip()) if p.strip()]
 content='\n\n'.join(paragraphs)
 if not 3<=len(title)<=80 or not 60<=len(content)<=3000 or not 2<=len(paragraphs)<=12 or any(len(p)>700 for p in paragraphs):
  flash('Check the story title and text. Use 2–12 paragraphs and 60–3,000 characters.','error'); return redirect(url_for('owner_kids_studio'))
 slug=re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-')[:48] or 'kids-story'
 c=db()
 if c.execute('SELECT 1 FROM kids_stories WHERE slug=?',(slug,)).fetchone(): slug=f'{slug}-{secrets.token_hex(2)}'
 now=datetime.utcnow().isoformat()
 c.execute('INSERT INTO kids_stories(slug,title,emoji,content_json,is_published,created_at,updated_at) VALUES(?,?,?,?,1,?,?)',(slug,title,emoji,json.dumps(paragraphs,ensure_ascii=False),now,now)); c.commit()
 audit_owner_action('kids_story_created',None,title); c.commit(); flash('Story saved and published in Kids World.'); return redirect(url_for('owner_kids_studio'))

@app.route('/owner/kids-studio/story/<int:story_id>/update', methods=['POST'])
@owner_required
def owner_kids_story_update(story_id):
 title=(request.form.get('title') or '').strip(); emoji=(request.form.get('emoji') or '📘').strip()[:8]
 paragraphs=[p.strip() for p in re.split(r'\n\s*\n', (request.form.get('content') or '').strip()) if p.strip()]
 content='\n\n'.join(paragraphs); c=db()
 if not 3<=len(title)<=80 or not 60<=len(content)<=3000 or not 2<=len(paragraphs)<=12 or any(len(p)>700 for p in paragraphs):
  flash('Check the story title and text. Use 2–12 paragraphs and 60–3,000 characters.','error'); return redirect(url_for('owner_kids_studio'))
 row=c.execute('SELECT slug FROM kids_stories WHERE id=?',(story_id,)).fetchone()
 if not row: abort(404)
 c.execute('UPDATE kids_stories SET title=?,emoji=?,content_json=?,updated_at=? WHERE id=?',(title,emoji,json.dumps(paragraphs,ensure_ascii=False),datetime.utcnow().isoformat(),story_id))
 audit_owner_action('kids_story_updated',None,title); c.commit(); flash('Story updated.'); return redirect(url_for('owner_kids_studio'))

@app.route('/owner/kids-studio/story/<int:story_id>/toggle', methods=['POST'])
@owner_required
def owner_kids_story_toggle(story_id):
 c=db(); row=c.execute('SELECT title,is_published FROM kids_stories WHERE id=?',(story_id,)).fetchone()
 if not row: abort(404)
 new_status=0 if row['is_published'] else 1
 c.execute('UPDATE kids_stories SET is_published=?,updated_at=? WHERE id=?',(new_status,datetime.utcnow().isoformat(),story_id))
 audit_owner_action('kids_story_published' if new_status else 'kids_story_unpublished',None,row['title']); c.commit(); flash('Story '+('published.' if new_status else 'unpublished.')); return redirect(url_for('owner_kids_studio'))

def _kids_question_values(form):
 question=(form.get('question') or '').strip()
 options=[(form.get('option_a') or '').strip(),(form.get('option_b') or '').strip(),(form.get('option_c') or '').strip()]
 explanation=(form.get('explanation') or '').strip()
 try: correct=int(form.get('correct_index','-1'))
 except (TypeError,ValueError): correct=-1
 if not 8<=len(question)<=240 or any(not 1<=len(x)<=120 for x in options) or len({x.casefold() for x in options})<3 or correct not in (0,1,2) or not 10<=len(explanation)<=400:
  return None
 return question,options,correct,explanation

@app.route('/owner/kids-studio/question/save', methods=['POST'])
@owner_required
def owner_kids_question_save():
 values=_kids_question_values(request.form)
 if not values:
  flash('Check the question, three different answer options and correct answer.','error'); return redirect(url_for('owner_kids_studio'))
 q,opts,correct,explanation=values; now=datetime.utcnow().isoformat(); c=db()
 c.execute('INSERT INTO kids_exam_questions(question,options_json,correct_index,is_published,created_at,updated_at,explanation) VALUES(?,?,?,1,?,?,?)',(q,json.dumps(opts,ensure_ascii=False),correct,now,now,explanation))
 audit_owner_action('kids_exam_question_created',None,q); c.commit(); flash('Question added to the Kids practice exam.'); return redirect(url_for('owner_kids_studio'))

@app.route('/owner/kids-studio/question/<int:question_id>/update', methods=['POST'])
@owner_required
def owner_kids_question_update(question_id):
 values=_kids_question_values(request.form); c=db()
 if not values:
  flash('Check the question, three different answer options and correct answer.','error'); return redirect(url_for('owner_kids_studio'))
 if not c.execute('SELECT 1 FROM kids_exam_questions WHERE id=?',(question_id,)).fetchone(): abort(404)
 q,opts,correct,explanation=values
 c.execute('UPDATE kids_exam_questions SET question=?,options_json=?,correct_index=?,updated_at=?,explanation=? WHERE id=?',(q,json.dumps(opts,ensure_ascii=False),correct,datetime.utcnow().isoformat(),explanation,question_id))
 audit_owner_action('kids_exam_question_updated',None,q); c.commit(); flash('Exam question updated.'); return redirect(url_for('owner_kids_studio'))

@app.route('/owner/kids-studio/question/<int:question_id>/toggle', methods=['POST'])
@owner_required
def owner_kids_question_toggle(question_id):
 c=db(); row=c.execute('SELECT question,is_published FROM kids_exam_questions WHERE id=?',(question_id,)).fetchone()
 if not row: abort(404)
 new_status=0 if row['is_published'] else 1
 if not new_status and c.execute('SELECT COUNT(*) FROM kids_exam_questions WHERE is_published=1').fetchone()[0]<=1:
  flash('Keep at least one published exam question.','error'); return redirect(url_for('owner_kids_studio'))
 c.execute('UPDATE kids_exam_questions SET is_published=?,updated_at=? WHERE id=?',(new_status,datetime.utcnow().isoformat(),question_id))
 audit_owner_action('kids_exam_question_published' if new_status else 'kids_exam_question_unpublished',None,row['question']); c.commit(); flash('Exam question '+('published.' if new_status else 'unpublished.')); return redirect(url_for('owner_kids_studio'))


KIDS_STORIES=[
 ('little-plane','The Little Plane’s First Adventure','✈️',['Pip was a little blue plane who loved looking at the clouds. One morning, Pip felt nervous about visiting a new airport.','“You can learn one small thing at a time,” said Captain Ada. Pip listened, asked questions and followed the airport team’s instructions.','At sunset, Pip smiled. The biggest adventure was learning to be curious, patient and kind.']),
 ('moon-airport','Mila and the Moonlight Airport','🌙',['Mila imagined a tiny airport on the moon, with silver runways and glowing flowers.','The airport helpers worked together. When a visitor felt lost, Mila made a bright sign with a friendly arrow.','Mila learned that a little kindness can make any place feel welcoming.']),
 ('helpful-cloud','The Cloud That Wanted to Help','☁️',['Cloudy was a small white cloud who wanted to help a sunny town.','Cloudy learned that gentle rain helps gardens grow. Together, the clouds made a soft shower and the plants lifted their leaves.','Cloudy discovered that everyone can help in their own way.']),
 ('teddy-trip','Teddy’s Big Trip','🧸',['Teddy the bear went on a pretend holiday with Nia and her family.','Nia stayed with her grown-up at the pretend airport and listened to the staff. Teddy sat safely inside the travel bag.','The best part of the trip was being together and sharing stories.'])]
@app.route('/kids/progress', methods=['POST'])
@kids_required
def kids_save_progress():
 # Stores only this member's progress. No public leaderboard, EXP, or payment data.
 payload=request.get_json(silent=True) or request.form
 activity=(payload.get('activity') or '').strip()
 uid=current_user()['id']; c=db(); now=datetime.utcnow().isoformat()
 if activity=='story':
  slug=(payload.get('item_key') or '').strip()
  if not slug or not c.execute('SELECT 1 FROM kids_stories WHERE slug=? AND is_published=1',(slug,)).fetchone():
   abort(404)
  c.execute("INSERT INTO kids_activity_progress(user_id,activity_type,item_key,completed_count,best_score,updated_at) VALUES(?,'story',?,1,0,?) ON CONFLICT(user_id,activity_type,item_key) DO UPDATE SET completed_count=1,updated_at=excluded.updated_at",(uid,slug,now))
  c.commit()
  if request.is_json: return {'ok':True,'message':'Story marked as read.'}
  flash('Story marked as read. Well done!')
  return redirect(url_for('kids_storybook',slug=slug))
 if activity=='sky_stars':
  score=payload.get('score')
  if isinstance(score,bool): abort(400)
  try: score=int(score)
  except (TypeError,ValueError): abort(400)
  if not 0<=score<=5000: abort(400)
  c.execute("INSERT INTO kids_activity_progress(user_id,activity_type,item_key,completed_count,best_score,updated_at) VALUES(?,'sky_stars','personal-best',1,?,?) ON CONFLICT(user_id,activity_type,item_key) DO UPDATE SET completed_count=kids_activity_progress.completed_count+1,best_score=MAX(kids_activity_progress.best_score,excluded.best_score),updated_at=excluded.updated_at",(uid,score,now))
  c.commit(); return {'ok':True,'saved':True}
 if activity=='perfect_timing':
  success=payload.get('success')
  if success not in (True,False,0,1,'0','1'): abort(400)
  if str(success).lower() in ('true','1'):
   c.execute("INSERT INTO kids_activity_progress(user_id,activity_type,item_key,completed_count,best_score,updated_at) VALUES(?,'perfect_timing','wins',1,1,?) ON CONFLICT(user_id,activity_type,item_key) DO UPDATE SET completed_count=kids_activity_progress.completed_count+1,best_score=1,updated_at=excluded.updated_at",(uid,now))
   c.commit()
  return {'ok':True,'saved':True}
 abort(400)


@app.route('/kids/story-books')
@kids_required
def kids_storybooks():
 c=db(); uid=current_user()['id']
 rows=c.execute('SELECT slug,title,emoji FROM kids_stories WHERE is_published=1 ORDER BY id').fetchall()
 read_slugs={r['item_key'] for r in c.execute("SELECT item_key FROM kids_activity_progress WHERE user_id=? AND activity_type='story' AND completed_count>0",(uid,)).fetchall()}
 favourite_slugs={r['story_slug'] for r in c.execute('SELECT story_slug FROM kids_story_favourites WHERE user_id=?',(uid,)).fetchall()}
 stories=[(r['slug'],r['title'],r['emoji']) for r in rows]
 featured=stories[0] if stories else None
 return page('Story Books', '''<div class="kids-world"><section class="kids-hero"><h1>📚 Story Books</h1><p>Pick a story and enjoy reading! Save your favourites so you can find them again.</p></section>
 {% if featured %}<section class="kids-card" style="border:2px solid #f1c96f;margin:16px 0"><span class="tag">🌟 SKY'S STORY PICK</span><h2>{{featured[2]}} {{featured[1]}}</h2><p>Sky's featured story this time. Have a read and enjoy!</p><a class="btn" href="{{url_for('kids_storybook',slug=featured[0])}}">Read the story</a></section>{% endif %}
 {% if favourite_stories %}<section class="kids-card"><h2>💜 My Favourite Stories</h2><div class="grid">{% for story in favourite_stories %}<div><b>{{story[2]}} {{story[1]}}</b><br><a href="{{url_for('kids_storybook',slug=story[0])}}">Read favourite</a></div>{% endfor %}</div></section>{% endif %}
 <div class="grid">{% for story in stories %}<article class="kids-card"><div style="font-size:42px">{{story[2]}}</div><h2>{{story[1]}}</h2><p>A short original story about kindness and adventure.</p>{% if story[0] in read_slugs %}<p><b>✅ Read</b></p>{% endif %}<a class="btn" href="{{url_for('kids_storybook',slug=story[0])}}">{{'Read again' if story[0] in read_slugs else 'Read this story'}}</a><form method="post" action="{{url_for('kids_story_favourite',slug=story[0])}}"><button class="kids-favourite" type="submit">{{'💜 Remove favourite' if story[0] in favourite_slugs else '♡ Add to favourites'}}</button></form></article>{% else %}<article class="kids-card"><h2>New stories are on the way!</h2><p>Please check back soon.</p></article>{% endfor %}</div><a class="btn alt" href="{{url_for('home')}}">← Kids Home</a></div>''',stories=stories,read_slugs=read_slugs,favourite_slugs=favourite_slugs,favourite_stories=[x for x in stories if x[0] in favourite_slugs],featured=featured)

@app.route('/kids/story-books/<slug>/favourite', methods=['POST'])
@kids_required
def kids_story_favourite(slug):
 c=db(); uid=current_user()['id']
 if not c.execute('SELECT 1 FROM kids_stories WHERE slug=? AND is_published=1',(slug,)).fetchone(): abort(404)
 exists=c.execute('SELECT 1 FROM kids_story_favourites WHERE user_id=? AND story_slug=?',(uid,slug)).fetchone()
 if exists:
  c.execute('DELETE FROM kids_story_favourites WHERE user_id=? AND story_slug=?',(uid,slug)); flash('Story removed from your favourites.')
 else:
  c.execute('INSERT OR IGNORE INTO kids_story_favourites(user_id,story_slug,created_at) VALUES(?,?,?)',(uid,slug,datetime.utcnow().isoformat())); flash('Story added to your favourites!')
 c.commit(); return redirect(url_for('kids_storybooks'))
@app.route('/kids/story-books/<slug>')
@kids_required
def kids_storybook(slug):
 row=db().execute('SELECT slug,title,emoji,content_json FROM kids_stories WHERE slug=? AND is_published=1',(slug,)).fetchone()
 if row is None: abort(404)
 story=(row['slug'],row['title'],row['emoji'],json.loads(row['content_json']))
 return page(story[1], '''<div class="kids-world"><article class="kids-story"><div style="font-size:52px">{{story[2]}}</div><h1>{{story[1]}}</h1><div class="kids-story-tools"><button type="button" id="readStory">🔊 Read to me</button><button type="button" id="pauseStory" class="btn alt">Ⅱ Pause</button><button type="button" id="stopStory" class="btn alt">■ Stop</button></div><p id="storyVoiceStatus" aria-live="polite">Sky can read this story aloud using your browser's voice feature.</p><div id="storyText">{% for paragraph in story[3] %}<p>{{paragraph}}</p>{% endfor %}<p><b>The End ✨</b></p></div><form method="post" action="{{url_for('kids_save_progress')}}"><input type="hidden" name="activity" value="story"><input type="hidden" name="item_key" value="{{story[0]}}"><button type="submit">✅ Mark as read</button></form><p><a class="btn alt" href="{{url_for('kids_storybooks')}}">More Story Books</a> <a class="btn alt" href="{{url_for('home')}}">Kids Home</a></p></article></div><script>(()=>{const read=document.getElementById('readStory'),pause=document.getElementById('pauseStory'),stop=document.getElementById('stopStory'),status=document.getElementById('storyVoiceStatus');function supported(){if(!('speechSynthesis'in window)){status.textContent='Read-aloud is not supported by this browser. You can still read the story on screen.';return false}return true}read.addEventListener('click',()=>{if(!supported())return;window.speechSynthesis.cancel();const text=document.getElementById('storyText').innerText;const utter=new SpeechSynthesisUtterance(text);utter.lang='en-GB';utter.rate=.92;utter.onend=()=>status.textContent='Story finished. Well done!';utter.onerror=()=>status.textContent='Audio could not play. You can continue reading on screen.';status.textContent='Sky is reading. Enjoy the story!';window.speechSynthesis.speak(utter)});pause.addEventListener('click',()=>{if(!supported())return;if(window.speechSynthesis.paused){window.speechSynthesis.resume();status.textContent='Reading resumed.'}else if(window.speechSynthesis.speaking){window.speechSynthesis.pause();status.textContent='Reading paused.'}});stop.addEventListener('click',()=>{if('speechSynthesis'in window)window.speechSynthesis.cancel();status.textContent='Read-aloud stopped.'});window.addEventListener('pagehide',()=>{if('speechSynthesis'in window)window.speechSynthesis.cancel()});})();</script>''',story=story)
KIDS_QUESTIONS=[
 ('Which part of an aeroplane helps it fly?',['Wings','Suitcase','Passenger seat'],0),
 ('Who helps passengers during a flight?',['Cabin crew','Gardener','Shopkeeper'],0),
 ('What should you do if you are lost at an airport?',['Ask an authorised staff member with your grown-up','Go through any door','Leave your group'],0),
 ('Clouds and rain are part of what?',['Weather','Music','Sport'],0),
 ('What carries your holiday clothes?',['Suitcase','Flower pot','Plate'],0),
 ('What is a kind thing to do when someone is lost?',['Help them find a trusted staff member','Laugh','Hide their map'],0),
 ('What should you do when the seat-belt sign is on?',['Follow crew instructions and fasten your belt','Run in the aisle','Stand on the seat'],0),
 ('Which is an airport helper?',['Baggage handler','Moon dragon','Mermaid'],0),
 ('What should you do with your password?',['Keep it private','Post it publicly','Share it with strangers'],0),
 ('How can you learn something new?',['Listen, ask questions and practise safely','Ignore instructions','Give up'],0)]
KIDS_QUESTION_EXPLANATIONS={
 'Which part of an aeroplane helps it fly?':'The wings help an aeroplane create lift as it moves through the air.',
 'Who helps passengers during a flight?':'Cabin crew members look after passengers and help them during the journey.',
 'What should you do if you are lost at an airport?':'Stay with your grown-up and ask an authorised airport staff member for help.',
 'Clouds and rain are part of what?':'Clouds and rain are parts of weather, which describes conditions in the air.',
 'What carries your holiday clothes?':'A suitcase is made to carry clothes and other travel items.',
 'What is a kind thing to do when someone is lost?':'You can help by finding a trusted grown-up or authorised staff member.',
 'What should you do when the seat-belt sign is on?':'Passengers should fasten their seat belts and follow the cabin crew instructions.',
 'Which is an airport helper?':'A baggage handler helps move checked bags through the airport.',
 'What should you do with your password?':'Keep your password private and never post it publicly or share it with strangers.',
 'How can you learn something new?':'Listening, asking questions and practising safely are helpful ways to learn.'
}

@app.route('/kids/exam',methods=['GET','POST'])
@kids_required
def kids_exam():
 c=db(); uid=current_user()['id']; result=None; review=[]
 rows=c.execute('SELECT question,options_json,correct_index,explanation FROM kids_exam_questions WHERE is_published=1 ORDER BY id').fetchall()
 questions=[(r['question'],json.loads(r['options_json'])) for r in rows]
 if request.method=='POST' and rows:
  score=0; review=[]
  for i,row in enumerate(rows):
   options=json.loads(row['options_json'])
   raw=request.form.get('q'+str(i),'-1')
   try: selected=int(raw)
   except (TypeError,ValueError): selected=-1
   if selected < 0 or selected >= len(options): selected=-1
   correct=int(row['correct_index'])
   is_correct=(selected==correct)
   if is_correct: score+=1
   review.append({
    'question':row['question'],
    'your_answer':options[selected] if selected>=0 else 'Not answered',
    'correct_answer':options[correct],
    'is_correct':is_correct,
    'explanation':(row['explanation'] or 'This is the correct answer. Ask a trusted grown-up if you would like more help.')
   })
  total=len(rows); pass_mark=max(1,(total*7+9)//10); passed=score>=pass_mark
  cur=c.execute('INSERT INTO kids_exam_attempts(user_id,score,total,passed,completed_at,review_json) VALUES(?,?,?,?,?,?)',(uid,score,total,int(passed),datetime.utcnow().isoformat(),json.dumps(review,ensure_ascii=False)))
  c.commit()
  session['kids_last_exam_attempt_id']=cur.lastrowid
  return redirect(url_for('kids_exam'))
 # Read the just-completed review once, and only for the member who owns the attempt.
 last_attempt_id=session.pop('kids_last_exam_attempt_id',None)
 if last_attempt_id:
  attempt=c.execute('SELECT id,score,total,passed,completed_at,review_json FROM kids_exam_attempts WHERE id=? AND user_id=?',(last_attempt_id,uid)).fetchone()
  if attempt:
   result={'score':attempt['score'],'total':attempt['total'],'passed':bool(attempt['passed']),'pass_mark':max(1,(attempt['total']*7+9)//10),'completed_at':attempt['completed_at']}
   try: review=json.loads(attempt['review_json'] or '[]')
   except (TypeError,ValueError): review=[]
 attempts=c.execute('SELECT score,total,passed,completed_at FROM kids_exam_attempts WHERE user_id=? ORDER BY id DESC LIMIT 5',(uid,)).fetchall()
 body=r"""<link rel="stylesheet" href="{{url_for('static',filename='kids_exam_stage28.css')}}"><div class="kids-world kids-exam-stage28">
 <section class="kids-hero"><h1>📝 Friendly Learning Exam</h1><p>{{questions|length}} simple questions. No timer. Take your time and do your best!</p><div class="kids-note">💜 You can learn from every answer. This is practice, not a school grade.</div></section>
 {% if result %}<section class="kids-card kids-exam-result"><h2>{{'🌟 Well done!' if result.passed else '💜 Good try!'}}</h2><p class="kids-exam-score">{{result.score}} / {{result.total}}</p><p>{{'You passed this practice exam!' if result.passed else 'You can practise and try again.'}} Pass mark: {{result.pass_mark}}.</p><small>Your answers and explanations are shown below so you can learn as you review.</small></section>
 <section class="kids-card kids-answer-review"><h2>📘 Let's review your answers</h2><p>Read each explanation and try the exam again whenever you are ready.</p>
 {% for item in review %}<article class="kids-review-item {{'is-correct' if item.is_correct else 'needs-practice'}}"><h3>{{loop.index}}. {{item.question}}</h3><p><b>{{'✅ Your answer:' if item.is_correct else '💡 Your answer:'}}</b> {{item.your_answer}}</p>{% if not item.is_correct %}<p><b>Correct answer:</b> {{item.correct_answer}}</p>{% endif %}<p class="kids-explanation"><b>Why?</b> {{item.explanation}}</p></article>{% endfor %}</section>
 {% endif %}
 {% if questions %}<form class="kids-card kids-exam" method="post"><h2>🌟 Your questions</h2>{% for q in questions %}{% set qi=loop.index0 %}<fieldset class="kids-question"><legend>{{loop.index}}. {{q[0]}}</legend>{% for opt in q[1] %}<label><input type="radio" name="q{{qi}}" value="{{loop.index0}}" required>{{opt}}</label>{% endfor %}</fieldset>{% endfor %}<button type="submit">Submit Exam</button></form>{% else %}<div class="kids-card"><h2>Exam break</h2><p>There are no published questions right now. Please come back later.</p></div>{% endif %}
 {% if attempts %}<div class="kids-card"><h2>🕘 Your recent results</h2>{% for a in attempts %}<p>{{a['completed_at'][:10]}} · {{a['score']}}/{{a['total']}} · {{'Passed' if a['passed'] else 'Keep practising'}}</p>{% endfor %}</div>{% endif %}
 <p class="kids-note">Your exam results are private to your account. No EXP is charged or awarded.</p><a class="btn alt" href="{{url_for('home')}}">← Kids Home</a></div>"""
 return page('Kids Exam',body,questions=questions,result=result,review=review,attempts=attempts)

@app.route('/cinema')
def cinema():
 u=current_user()
 if u and u['role']=='member' and u['mode']=='kids':
  return page('Kids Movie Night', '''<link rel="stylesheet" href="{{url_for('static',filename='kids_movie_stage26.css')}}">
<div class="kids-world kids-cinema">
 <section class="kids-hero kids-cinema-hero">
  <div><span class="kids-cinema-tag">🍿 SKY'S FAMILY CINEMA</span><h1>🎬 Movie Night</h1><p>Make a little movie playlist from videos already saved on this device. Ask a parent or guardian to choose videos that are suitable for you.</p></div>
  <img src="{{url_for('static',filename='media/kids_world_mascot.png')}}" alt="Sky the friendly airplane mascot" loading="lazy">
 </section>
 <section class="kids-card kids-cinema-picker">
  <h2>🎞️ Choose your videos</h2>
  <p>You can choose several MP4, WebM or OGG video files at once. They stay on this device: AIR TRAVEL does not upload or store them.</p>
  <label class="kids-movie-file-label" for="kidsMovieFiles">📁 Choose videos from this device</label>
  <input id="kidsMovieFiles" type="file" accept="video/mp4,video/webm,video/ogg,.mp4,.webm,.ogv,.ogg" multiple>
  <p class="kids-cinema-hint">Tip: MP4 videos using H.264 video and AAC audio are usually a good choice for modern browsers. Some files may use formats your device cannot play.</p>
 </section>
 <section class="kids-cinema-layout">
  <article class="kids-card kids-player-card">
   <div class="kids-player-heading"><h2>▶️ Now showing</h2><span id="kidsMovieQueueCount" class="kids-cinema-count">0 videos</span></div>
   <div class="kids-video-frame"><video id="kidsPlayer" controls playsinline preload="metadata" poster="{{url_for('static',filename='media/kids_world_mascot.png')}}"><p>Your browser does not support video playback.</p></video></div>
   <h3 id="kidsMovieTitle" class="kids-movie-title">Your screen is ready!</h3>
   <p id="kidsMovieStatus" class="kids-cinema-status" role="status" aria-live="polite">Choose a video to start your movie night.</p>
   <div class="kids-movie-controls"><button type="button" id="kidsPreviousMovie" class="kids-movie-secondary" disabled>⏮ Previous</button><button type="button" id="kidsNextMovie" disabled>Next ⏭</button><button type="button" id="kidsClearMovies" class="kids-movie-clear" disabled>Clear playlist</button></div>
  </article>
  <aside class="kids-card kids-playlist-card">
   <div class="kids-player-heading"><h2>📋 Your playlist</h2><span class="kids-cinema-count">This visit only</span></div>
   <ol id="kidsMoviePlaylist" class="kids-movie-playlist" aria-label="Selected videos"><li class="kids-empty-playlist">Your selected videos will appear here.</li></ol>
   <p class="kids-cinema-hint">Select a video in the list to play it. Use Next when one finishes, or let the player move to the next video automatically.</p>
  </aside>
 </section>
 <section class="kids-card kids-movie-help"><h2>💜 A safe movie night</h2><ul><li>Ask a parent or guardian to choose the videos with you.</li><li>Only choose videos you are allowed to watch.</li><li>Your selected files are not sent to AIR TRAVEL or other people.</li><li>Your playlist is cleared when you leave this page. Your original files stay on your device.</li></ul></section>
 <p class="kids-cinema-back"><a class="btn alt" href="{{url_for('home')}}">← Back to Kids Home</a></p>
</div>
<script src="{{url_for('static',filename='kids_movie_stage26.js')}}" defer></script>''')
 eps=['The Door That Wasn\'t There','The Dream City','The Lost Memory','The Time Portal','The Heart of Our World',"Echo's Secret",'The World Without Colour','The Stranger in the Sky','The Last Door','Beyond the Unknown']
 return page('Cinema Club','''<div class="hero"><h1>🎬 AIR TRAVEL Movie Night</h1><p>Choose a video file saved on your device to play in this browser. Only use videos you own or are authorised to watch.</p></div><div class="card"><h2>▶ Local Video Player</h2><label for="movieFile">Choose a video from your device</label><input id="movieFile" type="file" accept="video/*"><div class="video-box"><video id="moviePlayer" controls playsinline preload="metadata"><p>Your browser does not support HTML video.</p></video></div><p id="movieStatus" class="muted">No video selected yet. Choose a video file above.</p><button type="button" id="clearMovie" class="btn alt">Clear video</button></div><div class="card"><h2>The World Inside Us</h2><p>Original animated series concept · Season 1 · 10 planned episodes · Zara, Milo, Nova and Echo.</p><ol class="list">{% for ep in eps %}<li>{{ep}}</li>{% endfor %}</ol><p>Episodes and voice performances are still in production; this page does not contain finished episodes yet.</p></div><div class="card"><h2>Music Zone</h2><p>Use an official licensed music service for playback.</p><a href="https://www.michaeljackson.com/" target="_blank" rel="noopener">Official Michael Jackson website</a></div><script>const mf=document.getElementById('movieFile'),mp=document.getElementById('moviePlayer'),ms=document.getElementById('movieStatus'),clear=document.getElementById('clearMovie');let currentMovieUrl=null;mf.addEventListener('change',()=>{const f=mf.files&&mf.files[0];if(!f)return;if(!f.type.startsWith('video/')){ms.textContent='Please choose a video file.';return}if(currentMovieUrl)URL.revokeObjectURL(currentMovieUrl);currentMovieUrl=URL.createObjectURL(f);mp.src=currentMovieUrl;mp.load();mp.onerror=()=>{ms.textContent='This video format may not be supported by your browser. Try an MP4 video (H.264/AAC).';};mp.onloadedmetadata=()=>{ms.textContent='Video ready: '+f.name+' · '+Math.round(mp.duration)+' seconds. Press Play.';};ms.textContent='Loading video: '+f.name+'…';});clear.addEventListener('click',()=>{mp.pause();mp.removeAttribute('src');mp.load();mf.value='';if(currentMovieUrl)URL.revokeObjectURL(currentMovieUrl);currentMovieUrl=null;ms.textContent='No video selected yet.';});</script>''',eps=eps)
@app.route('/versions',methods=['GET','POST'])
@login_required
def versions():
 u=current_user()
 if request.method=='POST':
  mode=request.form.get('mode','')
  if mode not in ('kids','general'): flash('Choose Kids or General mode.','error')
  elif u['role']=='owner': flash('Owner can preview both experiences from this page.')
  else:
   db().execute('UPDATE users SET mode=? WHERE id=?',(mode,u['id'])); db().commit(); flash('Your experience mode has been updated. Kids mode is only a starter interface, not a complete child-safety system.')
  return redirect(url_for('versions'))
 return page('Kids and General', """<div class="hero"><h1>Choose Your Air Travel World</h1><p>Two experience styles, one aviation community.</p><span class="tag">CURRENT MODE: {{user['mode']|upper}}</span></div><div class="grid"><div class="card"><h2>Kids Experience</h2><p>Simple navigation, beginner aviation facts, gentle quizzes and age-appropriate activities. Chat and public posting should remain supervised and moderated.</p>{% if user['role']=='owner' %}<span class="tag">OWNER PREVIEW AVAILABLE</span>{% else %}<form method="post"><input type="hidden" name="mode" value="kids"><button>Use Kids Experience</button></form>{% endif %}</div><div class="card"><h2>General Experience</h2><p>Expanded aviation information, community features, games, events, virtual airport ideas and membership information.</p>{% if user['role']=='owner' %}<span class="tag">OWNER PREVIEW AVAILABLE</span>{% else %}<form method="post"><input type="hidden" name="mode" value="general"><button>Use General Experience</button></form>{% endif %}</div></div><div class="notice">Safety note: the Kids option is a basic mode selector only. Before children use the service, add age verification, guardian consent, strict moderation, privacy protections and restricted messaging.</div>""")

@app.route('/daily-reward',methods=['POST'])
@login_required
def daily_reward():
 u=current_user()
 if u['role']=='owner': flash('Owner accounts do not claim member daily EXP.')
 else:
  today=datetime.now(timezone(timedelta(hours=1))).date().isoformat(); c=db()
  try:
   c.execute('BEGIN IMMEDIATE'); c.execute('INSERT INTO daily_claims(user_id,claim_date,amount) VALUES(?,?,?)',(u['id'],today,50)); c.execute('UPDATE users SET exp=exp+50 WHERE id=?',(u['id'],)); c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(u['id'],50,'Daily login reward',datetime.utcnow().isoformat())); c.commit(); flash('Daily reward claimed: 50 EXP!')
  except sqlite3.IntegrityError: c.rollback(); flash('You have already claimed today’s reward.','error')
 return redirect(url_for('home'))

@app.route('/owner-tribute')
def owner_tribute():
 row=db().execute('SELECT dedication,updated_at FROM owner_tribute_settings WHERE id=1').fetchone()
 dedication=row['dedication'] if row else 'AIR TRAVEL began in 2026 with a simple ambition: bring aviation discovery, travel planning, learning, games and community together in one place.'
 milestones=db().execute('SELECT id,stage_label,title,description FROM owner_tribute_milestones ORDER BY id ASC').fetchall()
 return page('Owner Tribute', r'''<style>
.tribute-shell{display:grid;gap:20px}.tribute-hero{position:relative;overflow:hidden;text-align:center;padding:clamp(34px,6vw,72px);border:1px solid #d5a84e;border-radius:26px;background:radial-gradient(circle at 50% 0,#60428b 0,#21133f 45%,#07162e 100%);box-shadow:0 18px 54px #0007}.tribute-hero:before,.tribute-hero:after{content:'✦';position:absolute;color:#f7d98b66;font-size:90px}.tribute-hero:before{left:7%;top:12%}.tribute-hero:after{right:8%;bottom:8%}.tribute-crown{font-size:42px}.tribute-hero h1{font-size:clamp(36px,7vw,68px);margin:12px 0;background:linear-gradient(90deg,#fff3c7,#e8b95c,#fff);-webkit-background-clip:text;background-clip:text;color:transparent}.tribute-hero p{max-width:760px;margin:12px auto;color:#e6dff4;line-height:1.7;font-size:17px}.tribute-pills{display:flex;justify-content:center;gap:10px;flex-wrap:wrap;margin-top:22px}.tribute-pill{padding:9px 14px;border:1px solid #e3bf6c77;border-radius:30px;background:#100d2a88;color:#ffe4a3;font-weight:700;font-size:13px}.founder-card{text-align:center;border-color:#94733b;background:linear-gradient(150deg,#292044,#0a1b35)}.founder-avatar{width:76px;height:76px;border-radius:50%;margin:0 auto 14px;display:grid;place-items:center;font-size:34px;background:linear-gradient(145deg,#f6d78d,#966c28);color:#211331;box-shadow:0 6px 24px #0005}.founder-photo{width:132px;height:132px;border-radius:50%;object-fit:cover;object-position:center 38%;display:block;margin:0 auto 14px;border:3px solid #e7c46e;box-shadow:0 8px 26px #0008}.founder-name{font-size:24px;color:#ffe1a1;margin:6px 0}.founder-role{color:#82dcff;font-weight:800;letter-spacing:1px;font-size:12px}.tribute-copy{border-color:#9b7a3e;background:linear-gradient(135deg,#1b1b3d,#0b203b)}.tribute-copy p{white-space:pre-wrap;line-height:1.8;color:#e4edf8}.timeline{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}.milestone{border-left:3px solid #e2b85e}.milestone small{color:#f0cc7d;font-weight:800;letter-spacing:1px}.milestone h3{margin:8px 0}.tribute-status{border:1px solid #c99a43;background:#211b2d;color:#f5e4b8;border-radius:14px;padding:15px 18px;text-align:center}
</style>
<div class="tribute-shell">
<section class="tribute-hero"><div class="tribute-crown">👑 ✈️ 👑</div><span class="tag">THE PEOPLE BEHIND THE PROJECT</span><h1>AIR TRAVEL</h1><h2 style="color:#ffe4a3;margin:0">Founders & Leadership Tribute</h2><p>A celebration of the vision, teamwork and creativity behind the AIR TRAVEL project.</p><div class="tribute-pills"><span class="tribute-pill">ESTABLISHED 2026</span><span class="tribute-pill">FOUNDER-LED PROJECT</span><span class="tribute-pill">AVIATION · TRAVEL · COMMUNITY</span></div></section>
<div class="grid">
 <article class="card founder-card">{% if show_owner_photo %}<img class="founder-photo" src="{{url_for('owner_tribute_photo_public')}}" alt="Portrait of the AIR TRAVEL founder">{% else %}<div class="founder-avatar">👑</div>{% endif %}<div class="founder-role">FOUNDER & OWNER</div><h2 class="founder-name">AKINOLA AJIDE</h2><p>The founder behind the AIR TRAVEL vision, guiding the project's direction and development.</p></article>
 <article class="card founder-card"><div class="founder-avatar">✈️</div><div class="founder-role">CO-OWNER</div><h2 class="founder-name">JAYDINE</h2><p>Co-owner of AIR TRAVEL, recognised as part of the project's leadership team.</p></article>
</div>
<section class="card tribute-copy"><span class="tag">A MESSAGE FROM THE PROJECT</span><h2>Our story</h2><p>{{dedication}}</p><small class="muted">This message is managed securely through Owner HQ.</small></section>
<section><div class="home-section-head"><div><h2>🚀 Development milestones</h2><p>Updates published by AIR TRAVEL Owner HQ.</p></div></div><div class="timeline">
 {% for milestone in milestones %}<article class="card milestone"><small>{{milestone['stage_label']}}</small><h3>{{milestone['title']}}</h3><p class="muted">{{milestone['description']}}</p></article>{% else %}<article class="card"><p class="muted">The project timeline will be updated soon.</p></article>{% endfor %}
</div></section>
<div class="tribute-status"><b>📍 PROJECT STATUS: IN DEVELOPMENT — NOT YET OFFICIALLY LAUNCHED</b><br><small>Milestones describe project development, not a public launch or live airline service.</small></div>
</div>''', dedication=dedication, milestones=milestones, show_owner_photo=os.environ.get('PUBLIC_OWNER_PHOTO_APPROVED','0').strip() == '1')

@app.route('/owner-tribute/photo')
def owner_tribute_photo_public():
 # Public delivery is disabled by default. An adult project administrator should
 # enable this environment flag only after guardian approval for public display.
 if os.environ.get('PUBLIC_OWNER_PHOTO_APPROVED','0').strip() != '1':
  abort(404)
 photo_path=os.path.join(ROOT,'private_media','owner_tribute_portrait.jpg')
 if not os.path.isfile(photo_path): abort(404)
 return send_file(photo_path, mimetype='image/jpeg', conditional=True, max_age=3600)

@app.route('/owner/tribute/photo-preview')
@owner_required
def owner_tribute_photo_preview():
 photo_path=os.path.join(ROOT,'private_media','owner_tribute_portrait.jpg')
 if not os.path.isfile(photo_path): abort(404)
 response=send_file(photo_path, mimetype='image/jpeg', conditional=True, max_age=0)
 response.headers['Cache-Control']='no-store, private'
 return response

@app.route('/owner/tribute', methods=['GET','POST'])
@owner_required
def owner_tribute_manage():
 c=db()
 if request.method=='POST':
  dedication=(request.form.get('dedication') or '').strip()
  if not 30<=len(dedication)<=1200:
   flash('The tribute message must contain 30–1,200 characters.','error')
  else:
   owner=current_user(); now=datetime.utcnow().isoformat()
   c.execute('UPDATE owner_tribute_settings SET dedication=?,updated_at=?,updated_by=? WHERE id=1',(dedication,now,owner['id']))
   audit_owner_action('Owner tribute updated',None,'Updated public founders tribute message')
   c.commit(); flash('Owner Tribute page updated successfully.')
  return redirect(url_for('owner_tribute_manage'))
 row=c.execute('SELECT dedication,updated_at FROM owner_tribute_settings WHERE id=1').fetchone()
 return page('Manage Owner Tribute', r'''<section class="hero"><span class="tag">OWNER HQ · PRIVATE MANAGEMENT</span><h1>👑 Manage Owner Tribute</h1><p>Update the message shown on the public AIR TRAVEL founders page. The founder and co-owner names and founding year remain part of the official project record.</p><p><a class="btn" href="{{url_for('owner_tribute')}}" target="_blank" rel="noopener">Preview public tribute ↗</a></p></section>
<div class="card" style="max-width:900px;margin:20px auto"><h2>Founder portrait · private preview</h2><img src="{{url_for('owner_tribute_photo_preview')}}" alt="Private preview of the founder portrait" style="width:150px;height:150px;object-fit:cover;object-position:center 38%;border-radius:50%;border:3px solid #e7c46e;display:block;margin:12px 0"><p class="muted">Your uploaded photo is stored outside the public static folder. Only an authenticated owner can view this preview. It is not shown on the public tribute page by default.</p><p><b>Public display:</b> disabled until a parent/guardian agrees. After approval, an adult deployment administrator can set <code>PUBLIC_OWNER_PHOTO_APPROVED=1</code> in the hosting environment. Leave it at 0 to keep the photo private.</p></div>
<div class="card" style="max-width:900px;margin:20px auto"><h2>Project dedication</h2><form method="post"><label for="dedication">Public tribute message</label><textarea id="dedication" name="dedication" minlength="30" maxlength="1200" rows="8" required>{{row['dedication'] if row else ''}}</textarea><small class="muted">30–1,200 characters. Do not include private contact details, passwords, home addresses or other personal information.</small><p><button type="submit">Save tribute message</button></p></form>{% if row and row['updated_at'] %}<small class="muted">Last updated: {{row['updated_at'][:16]}}</small>{% endif %}</div>''', row=row)

@app.route('/owner/tribute/timeline', methods=['GET','POST'])
@owner_required
def owner_milestones_manage():
 c=db()
 if request.method=='POST':
  action=(request.form.get('action') or 'add').strip().lower()
  if action=='delete':
   milestone_id=request.form.get('milestone_id','').strip()
   if not milestone_id.isdigit():
    flash('Choose a valid timeline item to delete.','error')
   else:
    existing=c.execute('SELECT id,title FROM owner_tribute_milestones WHERE id=?',(int(milestone_id),)).fetchone()
    if existing:
     c.execute('DELETE FROM owner_tribute_milestones WHERE id=?',(existing['id'],))
     audit_owner_action('Founder timeline item deleted',None,'Deleted milestone: '+existing['title'])
     c.commit(); flash('Timeline item deleted.')
    else:
     flash('That timeline item could not be found.','error')
  else:
   milestone_id=request.form.get('milestone_id','').strip()
   label=(request.form.get('stage_label') or '').strip()
   title=(request.form.get('title') or '').strip()
   description=(request.form.get('description') or '').strip()
   if not (2<=len(label)<=60 and 2<=len(title)<=100 and 8<=len(description)<=300):
    flash('Please check the limits: label 2–60, title 2–100 and description 8–300 characters.','error')
   elif action=='update' and not milestone_id.isdigit():
    flash('Choose a valid timeline item to update.','error')
   elif action=='update':
    existing=c.execute('SELECT id FROM owner_tribute_milestones WHERE id=?',(int(milestone_id),)).fetchone()
    if not existing:
     flash('That timeline item could not be found.','error')
    else:
     c.execute('UPDATE owner_tribute_milestones SET stage_label=?,title=?,description=? WHERE id=?',(label,title,description,int(milestone_id)))
     audit_owner_action('Founder timeline item updated',None,'Updated milestone: '+title)
     c.commit(); flash('Timeline item updated.')
   else:
    count=c.execute('SELECT COUNT(*) FROM owner_tribute_milestones').fetchone()[0]
    if count>=12:
     flash('The public timeline is limited to 12 items. Edit or remove an item before adding another.','error')
    else:
     c.execute('INSERT INTO owner_tribute_milestones(stage_label,title,description,created_at) VALUES(?,?,?,?)',(label,title,description,datetime.utcnow().isoformat()))
     audit_owner_action('Founder timeline item added',None,'Added milestone: '+title)
     c.commit(); flash('New timeline item published.')
  return redirect(url_for('owner_milestones_manage'))
 rows=c.execute('SELECT * FROM owner_tribute_milestones ORDER BY id ASC').fetchall()
 return page('Manage Founder Timeline', r'''<section class="hero"><span class="tag">OWNER HQ · PRIVATE MANAGEMENT</span><h1>🚀 Founder Timeline Manager</h1><p>Add, update or remove the milestones displayed on the public Owner Tribute page. Only the authenticated owner can manage these entries.</p><p><a class="btn alt" href="{{url_for('owner_tribute')}}" target="_blank" rel="noopener">Preview public tribute ↗</a></p></section>
<div class="card" style="max-width:900px;margin:20px auto"><h2>➕ Add a milestone</h2><form method="post"><input type="hidden" name="action" value="add"><label for="new-label">Stage label</label><input id="new-label" name="stage_label" maxlength="60" minlength="2" placeholder="e.g. NOVEMBER 2026 · COMMUNITY" required><label for="new-title">Milestone title</label><input id="new-title" name="title" maxlength="100" minlength="2" placeholder="e.g. Announcements Centre" required><label for="new-description">Description</label><textarea id="new-description" name="description" minlength="8" maxlength="300" rows="3" placeholder="Describe this project milestone..." required></textarea><small class="muted">Up to 12 public milestones. Do not include private contact details or sensitive personal information.</small><p><button type="submit">Publish milestone</button></p></form></div>
<div class="card" style="max-width:900px;margin:20px auto"><h2>📝 Current milestones ({{rows|length}}/12)</h2>{% for item in rows %}<details style="border-top:1px solid #245078;padding:14px 0" {% if loop.first %}open{% endif %}><summary><b>{{item['stage_label']}}</b> · {{item['title']}}</summary><form method="post" style="margin-top:12px"><input type="hidden" name="action" value="update"><input type="hidden" name="milestone_id" value="{{item['id']}}"><label>Stage label</label><input name="stage_label" value="{{item['stage_label']}}" maxlength="60" minlength="2" required><label>Milestone title</label><input name="title" value="{{item['title']}}" maxlength="100" minlength="2" required><label>Description</label><textarea name="description" minlength="8" maxlength="300" rows="3" required>{{item['description']}}</textarea><button type="submit">Save changes</button></form><form method="post" style="margin-top:8px"><input type="hidden" name="action" value="delete"><input type="hidden" name="milestone_id" value="{{item['id']}}"><button class="btn alt" type="submit" onclick="return confirm('Delete this public timeline milestone?')">Delete milestone</button></form></details>{% else %}<p>No milestones yet. Add the first one above.</p>{% endfor %}</div>''',rows=rows)

@app.route('/ideas')
def ideas():
 return page('More ideas','''<div class="hero"><h1>Next-level AIR TRAVEL ideas</h1><p>A clear roadmap for growing the platform safely.</p></div><div class="grid"><div class="card"><h3>🏙 Virtual Airport</h3><p>Build and customise terminals, runways, gates, aircraft displays and airport shops.</p></div><div class="card"><h3>🧑‍✈️ Pilot Career</h3><p>Progress through Student Pilot, Junior Pilot, Professional Pilot, Senior Captain and Legendary Captain ranks.</p></div><div class="card"><h3>🌦 Live Weather Centre</h3><p>Weather maps, airport conditions and forecast cards using a licensed weather data source.</p></div><div class="card"><h3>🏆 Competitions</h3><p>Weekly aviation quizzes, landing challenges, seasonal events and fair leaderboards.</p></div><div class="card"><h3>👥 Friends & Clubs</h3><p>Friend requests, private groups, moderated chat, profile badges and member gifting.</p></div><div class="card"><h3>🎁 Mystery Gift Box</h3><p>Surprise virtual rewards with clear odds and no cash gambling or paid random rewards.</p></div><div class="card"><h3>🔔 Daily Rewards</h3><p>Login streaks, daily challenges, achievement collections and event EXP.</p></div><div class="card"><h3>🔐 Safety & Security</h3><p>Two-factor authentication, account recovery, reporting, moderation, backups and admin audit logs.</p></div><div class="card"><h3>👑 Owner HQ</h3><p>Member management, events, EXP awards, moderation tools, announcements and system health.</p></div></div><div class="card"><h3>New playable ATW features</h3><p><a href="{{url_for('world')}}">Rotating Globe & Destination Explorer</a> · <a href="{{url_for('passport')}}">Digital Passport</a> · <a href="{{url_for('tycoon')}}">Airport Tycoon</a> · <a href="{{url_for('wheel')}}">Free Daily EXP Wheel</a> · <a href="{{url_for('achievements')}}">Achievement Wall & Leaderboard</a>.</p><p>These are local account features. Multiplayer, real flight data and airline booking integrations remain separate future work.</p></div><div class="card"><h3>Membership concept</h3><p>Premium/PRO pricing can be displayed as a proposal, but checkout must not accept payment until a compliant payment provider, guardian-consent flow where needed, refunds and verified payment webhooks are implemented.</p></div>''')
# Stage 5: server-connected general-purpose AI assistant.
# Simple per-process rate limit. For a multi-worker deployment, use a shared
# store such as Redis and configure an application-wide request limit.
_AI_REQUESTS = {}
_AI_RATE_WINDOW = 60
_AI_RATE_LIMIT = 8

@app.route('/ai-assistant')
@login_required
def ai_assistant():
 configured = bool(os.environ.get('OPENAI_API_KEY','').strip())
 history=db().execute('SELECT role,content,created_at FROM member_ai_messages WHERE user_id=? ORDER BY id DESC LIMIT 30',(current_user()['id'],)).fetchall()
 history=list(reversed(history))
 return page('AIR TRAVEL AI', r"""<div class="hero"><span class="tag">STAGE 39 · PERSONAL AI</span><h1>🤖 YOUR PERSONAL AIR TRAVEL AI</h1><p>Your own assistant for school, science, technology, writing, travel, creativity, everyday questions and aviation. Your saved chats are private to your account.</p></div>
 <div class="card" style="max-width:900px;margin:20px auto">
 <div class="notice">Privacy reminder: never share passwords, home addresses, phone numbers, school details or private family information. AI can make mistakes; check important answers with a trusted adult or reliable source.</div>
 <div class="notice" id="ai-connection">{{'AI service is configured on this server.' if ai_configured else 'AI service setup is still required on the server. An adult administrator must configure the private API key.'}}</div>
 <div id="chat" aria-live="polite" style="min-height:260px;max-height:480px;overflow:auto;background:#041126;border:1px solid #145eaa;border-radius:12px;padding:14px">{% for item in history %}<p><b>{{'You' if item['role']=='user' else 'AIR TRAVEL AI'}}:</b> {{item['content']}}</p>{% else %}<p class="muted">AIR TRAVEL AI: Hello! What would you like help with today?</p>{% endfor %}</div>
 <form id="ai-form" style="margin-top:14px"><label for="ai-input">Your message</label><textarea id="ai-input" maxlength="2000" required placeholder="Ask me anything appropriate..."></textarea><button id="ai-send" type="submit">Send message</button></form>
 <p id="ai-status" class="muted" role="status">Your chat history is saved privately to your account. Do not share passwords, addresses or other sensitive details.</p><form method="post" action="{{url_for('ai_clear_history')}}" onsubmit="return confirm('Clear your saved AI chat history?')"><input type="hidden" name="csrf_token" value="{{csrf_token}}"><button class="btn alt" type="submit">Clear my chat history</button></form>
 </div>
 <script>
 (()=>{const form=document.getElementById('ai-form'),input=document.getElementById('ai-input'),chat=document.getElementById('chat'),send=document.getElementById('ai-send'),status=document.getElementById('ai-status');const history=[];
 function line(who,text){const p=document.createElement('p');const b=document.createElement('b');b.textContent=who+': ';p.appendChild(b);p.appendChild(document.createTextNode(text));chat.appendChild(p);chat.scrollTop=chat.scrollHeight;}
 form.addEventListener('submit',async e=>{e.preventDefault();const text=input.value.trim();if(!text)return;line('You',text);history.push({role:'user',content:text});input.value='';send.disabled=true;status.textContent='AIR TRAVEL AI is thinking…';
 try{const r=await fetch('{{url_for("ai_chat")}}',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':'{{csrf_token}}'},body:JSON.stringify({message:text})});const data=await r.json();if(!r.ok)throw new Error(data.error||'The assistant could not reply.');line('AIR TRAVEL AI',data.reply);history.push({role:'assistant',content:data.reply});}
 catch(err){line('AIR TRAVEL AI',err.message);status.textContent='Please try again later or ask the app administrator to check the AI setup.';}
 finally{send.disabled=false;input.focus();}});
 })();
 </script>""", ai_configured=configured)

@app.route('/ai/chat', methods=['POST'])
@login_required
def ai_chat():
 # The secret key is read only by the backend and is never returned to the browser.
 api_key=os.environ.get('OPENAI_API_KEY','').strip()
 if not api_key:
  return {'error':'AIR TRAVEL AI is not connected yet. An adult administrator must configure the private API key on the server.'},503
 user=current_user()
 now=time.time()
 bucket=_AI_REQUESTS.setdefault(user['id'],[])
 bucket[:]=[stamp for stamp in bucket if now-stamp < _AI_RATE_WINDOW]
 if len(bucket)>=_AI_RATE_LIMIT:
  return {'error':'You have reached the short chat limit. Please wait a minute before sending another message.'},429
 payload=request.get_json(silent=True) or {}
 message=payload.get('message','')
 if not isinstance(message,str) or not message.strip() or len(message)>2000:
  return {'error':'Enter a message between 1 and 2,000 characters.'},400
 # Conversation history is loaded by authenticated user ID; clients cannot submit another member's history.
 c=db()
 previous=c.execute('SELECT role,content FROM member_ai_messages WHERE user_id=? ORDER BY id DESC LIMIT 7',(user['id'],)).fetchall()
 safe=[{'role':row['role'],'content':row['content']} for row in reversed(previous)]
 safe.append({'role':'user','content':message.strip()})
 instructions=("You are AIR TRAVEL AI, a friendly general-purpose assistant inside the AIR TRAVEL app. "
 "Help with safe topics including learning, school explanations, science, technology, writing, creativity, travel and aviation. "
 "Use clear, age-appropriate language because some users may be under 18. "
 "For Kids World users, keep explanations especially simple, gentle and child-appropriate. "
 "Do not request or encourage sharing passwords, precise location, contact details, school details, private family information or other sensitive personal data. "
 "Do not provide sexual content involving minors, instructions for dangerous activities, or graphic violence. "
 "For medical, legal, financial or other high-stakes matters, give general information and encourage help from a trusted adult or qualified professional. "
 "Do not claim to have live information, perform actions, or remember users outside the saved conversation. Be honest about uncertainty.")
 body=json.dumps({'model':os.environ.get('OPENAI_MODEL','gpt-4.1-mini'),'instructions':instructions,'input':safe,'max_output_tokens':700,'store':False}).encode('utf-8')
 req=urllib.request.Request('https://api.openai.com/v1/responses',data=body,headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},method='POST')
 bucket.append(now)
 try:
  with urllib.request.urlopen(req,timeout=35) as response:
   result=json.loads(response.read().decode('utf-8'))
  reply='\n'.join(part.get('text','') for item in result.get('output',[]) if item.get('type')=='message' for part in item.get('content',[]) if part.get('type')=='output_text').strip()
  if not reply: raise ValueError('The AI returned an empty answer.')
  stamp=datetime.utcnow().isoformat()
  c.execute("INSERT INTO member_ai_messages(user_id,role,content,created_at) VALUES(?,?,?,?)",(user['id'],'user',message.strip(),stamp))
  c.execute("INSERT INTO member_ai_messages(user_id,role,content,created_at) VALUES(?,?,?,?)",(user['id'],'assistant',reply,stamp))
  c.commit()
  return {'reply':reply}
 except urllib.error.HTTPError as exc:
  app.logger.warning('AIR TRAVEL AI provider returned HTTP %s',exc.code)
  return {'error':'The AI service could not complete that request. Please try again later.'},502
 except (urllib.error.URLError,TimeoutError,ValueError,json.JSONDecodeError):
  app.logger.exception('AIR TRAVEL AI request failed')
  return {'error':'AIR TRAVEL AI could not connect. Please try again later.'},502

@app.route('/ai/clear-history',methods=['POST'])
@login_required
def ai_clear_history():
 if request.form.get('csrf_token') != session.get('csrf_token'):
  abort(400)
 c=db(); c.execute('DELETE FROM member_ai_messages WHERE user_id=?',(current_user()['id'],)); c.commit()
 flash('Your personal AI chat history has been cleared.')
 return redirect(url_for('ai_assistant'))


# Stage 13: Aviation Career & Professional World.
CAREERS = [
 ('pilot','✈ Pilot','Explore flight-deck teamwork, flight planning concepts and the professional training pathway.','Pilots are professionally trained and licensed flight crew.'),
 ('cabin-crew','🛫 Cabin Crew','Explore passenger care, teamwork, communication and cabin-service responsibilities.','Cabin crew support passengers and follow approved airline procedures.'),
 ('engineer','🔧 Aircraft Engineer','Discover aircraft maintenance careers, inspection principles and technical teamwork.','Maintenance is performed only by qualified, authorised professionals.'),
 ('controller','🗼 Air Traffic Controller','Learn about aviation communication and coordination.','Air traffic control requires specialist training and certification.'),
 ('airport-manager','🏢 Airport Manager','Explore airport operations, customer experience, planning and leadership.','Airport management coordinates many teams and services.')
]
CAREER_CHALLENGES = [
 ('pilot','flight-planning','Flight Planning Basics','Explain why a flight plan helps teams coordinate a journey.'),
 ('pilot','crewwork','Flight-deck Teamwork','Name two qualities that support safe teamwork.'),
 ('cabin-crew','passenger-care','Passenger Care','Describe two ways crew can help passengers feel informed and supported.'),
 ('cabin-crew','teamwork','Cabin Teamwork','Explain why clear communication matters.'),
 ('engineer','maintenance-team','Maintenance Teamwork','Why must aircraft maintenance be done by trained, authorised professionals?'),
 ('engineer','quality-checks','Quality and Records','Explain why careful records and approved checks matter.'),
 ('controller','coordination','Coordination','Explain why clear coordination between aviation teams is important.'),
 ('controller','awareness','Situational Awareness','Describe why professionals need to stay attentive and follow procedures.'),
 ('airport-manager','airport-teams','Airport Teams','Name three teams an airport manager may coordinate.'),
 ('airport-manager','service-quality','Service Quality','Suggest one way an airport can improve passenger experience.')
]

@app.route('/career-centre', methods=['GET','POST'])
@login_required
def career_centre():
 c=db(); uid=current_user()['id']
 if request.method=='POST':
  action=request.form.get('action','')
  if action=='complete':
   career=request.form.get('career_key',''); challenge=request.form.get('challenge_key','')
   valid=any(x[0]==career and x[1]==challenge for x in CAREER_CHALLENGES)
   if challenge.startswith('custom-') and challenge[7:].isdigit():
    valid=bool(c.execute('SELECT 1 FROM career_challenges WHERE id=? AND career_key=?',(int(challenge[7:]),career)).fetchone())
   if valid:
    c.execute('INSERT OR IGNORE INTO career_progress(user_id,career_key,challenge_key,completed_at) VALUES(?,?,?,?)',(uid,career,challenge,datetime.utcnow().isoformat()))
    c.commit(); flash('Challenge saved to your career record.')
   else: flash('Challenge not found.','error')
  elif action=='apply':
   role=request.form.get('role_key',''); motivation=(request.form.get('motivation') or '').strip()
   if any(x[0]==role for x in CAREERS) and 20<=len(motivation)<=500:
    c.execute('INSERT INTO career_applications(user_id,role_key,motivation,created_at) VALUES(?,?,?,?)',(uid,role,motivation,datetime.utcnow().isoformat()))
    c.commit(); flash('Your fictional AIR TRAVEL career application has been submitted.')
   else: flash('Choose a career and write 20–500 characters.','error')
  return redirect(url_for('career_centre'))
 rows=c.execute('SELECT career_key,challenge_key FROM career_progress WHERE user_id=?',(uid,)).fetchall()
 done={(r['career_key'],r['challenge_key']) for r in rows}
 
 challenges=CAREER_CHALLENGES+[(r['career_key'],'custom-'+str(r['id']),r['title'],r['description']) for r in c.execute('SELECT id,career_key,title,description FROM career_challenges ORDER BY id DESC').fetchall()]
 applications=c.execute('SELECT role_key,status,created_at FROM career_applications WHERE user_id=? ORDER BY id DESC',(uid,)).fetchall()
 return page('Aviation Career Centre',r"""<section class="hero"><span class="tag">STAGE 13 · CAREER & PROFESSIONAL WORLD</span><h1>🧭 Aviation Career Centre</h1><p>Explore aviation professions, learn career skills and complete educational challenges.</p><div class="notice"><b>{{done_count}} / {{total}} challenges completed</b></div></section>
<div class="grid">{% for role in careers %}<article class="card"><span class="tag">CAREER PATH</span><h2>{{role[1]}}</h2><p>{{role[2]}}</p><p class="muted">{{role[3]}}</p><h3>Training challenges</h3>{% for ch in challenges if ch[0]==role[0] %}<div class="notice"><b>{{ch[2]}}</b><p>{{ch[3]}}</p>{% if (role[0],ch[1]) in done %}<span>✓ Completed</span>{% else %}<form method="post"><input type="hidden" name="action" value="complete"><input type="hidden" name="career_key" value="{{role[0]}}"><input type="hidden" name="challenge_key" value="{{ch[1]}}"><button>Complete learning challenge</button></form>{% endif %}</div>{% endfor %}<form method="post"><input type="hidden" name="action" value="apply"><input type="hidden" name="role_key" value="{{role[0]}}"><label>Why does this career interest you?<textarea name="motivation" minlength="20" maxlength="500" required></textarea></label><button>Submit fictional career application</button></form></article>{% endfor %}</div>
<section class="card"><h2>🏅 Your Career Record</h2><p>Completed challenges: {{done_count}}. Your progress and badges are saved to your account.</p>{% for a in applications %}<p>Application: {{a['role_key']}} · {{a['status']}} · {{a['created_at'][:10]}}</p>{% endfor %}</section>
<div class="notice">Educational career exploration only. Applications are fictional in-app activities, not real job applications, recruitment, professional qualifications or licences. Never submit private contact, school, address or identity details.</div>""", careers=CAREERS, challenges=challenges, done=done, done_count=len(done), total=len(challenges), applications=applications)

@app.route('/owner/careers', methods=['GET','POST'])
@owner_required
def owner_careers():
 c=db()
 if request.method=='POST':
  key=request.form.get('career_key',''); title=(request.form.get('title') or '').strip(); desc=(request.form.get('description') or '').strip()
  if key not in [x[0] for x in CAREERS] or not 4<=len(title)<=80 or not 10<=len(desc)<=400:
   flash('Check the career, title and description lengths.','error')
  else:
   c.execute('INSERT INTO career_challenges(career_key,title,description,created_at) VALUES(?,?,?,?)',(key,title,desc,datetime.utcnow().isoformat()))
   c.commit(); audit_owner_action('career_challenge_created',None,title); flash('Career challenge published.')
  return redirect(url_for('owner_careers'))
 rows=c.execute('SELECT career_key,title,description FROM career_challenges ORDER BY id DESC').fetchall()
 return page('Owner Career Management',r"""<section class="hero"><span class="tag">OWNER HQ · STAGE 13</span><h1>👑 Career Management</h1><p>Create additional educational challenges for members.</p></section><div class="card"><form method="post"><label>Career<select name="career_key">{% for r in careers %}<option value="{{r[0]}}">{{r[1]}}</option>{% endfor %}</select></label><label>Challenge title<input name="title" minlength="4" maxlength="80" required></label><label>Description<input name="description" minlength="10" maxlength="400" required></label><button>Publish challenge</button></form></div><div class="card"><h2>Published challenges</h2>{% for r in rows %}<p><b>{{r['title']}}</b> · {{r['career_key']}} — {{r['description']}}</p>{% else %}<p>No custom challenges yet.</p>{% endfor %}</div>""", careers=CAREERS, rows=rows)


# Stage 14 redesign: Virtual Aviation Experience replaces the Career Skills Test.
# All activities are fictional, educational mini-missions; they do not teach real aircraft
# operation, air-traffic control instructions, or emergency procedures.
AVIATION_MISSIONS = [
 ('airport-welcome','🏢 Airport Manager','The airport is busy and several passengers need help finding their gates. What is the best first step?', ['Give everyone a different guess','Direct passengers to official information desks and clear airport signs','Close the terminal'], 1, 'Good airport management starts with clear information and organised passenger support.'),
 ('terminal-team','🏢 Airport Manager','A queue is getting longer at a check-in area. Which response best supports the team?', ['Coordinate with the responsible supervisor and communicate the queue issue','Ignore it','Make promises about departure times'], 0, 'Team communication helps staff respond appropriately.'),
 ('world-explorer','🌍 World Explorer','You are planning a fictional trip to a country you have never visited. What should you check first?', ['Only the souvenirs','Reliable destination information and current entry requirements with a trusted adult','A random social-media comment'], 1, 'Reliable, current travel information matters.'),
 ('passport-stamp','🌍 World Explorer','What does a passport stamp represent in this AIR TRAVEL learning game?', ['A real visa approval','A fictional record of a destination explored in the app','Permission to board any flight'], 1, 'In-app stamps are collectibles only; they are not travel documents.'),
 ('aircraft-museum','🛩 Aircraft Explorer','You are viewing an aircraft in the virtual museum. What is a good way to learn about it?', ['Read its museum information card and compare its general features','Try to operate its controls','Assume every aircraft is identical'], 0, 'Museum cards provide safe, general aircraft knowledge.'),
 ('cabin-service','🧑‍✈️ Passenger Experience','A passenger cannot find their seat number. What should a cabin crew member in this learning scenario do?', ['Speak respectfully and help them check their boarding information','Tell them to choose any seat','Ignore them'], 0, 'Respectful communication and checking approved information are important.'),
 ('weather-awareness','🌦 Weather Explorer','A travel forecast mentions possible delays due to weather. What is the sensible passenger response?', ['Check official airline or airport updates and follow staff guidance','Rely on an old forecast','Go to a restricted airport area'], 0, 'Passengers should use official updates and follow airport staff instructions.'),
 ('travel-planner','🧳 Trip Planner','Your group has different destination ideas and a limited fictional budget. What should you do?', ['Compare options together and agree on a realistic plan','Book the first option without checking','Share private payment details in public chat'], 0, 'Good planning involves comparing choices and protecting personal information.'),
]

@app.route('/career-assessment', methods=['GET','POST'])
@login_required
def career_assessment():
 c=db(); uid=current_user()['id']; result=None
 if request.method=='POST':
  key=(request.form.get('mission_key') or '').strip()
  mission=next((m for m in AVIATION_MISSIONS if m[0]==key),None)
  if mission is None:
   flash('That mission could not be found.','error')
  else:
   try: choice=int(request.form.get('choice','-1'))
   except (TypeError,ValueError): choice=-1
   if choice==mission[4]:
    c.execute('INSERT OR IGNORE INTO aviation_mission_progress(user_id,mission_key,completed_at) VALUES(?,?,?)',(uid,key,datetime.utcnow().isoformat()))
    c.commit(); result={'success':True,'title':mission[1],'feedback':mission[5]}
   else:
    result={'success':False,'title':mission[1],'feedback':'Not quite. Try again: '+mission[5]}
  # POST/redirect is used for successful completions to prevent accidental repeat submissions.
  if result and result.get('success'):
   flash('Mission completed! Your progress has been saved.'); return redirect(url_for('career_assessment'))
 rows=c.execute('SELECT mission_key FROM aviation_mission_progress WHERE user_id=?',(uid,)).fetchall()
 done={r['mission_key'] for r in rows}
 total=len(AVIATION_MISSIONS); completed=len(done); earned=completed==total
 body=r'''<section class="hero"><span class="tag">STAGE 14 REDESIGN · VIRTUAL AVIATION EXPERIENCE</span><h1>🎮 Your Aviation Adventure</h1><p>Explore airports, destinations, aircraft and passenger experience through short interactive missions.</p><div class="notice"><b>{{completed}} / {{total}} missions completed</b> · {{'🏆 Explorer badge earned!' if earned else 'Complete all missions to earn the Explorer badge.'}}</div><div style="height:12px;background:#031126;border-radius:20px;overflow:hidden;margin-top:14px"><div style="height:100%;width:{{(completed/total*100)|round(0)}}%;background:linear-gradient(90deg,#20c7ff,#68e6bd)"></div></div></section>
{% if feedback %}<div class="notice"><b>{{feedback.title}}</b><p>{{feedback.feedback}}</p></div>{% endif %}
<div class="grid">{% for m in missions %}<article class="card"><span class="tag">{{m[1]}}</span><h2>{{m[0]}}</h2><p>{{m[2]}}</p>{% if m[3] in done %}<div class="notice">✅ Mission completed</div>{% else %}<form method="post"><input type="hidden" name="mission_key" value="{{m[3]}}">{% for option in m[4] %}<label style="display:block;margin:12px 0"><input type="radio" name="choice" value="{{loop.index0}}" required> {{option}}</label>{% endfor %}<button type="submit">Complete mission</button></form>{% endif %}</article>{% endfor %}</div>
{% if earned %}<section class="card" style="text-align:center;border:2px solid #e5bd4c"><h2>🏆 AIR TRAVEL WORLD EXPLORER</h2><p>You completed every Stage 14 mission. Your badge is saved to your account.</p></section>{% endif %}
<div class="notice">This is a fictional educational game. It does not control aircraft, provide real air-traffic instructions, replace professional training, issue licences, or provide real travel authorisation. Use official airline, airport and government sources for real travel decisions. Do not enter passport numbers, payment details, addresses or other private information.</div>'''
 # If an incorrect answer was posted, show immediate feedback on the same page.
 feedback = result if result and not result.get('success') else None
 return page('Virtual Aviation Experience',body,missions=AVIATION_MISSIONS,done=done,completed=completed,total=total,earned=earned,feedback=feedback)

# ---------------------------------------------------------------------------
# Stage 29 — Airline Empire: a member-owned, fictional virtual airline game.
# It does not book real tickets, operate aircraft, or represent real airlines.
# ---------------------------------------------------------------------------
AIRLINE_AIRCRAFT = {
 'starter_turboprop': {'name':'Skyhopper Turboprop','capacity':19,'cost':550,'emoji':'🛩️'},
 'regional_jet': {'name':'Cloudline Regional Jet','capacity':90,'cost':1700,'emoji':'✈️'},
 'long_range_jet': {'name':'Horizon Long-range Jet','capacity':180,'cost':3500,'emoji':'🛫'},
}
AIRLINE_STAFF = {
 'pilots': {'label':'Virtual Pilot Team','cost':250,'max_teams':4,'team_size':2},
 'cabin': {'label':'Virtual Cabin Crew Team','cost':200,'max_teams':5,'team_size':3},
 'ground': {'label':'Virtual Ground Team','cost':150,'max_teams':5,'team_size':2},
}
AIRLINE_DESTINATIONS = ['Lagos','Abuja','London','Paris','Dubai','New York','Tokyo','Cape Town']
AIRLINE_COLOURS = ['blue','purple','teal','gold','coral']
AIRLINE_EMOJIS = ['✈️','🛫','🌍','☁️','⭐','🦅','🛩️']


def _airline_member_or_redirect():
 u=current_user()
 if not u:
  flash('Please sign in to build your virtual airline.','error')
  return None
 if u['role']!='member':
  flash('Use a member account to play Airline Empire. Owner tools are separate.','error')
  return None
 if u['mode']!='general':
  flash('Airline Empire is part of the General Experience, not Kids World.','error')
  return None
 return u


def _airline_wallet_change(c, user_id, airline_id, delta, reason):
 # Apply a signed EXP movement atomically to the member wallet and both ledgers.
 now=datetime.utcnow().isoformat()
 fresh=c.execute('SELECT exp,role FROM users WHERE id=?',(user_id,)).fetchone()
 if not fresh or fresh['role']!='member':
  raise ValueError('A valid member wallet is required for this action.')
 if delta < 0:
  cost=-delta
  changed=c.execute('UPDATE users SET exp=exp-? WHERE id=? AND exp>=?',(cost,user_id,cost)).rowcount
  if changed!=1:
   raise ValueError('Not enough EXP. Your balance has not been changed.')
 else:
  c.execute('UPDATE users SET exp=exp+? WHERE id=?',(delta,user_id))
 c.execute('INSERT INTO transactions(user_id,amount,reason,created_at) VALUES(?,?,?,?)',(user_id,delta,reason,now))
 c.execute('INSERT INTO airline_ledger(airline_id,user_id,amount,reason,created_at) VALUES(?,?,?,?,?)',(airline_id,user_id,delta,reason,now))


@app.route('/airline-empire',methods=['GET','POST'])
@login_required
def airline_empire():
 u=_airline_member_or_redirect()
 if not u:
  return redirect(url_for('home'))
 c=db(); uid=u['id']
 airline=c.execute('SELECT * FROM airlines WHERE owner_user_id=?',(uid,)).fetchone()
 if request.method=='POST':
  action=request.form.get('action','').strip()
  if not airline and action=='create':
   name=request.form.get('name','').strip()
   code=request.form.get('code','').strip().upper()
   emoji=request.form.get('emoji','✈️').strip()
   colour=request.form.get('colour','blue').strip()
   if len(name)<3 or len(name)>40 or not re.fullmatch(r'[A-Z0-9]{2,4}',code) or emoji not in AIRLINE_EMOJIS or colour not in AIRLINE_COLOURS:
    flash('Enter an airline name (3–40 characters), a 2–4 character airline code, and choose an available logo and colour.','error')
   else:
    try:
     c.execute('INSERT INTO airlines(owner_user_id,name,code,brand_emoji,brand_color,created_at) VALUES(?,?,?,?,?,?)',(uid,name,code,emoji,colour,datetime.utcnow().isoformat()))
     c.commit(); flash('Your virtual airline has been created! Welcome to Airline Empire.')
    except sqlite3.IntegrityError:
     c.rollback(); flash('That airline code is already being used. Choose another code.','error')
   return redirect(url_for('airline_empire'))
  if not airline:
   flash('Create your virtual airline before using the management tools.','error')
   return redirect(url_for('airline_empire'))
  if airline['status']!='active':
   flash('This virtual airline is currently paused by Owner HQ.','error')
   return redirect(url_for('airline_empire'))
  try:
   c.execute('BEGIN IMMEDIATE')
   # Recheck ownership and status inside the write transaction.
   fresh_airline=c.execute('SELECT * FROM airlines WHERE id=? AND owner_user_id=?',(airline['id'],uid)).fetchone()
   if not fresh_airline or fresh_airline['status']!='active':
    raise ValueError('Your airline is unavailable.')
   if action=='buy_aircraft':
    key=request.form.get('aircraft_key','')
    aircraft=AIRLINE_AIRCRAFT.get(key)
    if not aircraft: raise ValueError('Choose a valid aircraft model.')
    owned=c.execute('SELECT COUNT(*) FROM airline_fleet WHERE airline_id=?',(airline['id'],)).fetchone()[0]
    if owned>=12: raise ValueError('Your fleet has reached the limit of 12 virtual aircraft.')
    _airline_wallet_change(c,uid,airline['id'],-aircraft['cost'],'Airline Empire: '+aircraft['name']+' purchase')
    c.execute('INSERT INTO airline_fleet(airline_id,aircraft_key,aircraft_name,capacity,purchase_cost,created_at) VALUES(?,?,?,?,?,?)',(airline['id'],key,aircraft['name'],aircraft['capacity'],aircraft['cost'],datetime.utcnow().isoformat()))
    flash(f"{aircraft['name']} has joined your virtual fleet!")
   elif action=='open_route':
    origin=request.form.get('origin',''); destination=request.form.get('destination','')
    if origin not in AIRLINE_DESTINATIONS or destination not in AIRLINE_DESTINATIONS or origin==destination:
     raise ValueError('Choose two different destinations from the approved destination list.')
    route_count=c.execute('SELECT COUNT(*) FROM airline_routes WHERE airline_id=?',(airline['id'],)).fetchone()[0]
    if route_count>=12: raise ValueError('Your airline has reached the limit of 12 virtual routes.')
    _airline_wallet_change(c,uid,airline['id'],-150,f'Airline Empire: opened {origin}–{destination} virtual route')
    c.execute('INSERT INTO airline_routes(airline_id,origin,destination,route_fee,created_at) VALUES(?,?,?,?,?)',(airline['id'],origin,destination,250,datetime.utcnow().isoformat()))
    flash(f'Virtual route opened: {origin} → {destination}.')
   elif action=='hire_staff':
    key=request.form.get('role_key',''); staff=AIRLINE_STAFF.get(key)
    if not staff: raise ValueError('Choose a valid virtual staff team.')
    current=c.execute('SELECT teams FROM airline_staff WHERE airline_id=? AND role_key=?',(airline['id'],key)).fetchone()
    teams=current['teams'] if current else 0
    if teams>=staff['max_teams']: raise ValueError('You have reached the team limit for this role.')
    _airline_wallet_change(c,uid,airline['id'],-staff['cost'],'Airline Empire: '+staff['label']+' recruitment')
    c.execute('INSERT INTO airline_staff(airline_id,role_key,role_label,teams,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(airline_id,role_key) DO UPDATE SET teams=airline_staff.teams+1,updated_at=excluded.updated_at',(airline['id'],key,staff['label'],1,datetime.utcnow().isoformat()))
    flash(staff['label']+' added to your virtual airline team.')
   elif action=='schedule_flight':
    try: route_id=int(request.form.get('route_id','0')); aircraft_id=int(request.form.get('aircraft_id','0'))
    except ValueError: raise ValueError('Choose a valid route and aircraft.')
    scheduled_at=request.form.get('scheduled_at','').strip()
    try:
     parsed=datetime.strptime(scheduled_at,'%Y-%m-%dT%H:%M')
    except ValueError: raise ValueError('Choose a valid date and time for your virtual flight.')
    now_wat=datetime.now(timezone(timedelta(hours=1))).replace(tzinfo=None,second=0,microsecond=0)
    if parsed<now_wat or parsed>now_wat+timedelta(days=90): raise ValueError('Choose a virtual flight time between now and the next 90 days (Nigeria time).')
    open_flights=c.execute("SELECT COUNT(*) FROM airline_flights WHERE airline_id=? AND status='scheduled'",(airline['id'],)).fetchone()[0]
    if open_flights>=5: raise ValueError('You can have up to five scheduled virtual flights at a time.')
    route=c.execute('SELECT id FROM airline_routes WHERE id=? AND airline_id=?',(route_id,airline['id'])).fetchone()
    aircraft=c.execute('SELECT id FROM airline_fleet WHERE id=? AND airline_id=?',(aircraft_id,airline['id'])).fetchone()
    pilots=c.execute("SELECT COALESCE(teams,0) FROM airline_staff WHERE airline_id=? AND role_key='pilots'",(airline['id'],)).fetchone()
    if not route or not aircraft: raise ValueError('Choose a route and aircraft belonging to your airline.')
    if not pilots or pilots[0]<1: raise ValueError('Recruit at least one Virtual Pilot Team before scheduling flights.')
    c.execute('INSERT INTO airline_flights(airline_id,route_id,aircraft_id,scheduled_at,created_at) VALUES(?,?,?,?,?)',(airline['id'],route_id,aircraft_id,scheduled_at,datetime.utcnow().isoformat()))
    flash('Your virtual flight has been scheduled!')
   elif action=='operate_flight':
    try: flight_id=int(request.form.get('flight_id','0'))
    except ValueError: raise ValueError('Choose a valid virtual flight.')
    flight=c.execute('''SELECT f.*,a.capacity,r.origin,r.destination FROM airline_flights f
      JOIN airline_fleet a ON a.id=f.aircraft_id AND a.airline_id=f.airline_id
      JOIN airline_routes r ON r.id=f.route_id AND r.airline_id=f.airline_id
      WHERE f.id=? AND f.airline_id=?''',(flight_id,airline['id'])).fetchone()
    if not flight or flight['status']!='scheduled': raise ValueError('That flight is not available to complete.')
    if flight['scheduled_at']>datetime.now(timezone(timedelta(hours=1))).strftime('%Y-%m-%dT%H:%M'):
     raise ValueError('This virtual flight is not due yet. Return at its scheduled Nigeria time.')
    pilots=c.execute("SELECT COALESCE(teams,0) FROM airline_staff WHERE airline_id=? AND role_key='pilots'",(airline['id'],)).fetchone()
    if not pilots or pilots[0]<1: raise ValueError('A Virtual Pilot Team is required to complete this flight.')
    local_now=datetime.now(timezone(timedelta(hours=1)))
    local_start=local_now.replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    local_end=(local_now.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None).isoformat()
    completed_today=c.execute("SELECT COUNT(*) FROM airline_flights WHERE airline_id=? AND status='completed' AND completed_at>=? AND completed_at<?",(airline['id'],local_start,local_end)).fetchone()[0]
    if completed_today>=5: raise ValueError('Your airline has reached the daily limit of five completed virtual flights. Come back tomorrow.')
    reward=50 + min(int(flight['capacity']),200)//2
    changed=c.execute("UPDATE airline_flights SET status='completed',reward_exp=?,completed_at=? WHERE id=? AND airline_id=? AND status='scheduled'",(reward,datetime.utcnow().isoformat(),flight_id,airline['id'])).rowcount
    if changed!=1: raise ValueError('This flight has already been processed.')
    c.execute('UPDATE airlines SET completed_flights=completed_flights+1,reputation=reputation+10 WHERE id=?',(airline['id'],))
    _airline_wallet_change(c,uid,airline['id'],reward,f'Airline Empire: virtual flight {flight["origin"]}–{flight["destination"]} completed')
    flash(f'Virtual flight completed! Your airline earned {reward} EXP and 10 reputation points.')
   elif action=='cancel_flight':
    try: flight_id=int(request.form.get('flight_id','0'))
    except ValueError: raise ValueError('Choose a valid virtual flight.')
    changed=c.execute("UPDATE airline_flights SET status='cancelled' WHERE id=? AND airline_id=? AND status='scheduled'",(flight_id,airline['id'])).rowcount
    if changed!=1: raise ValueError('That flight cannot be cancelled.')
    flash('Virtual flight cancelled. No EXP was charged or refunded.')
   else:
    raise ValueError('Unknown Airline Empire action.')
   c.commit()
  except ValueError as e:
   c.rollback(); flash(str(e),'error')
  except sqlite3.IntegrityError:
   c.rollback(); flash('That route or action already exists. No EXP was deducted.','error')
  except sqlite3.Error:
   c.rollback(); app.logger.exception('Airline Empire transaction failed'); flash('The action could not be completed. No EXP was deducted. Please try again.','error')
  return redirect(url_for('airline_empire'))

  # no-op: redirect above handles all supported POSTs

  
 if airline:
  airline=c.execute('SELECT * FROM airlines WHERE owner_user_id=?',(uid,)).fetchone()
  fleet=c.execute('SELECT * FROM airline_fleet WHERE airline_id=? ORDER BY id',(airline['id'],)).fetchall()
  routes=c.execute('SELECT * FROM airline_routes WHERE airline_id=? ORDER BY id',(airline['id'],)).fetchall()
  staff=c.execute('SELECT * FROM airline_staff WHERE airline_id=? ORDER BY id',(airline['id'],)).fetchall()
  flights=c.execute('''SELECT f.*,r.origin,r.destination,a.aircraft_name FROM airline_flights f
   JOIN airline_routes r ON r.id=f.route_id AND r.airline_id=f.airline_id
   JOIN airline_fleet a ON a.id=f.aircraft_id AND a.airline_id=f.airline_id
   WHERE f.airline_id=? ORDER BY CASE f.status WHEN 'scheduled' THEN 0 WHEN 'completed' THEN 1 ELSE 2 END, f.scheduled_at DESC LIMIT 30''',(airline['id'],)).fetchall()
  ledger=c.execute('SELECT * FROM airline_ledger WHERE airline_id=? ORDER BY id DESC LIMIT 20',(airline['id'],)).fetchall()
 else:
  fleet=routes=staff=flights=ledger=[]
 leaderboard=c.execute('''SELECT a.name,a.code,a.brand_emoji,a.reputation,a.completed_flights
   FROM airlines a WHERE a.status='active'
   ORDER BY a.completed_flights DESC,a.reputation DESC,a.created_at ASC LIMIT 10''').fetchall()
 competition=c.execute('SELECT * FROM airline_competition WHERE id=1').fetchone()
 return page('Airline Empire','''
<section class="airline-hero"><span class="tag">STAGE 29 · BUILD YOUR VIRTUAL AIRLINE</span><h1>✈️ Airline Empire</h1>
<p>Start an airline, build a virtual fleet, open destination routes, recruit your team and schedule fictional game flights. Earn EXP for completed virtual missions and climb the airline rankings.</p>
<p class="muted">This is a fictional in-app simulation. It does not book real tickets, operate aircraft, provide real flight schedules or control real airlines.</p>
<p class="balance">Your member wallet: {{'{:,}'.format(user['exp'])}} EXP</p></section>
<div class="airline-card" style="margin:16px 0"><span class="tag">🏆 CURRENT LEAGUE</span><h2>{{competition['title']}}</h2><p>{{competition['description']}}</p></div>
{% if not airline %}
<div class="airline-card"><h2>🏢 Create your airline</h2><p>Every member can create one virtual airline. Pick a name and short code that other members can recognise.</p>
<form method="post"><input type="hidden" name="action" value="create"><label>Airline name</label><input name="name" minlength="3" maxlength="40" placeholder="e.g. Cloudline Airways" required><label>Airline code (2–4 letters or numbers)</label><input name="code" minlength="2" maxlength="4" pattern="[A-Za-z0-9]{2,4}" placeholder="e.g. CLD" required><label>Logo</label><select name="emoji">{% for e in emojis %}<option value="{{e}}">{{e}}</option>{% endfor %}</select><label>Brand colour</label><select name="colour">{% for colour in colours %}<option value="{{colour}}">{{colour|title}}</option>{% endfor %}</select><button>Create my virtual airline</button></form><p class="muted">Creating an airline is free. Purchases and upgrades cost virtual EXP only.</p></div>
{% else %}
<div class="airline-card"><div class="airline-brand"><div class="airline-logo">{{airline['brand_emoji']}}</div><div><span class="tag">{{airline['code']}}</span><h2 style="margin:5px 0">{{airline['name']}}</h2><p class="muted">Founded {{airline['created_at'][:10]}} · {{airline['status']|title}}</p></div></div>
<div class="airline-grid"><div><span class="muted">Completed virtual flights</span><div class="airline-stat">{{airline['completed_flights']}}</div></div><div><span class="muted">Reputation points</span><div class="airline-stat">{{airline['reputation']}}</div></div><div><span class="muted">Fleet aircraft</span><div class="airline-stat">{{fleet|length}}</div></div><div><span class="muted">Destination routes</span><div class="airline-stat">{{routes|length}}</div></div></div></div>
{% if airline['status']=='active' %}
<div class="airline-grid">
<div class="airline-card"><h3>🛫 Build your fleet</h3><p class="muted">Choose a virtual aircraft for your airline. Fleet limit: 12.</p>{% for key,ac in aircraft.items() %}<div class="airline-row"><div><b>{{ac['emoji']}} {{ac['name']}}</b><br><small>{{ac['capacity']}} virtual seats · {{'{:,}'.format(ac['cost'])}} EXP</small></div><form method="post"><input type="hidden" name="action" value="buy_aircraft"><input type="hidden" name="aircraft_key" value="{{key}}"><button>Purchase</button></form></div>{% endfor %}
<h4>Your aircraft</h4>{% for a in fleet %}<div class="airline-row"><span>{{a['aircraft_name']}} · {{a['capacity']}} seats</span><span class="tag">FLEET #{{a['id']}}</span></div>{% else %}<p class="muted">Your fleet is empty. Purchase an aircraft to continue.</p>{% endfor %}</div>
<div class="airline-card"><h3>🌍 Open a destination route</h3><p class="muted">Each virtual route costs 150 EXP. Limit: 12 routes.</p><form method="post"><input type="hidden" name="action" value="open_route"><label>From</label><select name="origin">{% for d in destinations %}<option>{{d}}</option>{% endfor %}</select><label>To</label><select name="destination">{% for d in destinations %}<option>{{d}}</option>{% endfor %}</select><button>Open route · 150 EXP</button></form><h4>Your routes</h4>{% for r in routes %}<div class="airline-row"><span>{{r['origin']}} → {{r['destination']}}</span><span class="tag">OPEN</span></div>{% else %}<p class="muted">No routes open yet.</p>{% endfor %}</div>
<div class="airline-card"><h3>🧑‍✈️ Recruit your virtual team</h3><p class="muted">Teams are fictional game characters, not real people hired for work.</p>{% for key,st in staff_options.items() %}<div class="airline-row"><div><b>{{st['label']}}</b><br><small>{{st['team_size']}} virtual staff · {{'{:,}'.format(st['cost'])}} EXP per team</small></div><form method="post"><input type="hidden" name="action" value="hire_staff"><input type="hidden" name="role_key" value="{{key}}"><button>Recruit</button></form></div>{% endfor %}<h4>Your teams</h4>{% for st in staff %}<div class="airline-row"><span>{{st['role_label']}}</span><b>{{st['teams']}} teams</b></div>{% else %}<p class="muted">No virtual teams hired yet.</p>{% endfor %}</div>
</div>
<div class="airline-card"><h2>📅 Virtual Flight Scheduler</h2><p>Schedule fictional game flights using one of your routes and aircraft. At least one Virtual Pilot Team is required. Times use Nigeria time (WAT).</p>
{% if routes and fleet %}<form method="post"><input type="hidden" name="action" value="schedule_flight"><label>Route</label><select name="route_id">{% for r in routes %}<option value="{{r['id']}}">{{r['origin']}} → {{r['destination']}}</option>{% endfor %}</select><label>Aircraft</label><select name="aircraft_id">{% for a in fleet %}<option value="{{a['id']}}">{{a['aircraft_name']}} ({{a['capacity']}} seats)</option>{% endfor %}</select><label>Departure date and time (Nigeria time)</label><input type="datetime-local" name="scheduled_at" required><button>Schedule virtual flight</button></form>{% else %}<p class="notice">Open at least one route and purchase an aircraft before scheduling a flight.</p>{% endif %}
<div class="airline-table-wrap"><table class="airline-table"><thead><tr><th>Flight</th><th>Aircraft</th><th>Scheduled (WAT)</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for f in flights %}<tr><td>{{f['origin']}} → {{f['destination']}}</td><td>{{f['aircraft_name']}}</td><td>{{f['scheduled_at'].replace('T',' ')}}</td><td>{{f['status']|title}}</td><td>{% if f['status']=='scheduled' %}<form method="post" style="display:inline"><input type="hidden" name="action" value="operate_flight"><input type="hidden" name="flight_id" value="{{f['id']}}"><button>Complete mission</button></form> <form method="post" style="display:inline"><input type="hidden" name="action" value="cancel_flight"><input type="hidden" name="flight_id" value="{{f['id']}}"><button class="btn alt">Cancel</button></form>{% elif f['status']=='completed' %}<span class="tag">+{{f['reward_exp']}} EXP</span>{% else %}<span class="muted">—</span>{% endif %}</td></tr>{% else %}<tr><td colspan="5">No virtual flights scheduled yet.</td></tr>{% endfor %}</tbody></table></div></div>
<div class="airline-card"><h2>💼 Airline Finance Ledger</h2><p class="muted">EXP movements are recorded here and in your main wallet transaction history.</p>{% for item in ledger %}<div class="airline-row"><div><b>{{item['reason']}}</b><br><small>{{item['created_at'][:16].replace('T',' ')}}</small></div><b class="{{'stat' if item['amount']>=0 else ''}}">{{'+' if item['amount']>0 else ''}}{{'{:,}'.format(item['amount'])}} EXP</b></div>{% else %}<p>No airline finance activity yet.</p>{% endfor %}</div>
{% else %}<div class="notice error">Your airline is paused by Owner HQ. You can view its details, but management actions are disabled.</div>{% endif %}
{% endif %}
<div class="airline-card"><h2>🏆 Airline Empire Leaderboard</h2><p class="muted">Top 10 active virtual airlines, ranked by completed game flights and then reputation. This is not a ranking of real airlines.</p><div class="airline-table-wrap"><table class="airline-table"><thead><tr><th>#</th><th>Airline</th><th>Code</th><th>Virtual flights</th><th>Reputation</th></tr></thead><tbody>{% for a in leaderboard %}<tr><td>{{loop.index}}</td><td>{{a['brand_emoji']}} {{a['name']}}</td><td><span class="airline-code">{{a['code']}}</span></td><td>{{a['completed_flights']}}</td><td>{{a['reputation']}}</td></tr>{% else %}<tr><td colspan="5">No active airlines yet. Create the first one!</td></tr>{% endfor %}</tbody></table></div></div>
<div class="notice">EXP is a fictional in-app score, not cash. No real tickets are sold, no real flights are scheduled, and no real airline services are provided. Purchases are optional and should never be funded with real money for this game.</div>
''',airline=airline,fleet=fleet,routes=routes,staff=staff,flights=flights,ledger=ledger,leaderboard=leaderboard,competition=competition,aircraft=AIRLINE_AIRCRAFT,staff_options=AIRLINE_STAFF,destinations=AIRLINE_DESTINATIONS,emojis=AIRLINE_EMOJIS,colours=AIRLINE_COLOURS)


@app.route('/owner/airline-empire',methods=['GET','POST'])
@owner_required
def owner_airline_empire():
 c=db()
 if request.method=='POST':
  action=request.form.get('action','')
  if action=='competition':
   title=request.form.get('title','').strip()[:80]
   description=request.form.get('description','').strip()[:500]
   if len(title)<3 or len(description)<10:
    flash('Enter a competition title and a description of at least 10 characters.','error')
   else:
    c.execute('UPDATE airline_competition SET title=?,description=?,updated_at=?,updated_by=? WHERE id=1',(title,description,datetime.utcnow().isoformat(),current_user()['id']))
    audit_owner_action('Airline league challenge updated',None,title)
    c.commit(); flash('The Airline Empire league challenge has been updated.')
  elif action=='status':
   try: airline_id=int(request.form.get('airline_id','0'))
   except ValueError: airline_id=0
   status=request.form.get('status','')
   if status not in ('active','suspended'):
    flash('Invalid airline status.','error')
   else:
    row=c.execute('SELECT name FROM airlines WHERE id=?',(airline_id,)).fetchone()
    if not row: flash('Airline not found.','error')
    else:
     c.execute('UPDATE airlines SET status=? WHERE id=?',(status,airline_id))
     audit_owner_action('Virtual airline status changed',None,f"{row['name']} → {status}")
     c.commit(); flash('Virtual airline status updated.')
  return redirect(url_for('owner_airline_empire'))
 competition=c.execute('SELECT * FROM airline_competition WHERE id=1').fetchone()
 airlines=c.execute('''SELECT a.*,u.name AS member_name,u.username,
  (SELECT COUNT(*) FROM airline_fleet f WHERE f.airline_id=a.id) AS fleet_count,
  (SELECT COUNT(*) FROM airline_routes r WHERE r.airline_id=a.id) AS route_count
  FROM airlines a JOIN users u ON u.id=a.owner_user_id ORDER BY a.created_at DESC LIMIT 100''').fetchall()
 stats=c.execute('''SELECT COUNT(*) AS airlines,
  COALESCE(SUM(completed_flights),0) AS flights,
  COALESCE(SUM(reputation),0) AS reputation,
  (SELECT COUNT(*) FROM airline_fleet) AS aircraft,
  (SELECT COUNT(*) FROM airline_routes) AS routes FROM airlines''').fetchone()
 return page('Owner Airline Control','''<section class="airline-hero"><span class="tag">PRIVATE OWNER HQ · STAGE 29</span><h1>👑 Airline Empire Control</h1><p>Monitor virtual airlines, view aggregate game activity, manage the active league challenge and pause accounts that need review.</p><p><a class="btn alt" href="{{url_for('owner_dashboard')}}">← Return to Owner HQ</a> <a class="btn" href="{{url_for('airline_empire')}}">View public game page</a></p></section>
<div class="airline-grid"><div class="airline-card"><small class="muted">VIRTUAL AIRLINES</small><div class="airline-stat">{{stats['airlines']}}</div></div><div class="airline-card"><small class="muted">VIRTUAL FLIGHTS COMPLETED</small><div class="airline-stat">{{stats['flights']}}</div></div><div class="airline-card"><small class="muted">FLEET AIRCRAFT</small><div class="airline-stat">{{stats['aircraft']}}</div></div><div class="airline-card"><small class="muted">OPEN ROUTES</small><div class="airline-stat">{{stats['routes']}}</div></div></div>
<div class="airline-card"><h2>🏆 Manage the league challenge</h2><form method="post"><input type="hidden" name="action" value="competition"><label>Challenge title</label><input name="title" maxlength="80" minlength="3" value="{{competition['title']}}" required><label>Challenge description</label><textarea name="description" maxlength="500" minlength="10" required>{{competition['description']}}</textarea><button>Save league challenge</button></form></div>
<div class="airline-card"><h2>🏢 Member virtual airlines</h2><p class="muted">Only the member's airline name and username are shown here. No password, email, EXP balance or private profile information is displayed.</p><div class="airline-table-wrap"><table class="airline-table"><thead><tr><th>Airline</th><th>Member</th><th>Fleet</th><th>Routes</th><th>Flights</th><th>Status</th><th>Action</th></tr></thead><tbody>{% for a in airlines %}<tr><td>{{a['brand_emoji']}} {{a['name']}} <small>({{a['code']}})</small></td><td>{{a['member_name']}} · @{{a['username']}}</td><td>{{a['fleet_count']}}</td><td>{{a['route_count']}}</td><td>{{a['completed_flights']}}</td><td>{{a['status']|title}}</td><td><form method="post"><input type="hidden" name="action" value="status"><input type="hidden" name="airline_id" value="{{a['id']}}"><input type="hidden" name="status" value="{{'suspended' if a['status']=='active' else 'active'}}"><button class="btn alt">{{'Pause' if a['status']=='active' else 'Restore'}}</button></form></td></tr>{% else %}<tr><td colspan="7">No member airlines created yet.</td></tr>{% endfor %}</tbody></table></div></div>''',competition=competition,airlines=airlines,stats=stats)


@app.route('/healthz')
def health(): return {'ok':True,'app':'AIR TRAVEL'}
init_db()
if __name__=='__main__': app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=False)
