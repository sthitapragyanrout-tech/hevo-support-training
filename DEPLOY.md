# Deploying Hevo Support Training

Everything runs in Docker on one Linux server: the web app, background workers, Postgres,
Redis and nginx (which serves the frontend and handles HTTPS). Nothing outside this repo is
needed except Docker and a domain name.

## What the server needs

- Linux with **Docker Engine and the Docker Compose plugin** (`docker compose version` works).
- About **4 CPU / 8 GB RAM / 100 GB+ disk**. Videos take most of the disk.
- **Ports 80 and 443** free (or other ports; see *If the server already runs nginx*).
- A **domain name** pointing at the server, for HTTPS. You can try it by IP address first.

## First-time setup

```bash
git clone https://github.com/sthitapragyanrout-tech/hevo-support-training.git
cd hevo-support-training
cp .env.prod.example .env.prod
```

Edit `.env.prod`. At minimum, set:

| Setting | What to put |
|---|---|
| `DJANGO_SECRET_KEY` | Output of `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `ALLOWED_HOSTS` | The domain, e.g. `training.example.com` (or the server IP for a trial) |
| `POSTGRES_PASSWORD` | A strong password, letters and digits only |
| `NGINX_SITE` | `https` if this stack handles HTTPS, `http` if something in front does |
| `OPENAI_API_KEY` | Only needed for practice tickets |

The app refuses to start without a proper secret key or `ALLOWED_HOSTS`, and says which is
missing.

Start everything, then create the database tables, the built-in roles and the first admin:

```bash
make prod-up                 # builds and starts all containers (first build takes a few minutes)
make prod-migrate            # creates tables and the six roles
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm web \
  python manage.py createsuperuser
```

Open the site and sign in as that admin. Everyone else is created from **Admin → Users**
(no self sign-up). New people get a temporary password and must change it at first sign-in.

Check it's healthy: `curl http://<server>/healthz` should return `{"ok": true}`.

## HTTPS

**Option A: this stack serves HTTPS.** Put the certificate files in `deploy/nginx/certs/`:
`fullchain.pem` (the certificate plus chain) and `privkey.pem` (the key). Set
`NGINX_SITE=https` and `USE_HTTPS=true`, then `make prod-up`. Port 80 redirects to 443. For a
free certificate, get one with certbot on the server (`certbot certonly --standalone -d <domain>`
while the stack is stopped) and copy or symlink the two files from `/etc/letsencrypt/live/<domain>/`.
These files are gitignored.

**Option B: something in front already handles HTTPS** (a load balancer, or the company's own
nginx). Keep `NGINX_SITE=http` and `USE_HTTPS=true`. The proxy in front must send
`X-Forwarded-Proto: https` and the original `Host` header.

**Trial by IP address, no certificate yet:** set `NGINX_SITE=http` and `USE_HTTPS=false`, and put
the IP in `ALLOWED_HOSTS`. Sign-in cookies are then not marked secure, so switch to A or B
before real users arrive.

## If the server already runs nginx (or something uses ports 80/443)

In `.env.prod`, move this stack off ports 80/443 and keep it reachable only from the server
itself:

```ini
NGINX_SITE=http
BIND_ADDRESS=127.0.0.1
HTTP_PORT=8080
HTTPS_PORT=8443
```

Then add a site to the existing nginx that proxies the domain to `http://127.0.0.1:8080`,
passing `Host`, `X-Forwarded-For` and `X-Forwarded-Proto`, with `client_max_body_size 1100m;`
(video uploads). That nginx handles HTTPS (Option B above).

## If the server already has a Postgres

Possible, but the bundled one is simplest. To use an existing one, create a database and user
there, remove the `postgres` service and its `depends_on` entries from
`docker-compose.prod.yml`, and set `DATABASE_URL: postgres://user:pass@host:5432/dbname` in the
`x-app` environment block instead of the line built from `POSTGRES_*`.

## Updating to a new version

```bash
git pull
make backup                  # always back up before changing the database
make prod-up                 # rebuilds and restarts what changed
make prod-migrate            # applies database changes (safe to run when there are none)
```

To roll back: `git checkout <previous commit>`, `make prod-up`, and if the update changed the
database, restore the backup taken just before (below).

## Backups

`make backup` (or `./deploy/backup/backup.sh`) writes to `backups/`:
`db-<time>.dump` (the database) and `media-<time>.tar.gz` (videos and attachments). It keeps 14
days. Run it nightly from cron:

```cron
30 1 * * * cd /path/to/hevo-support-training && ./deploy/backup/backup.sh >> backups/backup.log 2>&1
```

**Copy `backups/` somewhere off this server** (another host or object storage). A backup on
the same disk is lost with the disk.

Restore the database from a dump (this replaces the current data):

```bash
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"
$COMPOSE stop web worker-media worker-sim beat
$COMPOSE exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  < backups/db-<time>.dump
$COMPOSE start web worker-media worker-sim beat
```

Try a restore once on a spare machine. An untested backup may not work when you need it.

## Day to day

| Task | Command |
|---|---|
| See logs | `make prod-logs` |
| Restart everything | `make prod-up` |
| Stop everything | `make prod-down` (data is kept in Docker volumes) |
| Django shell | `make prod-shell` |
| Health | `curl http://<server>/healthz` |

Containers restart on their own after a crash or a reboot, as long as Docker starts on
boot (`sudo systemctl enable docker`).

## What is not set up yet

Known gaps, fine for a pilot, worth doing before a large cohort:

- **No monitoring or alerts.** Point an uptime checker at `/healthz`. There is no error tracking
  (such as Sentry) yet; errors are in `make prod-logs`.
- **Backups are local only** until you copy them off the server, and restore hasn't been drilled.
- **Notifications are in-app only**; no email is sent.
- **The Dashboard** is fine for one cohort but slows down past several hundred learners.
- **Zendesk import stays off** until data-protection sign-off (`docs/simbot.md`).
- **Certificates use the interim course score** until the final scoring model is agreed
  (`docs/scoring-open-questions.md`).

## Don't

- Don't commit `.env.prod`, certificates or backups (all are gitignored).
- Don't copy a development database to the server. Start empty and create real accounts.
- Don't set `SIMBOT_LLM=fake` in production (the app refuses to start with it).
