# Maintenance Mode — Quick Reference

## Commands

```bash
# Enable maintenance mode (indefinite — stays on until you turn it off)
python manage.py maintenance --on

# Enable with a custom message (shown to users)
python manage.py maintenance --on --message "Upgrading database. Back by 5 PM IST."

# Enable for a specific duration (auto-expires when timer runs out)
python manage.py maintenance --on --duration 3d                           # 3 days
python manage.py maintenance --on --duration 6h                           # 6 hours
python manage.py maintenance --on --duration 30m                          # 30 minutes
python manage.py maintenance --on --duration 2h --message "Quick patch"   # duration + message

# Disable maintenance mode immediately (site goes live)
python manage.py maintenance --off

# Check current status (shows remaining time if a duration was set)
python manage.py maintenance --status
```

## Duration Format

| Value  | Meaning     |
|--------|-------------|
| `30m`  | 30 minutes  |
| `2h`   | 2 hours     |
| `1.5h` | 1.5 hours   |
| `3d`   | 3 days      |

When a duration is set, users see a **live countdown timer** on the maintenance page.
Maintenance **auto-disables** when the timer expires — no manual `--off` needed.

## How It Works

| Detail               | Description                                                                 |
|----------------------|-----------------------------------------------------------------------------|
| **Trigger**          | Creates / deletes a `maintenance.flag` file in the project root             |
| **No restart needed**| Takes effect instantly — no need to restart the server                       |
| **Who is blocked**   | All regular users see a 503 maintenance page                                |
| **Who can bypass**   | Superusers (logged in), `/admin/` panel, IPs in `MAINTENANCE_BYPASS_IPS`    |
| **Static/media**     | Still served normally                                                       |
| **Auto-refresh**     | The maintenance page auto-refreshes every 60 seconds for users              |

## Configuration (in `inventory/settings.py`)

```python
MAINTENANCE_MODE_FLAG_FILE = BASE_DIR / 'maintenance.flag'   # Flag file path
MAINTENANCE_BYPASS_IPS = ['127.0.0.1', '::1']               # IPs that skip maintenance
```

## Files Involved

- `products/middleware.py` → `MaintenanceMiddleware` (checks for flag file)
- `products/templates/products/maintenance.html` → the page users see
- `products/management/commands/maintenance.py` → the management command
- `inventory/settings.py` → settings (`MAINTENANCE_MODE_FLAG_FILE`, `MAINTENANCE_BYPASS_IPS`)
