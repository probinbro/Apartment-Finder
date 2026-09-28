# Apartment Finder

A full-stack apartment marketplace built with **Django**, **Supabase Auth**, **Supabase PostgreSQL** and **Supabase Storage**.
Guests browse and search listings, registered users manage their profile and submit their own homes for rent,
and admins review submissions and manage listings, images and users.

## Features

- Public site: homepage with search, listings with filters/sorting/pagination, detail pages with photo gallery
- Accounts via **Supabase Auth**: email/password, **Continue with Google**, email confirmation, session refresh
- **List your home**: users submit properties → admins approve or reject (with a note) → approved listings go live
- Admin panel: dashboard, listing requests, apartment CRUD, publish/unpublish, image manager (upload, primary, replace, delete), media library, users & roles, property types/amenities, contact messages
- Images validated and re-encoded with **Pillow** (type/size checks, EXIF stripped), stored in Supabase Storage
- Row Level Security enabled on every table; the service-role key never reaches the browser
- 80 automated tests (Supabase is mocked)

## Tech stack

Python 3.12+ · Django 6 · Supabase (Auth, PostgreSQL, Storage) · Pillow · HTML/CSS/vanilla JS · WhiteNoise · Gunicorn (production)

## Project structure

```text
config/          settings, root URLs, WSGI
core/            home/about/contact, Supabase REST client + storage backend, image processing, RLS, template tags
users/           profile model, Supabase auth backend, login/register/Google/logout, session refresh middleware
apartments/      listing models, search filters, public views, "list your home" owner views, demo data
admin_panel/     admin dashboard and management views
templates/       base layout, reusable partials, page templates
static/          css/main.css, js/main.js, js/auth-callback.js
tests/           automated test suite
```

## Local setup (Windows)

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # then fill in the values (see below)
python manage.py migrate
python manage.py setup_storage   # creates the public image bucket (needs the service-role/secret key)
python manage.py seed_demo       # optional: 12 demo listings with real photos
python manage.py runserver
```

Open http://127.0.0.1:8000.

### Environment variables

| Variable | Description |
|---|---|
| `DEBUG` | `True` locally, `False` in production |
| `SECRET_KEY` | Django secret key (long random string) |
| `DATABASE_URL` | Supabase **Transaction pooler** connection string (port 6543). URL-encode special characters in the password (`@` → `%40`) |
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_ANON_KEY` | Publishable / anon key (safe for public use) |
| `SUPABASE_SERVICE_ROLE_KEY` | **Secret** key (`sb_secret_...`). Server-side only — used for Storage uploads |
| `SUPABASE_STORAGE_BUCKET` | Bucket name, default `apartment-media` |
| `SUPABASE_OAUTH_PROVIDERS` | `google` to show the Google button (after enabling it in Supabase) |
| `SITE_URL` | Public URL of the site (auto-detected on Render) |

Never commit `.env` — it is in `.gitignore`.

### Supabase setup

1. **Database** – Dashboard → *Connect* → copy the *Transaction pooler* URI into `DATABASE_URL`.
   `python manage.py migrate` creates all tables and enables Row Level Security automatically.
2. **Storage** – set `SUPABASE_SERVICE_ROLE_KEY`, then run `python manage.py setup_storage`.
   Images are stored as `apartments/<apartment-id>/<file>.jpg`.
3. **Auth URLs** – Authentication → *URL Configuration*: set **Site URL** to your site and add
   `<your-site>/auth/callback/` (e.g. `http://127.0.0.1:8000/auth/callback/`) to **Redirect URLs**.
4. **Google login** – create an OAuth *Web application* client in Google Cloud Console with the redirect URI
   `https://<project-ref>.supabase.co/auth/v1/callback`, then paste its Client ID/Secret into
   Supabase → Authentication → Providers → Google, and set `SUPABASE_OAUTH_PROVIDERS=google`.

### Admin account

Register on the site (or sign in with Google) once, then:

```bash
python manage.py make_admin you@example.com
```

## Deploying to Render (free)

GitHub Pages only serves static HTML, so it cannot run Django. Use Render instead:

1. **Move images to Supabase Storage first** (a web host can't see files on your computer):
   put your secret key in `.env` as `SUPABASE_SERVICE_ROLE_KEY`, then run
   `python manage.py setup_storage` and `python manage.py seed_demo --reset`.
2. Push this repository to GitHub.
3. On https://render.com → **New → Blueprint** → select the repository. Render reads `render.yaml`.
4. Fill in the secret environment variables when prompted: `DATABASE_URL`, `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` (same values as your `.env`).
5. Wait for the build (`build.sh` installs packages, collects static files and runs migrations).
6. In Supabase → Authentication → URL Configuration, set Site URL to `https://<your-app>.onrender.com`
   and add `https://<your-app>.onrender.com/auth/callback/` to Redirect URLs.

Free Render services sleep after inactivity; the first request after a while takes ~30–60 seconds.

## Tests

```bash
python manage.py test tests
```

Tests run against a local SQLite database with in-memory storage and a mocked Supabase — no network needed.

## Demo photo credits

Demo photos come from Wikimedia Commons under CC0 / CC BY / CC BY-SA licences. Each image caption credits
its author and licence; source pages are listed in `apartments/demo/listings.json`.

## Future improvements

Favorites/saved apartments · map view (lat/long fields already exist) · reviews · messaging owners ·
email notifications for listing approvals · recommendations · full-text search.
