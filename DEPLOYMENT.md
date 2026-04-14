# NexusOps â€” Deployment & Versioning Guide

> **Current Version:** `v1.0.0-prod`
> **Versioning Standard:** [Semantic Versioning 2.0.0](https://semver.org/)
> **Changelog Format:** [Keep a Changelog](https://keepachangelog.com/)

---

## Table of Contents

1. [Versioning Strategy](#1-versioning-strategy)
2. [Git Branching Model](#2-git-branching-model)
3. [Release Workflow](#3-release-workflow)
4. [Deployment Environments](#4-deployment-environments)
5. [Deployment Steps](#5-deployment-steps)
6. [Rollback Procedure](#6-rollback-procedure)
7. [Health Checks & Monitoring](#7-health-checks--monitoring)
8. [Docker Deployment](#8-docker-deployment)
9. [CI/CD Pipeline](#9-cicd-pipeline)
10. [Quick Reference Commands](#10-quick-reference-commands)

---

## 1. Versioning Strategy

### Semantic Versioning (SemVer)

```
MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]
```

| Component    | When to Increment                                     | Example     |
|-------------|-------------------------------------------------------|-------------|
| **MAJOR**   | Breaking changes (DB schema, API contract, auth flow) | `2.0.0`     |
| **MINOR**   | New features (backward-compatible)                    | `1.1.0`     |
| **PATCH**   | Bug fixes, security patches                           | `1.0.1`     |
| **PRE**     | Pre-release testing                                   | `1.1.0-rc.1`|
| **BUILD**   | Environment metadata                                  | `1.0.0+prod`|

### Version Source of Truth

| File                    | Purpose                                        |
|------------------------|------------------------------------------------|
| `inventory/version.py` | **Primary** â€” Python-accessible version info   |
| `VERSION`              | Plain-text file for Docker, CI/CD, scripts     |
| `CHANGELOG.md`         | Human-readable release history                 |

### When to Bump

```
Feature complete      â†’ bump MINOR   (1.0.0 â†’ 1.1.0)
Hotfix / bugfix       â†’ bump PATCH   (1.0.0 â†’ 1.0.1)
Breaking migration    â†’ bump MAJOR   (1.0.0 â†’ 2.0.0)
Internal testing      â†’ set PRE      (1.1.0-beta.1)
Production release    â†’ clear PRE    (1.1.0)
```

---

## 2. Git Branching Model

```
main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â— v1.0.0 â”€â”€â— v1.0.1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â— v1.1.0
                  â”‚                                â”‚
develop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â— feature-x â”€â”€â”€â”€â”€â”€â”˜
                  â”‚              â”‚
                  â””â”€â”€â”€ hotfix/login-fix â”€â”€â”˜
```

| Branch      | Purpose                     | Deploys To  |
|------------|-------------------------------|-------------|
| `main`     | Production-ready releases     | Production  |
| `develop`  | Integration branch            | Staging     |
| `feature/*`| New features                 | (local/PR)  |
| `hotfix/*` | Urgent production fixes      | Production  |
| `release/*`| Release candidates           | Staging     |

### Branch Rules

- **Never push directly to `main`** â€” always merge via PR
- **`develop`** auto-deploys to staging on every push
- **Tags** (`v*`) trigger production deployments

---

## 3. Release Workflow

### Standard Release (Feature Cycle)

```bash
# 1. Ensure develop is stable
git checkout develop
python manage.py test

# 2. Bump version
python manage.py release --bump minor --tag
# Output: 1.0.0 â†’ 1.1.0 + creates git tag v1.1.0

# 3. Update CHANGELOG.md
# Move items from [Unreleased] to [1.1.0] section

# 4. Commit and push
git add inventory/version.py VERSION CHANGELOG.md
git commit -m "release: v1.1.0"
git push origin develop
git push origin v1.1.0

# 5. Create PR: develop â†’ main
# After approval and merge, CI/CD deploys to production
```

### Hotfix Release

```bash
# 1. Branch from main
git checkout main
git checkout -b hotfix/critical-fix

# 2. Fix the issue
# ... make changes ...

# 3. Bump patch version
python manage.py release --bump patch --tag

# 4. Commit and push
git add -A
git commit -m "hotfix: v1.0.1 â€” fix critical login issue"
git push origin hotfix/critical-fix
git push origin v1.0.1

# 5. Create PR to main AND develop
```

### Pre-release

```bash
# Create a release candidate
python manage.py release --bump minor --pre rc.1 --tag
# â†’ 1.1.0-rc.1

# If testing passes, finalize:
python manage.py release --bump minor --tag
# â†’ 1.1.0
```

---

## 4. Deployment Environments

| Environment  | URL                          | Branch   | Auto-deploy? |
|-------------|------------------------------|----------|-------------|
| Development | `http://localhost:8000`       | any      | N/A         |
| Staging     | `https://staging.NexusOps.com` | `develop` | Yes (CI/CD) |
| Production  | `https://NexusOps.com`    | `main` (tagged) | Yes (on tag) |

### Environment Variables

Each environment uses its own `.env` file. See `.env.example` for the template.

| Variable              | Dev                | Staging            | Production            |
|----------------------|--------------------|--------------------|----------------------|
| `NexusOps_ENV`       | `dev`              | `staging`          | `prod`               |
| `DJANGO_DEBUG`       | `True`             | `False`            | `False`              |
| `DJANGO_SECRET_KEY`  | (default insecure) | (unique per env)   | (unique per env)     |
| `DJANGO_ALLOWED_HOSTS`| `127.0.0.1,localhost` | staging domain  | `NexusOps.com`   |

---

## 5. Deployment Steps

### A. Manual Deployment (Current â€” Direct Server)

```bash
# SSH into the server
ssh user@13.49.238.18

# Navigate to project
cd /opt/NexusOps

# Enable maintenance mode
python manage.py maintenance --on --message "Upgrading to v1.1.0"

# Pull latest code
git fetch --tags
git checkout v1.1.0

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Disable maintenance mode
python manage.py maintenance --off

# Restart the application server
sudo systemctl restart gunicorn
# or
sudo systemctl restart NexusOps
```

### B. Docker Deployment

```bash
# Pull and restart
docker compose pull
docker compose up -d --remove-orphans

# Run migrations inside container
docker compose exec web python manage.py migrate --noinput
docker compose exec web python manage.py collectstatic --noinput

# Check health
curl -s http://localhost:8000/api/health/ | python -m json.tool
```

### C. AWS EC2 Deployment

```bash
# 1. SSH into EC2
ssh -i ~/.ssh/NexusOps-key.pem ubuntu@13.49.238.18

# 2. Pull latest
cd /opt/NexusOps
git pull origin main

# 3. Activate virtualenv
source venv/bin/activate

# 4. Install deps + migrate + static
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 5. Restart Gunicorn
sudo systemctl restart gunicorn
```

---

## 6. Rollback Procedure

### Immediate Rollback (< 5 minutes)

```bash
# 1. Enable maintenance mode
python manage.py maintenance --on --message "Rolling back. Please wait."

# 2. Checkout previous version
git checkout v1.0.0

# 3. Reinstall deps (if changed)
pip install -r requirements.txt

# 4. Reverse migrations (if needed â€” check before deploying!)
python manage.py migrate products 0006  # Roll back to migration 0006

# 5. Restart
sudo systemctl restart gunicorn

# 6. Disable maintenance mode
python manage.py maintenance --off
```

### Docker Rollback

```bash
# Roll back to specific image version
docker compose down
docker compose pull NexusOps:1.0.0
docker compose up -d
```

### Database Rollback (from pre-deploy backup)

```bash
# Restore from backup
cp backups/pre-deploy-20260228-143000.json .
python manage.py loaddata pre-deploy-20260228-143000.json
```

---

## 7. Health Checks & Monitoring

### Endpoints

| Endpoint           | Method | Auth     | Purpose                     |
|-------------------|--------|----------|-----------------------------|
| `/api/health/`    | GET    | None     | Load balancer health check  |
| `/api/health/?full=1` | GET | Superuser | Detailed diagnostics    |
| `/api/version/`   | GET    | None     | Version info                |

### Health Check Response

```json
{
    "status": "healthy",
    "version": "1.0.0",
    "full_version": "1.0.0+prod",
    "environment": "prod"
}
```

### Monitoring Checklist

- [ ] Health check returns 200
- [ ] Version matches expected deployment
- [ ] Database connectivity confirmed
- [ ] Static files serving correctly
- [ ] Login flow works
- [ ] Key pages load within 2s

---

## 8. Docker Deployment

### Build

```bash
# Build with version tag
docker build -t NexusOps:$(cat VERSION) .
docker tag NexusOps:$(cat VERSION) NexusOps:latest

# Push to registry
docker push ghcr.io/philips-/NexusOps:$(cat VERSION)
docker push ghcr.io/philips-/NexusOps:latest
```

### Run

```bash
# Development
docker compose up

# Production (includes Nginx)
docker compose --profile production up -d
```

---

## 9. CI/CD Pipeline

The GitHub Actions pipeline (`.github/workflows/ci-cd.yml`) automates:

| Trigger                  | Actions                          |
|-------------------------|----------------------------------|
| PR to `main`            | Lint + Test                      |
| Push to `develop`       | Test â†’ Build â†’ Deploy Staging    |
| Push to `main`          | Test â†’ Build                     |
| Tag `v*`                | Test â†’ Build â†’ Deploy Production |

### Required GitHub Secrets

| Secret              | Description                    |
|--------------------|--------------------------------|
| `STAGING_HOST`     | Staging server IP/hostname     |
| `STAGING_USER`     | SSH user for staging           |
| `STAGING_SSH_KEY`  | SSH private key for staging    |
| `PRODUCTION_HOST`  | Production server IP/hostname  |
| `PRODUCTION_USER`  | SSH user for production        |
| `PRODUCTION_SSH_KEY`| SSH private key for production|

---

## 10. Quick Reference Commands

```bash
# â”€â”€ Version Management â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
python manage.py release --show              # Show current version
python manage.py release --bump patch        # 1.0.0 â†’ 1.0.1
python manage.py release --bump minor        # 1.0.0 â†’ 1.1.0
python manage.py release --bump major        # 1.0.0 â†’ 2.0.0
python manage.py release --bump minor --tag  # Bump + git tag
python manage.py release --bump patch --pre rc.1  # Pre-release
python manage.py release --tag-only          # Tag current version
python manage.py release --bump patch --dry-run  # Preview changes

# â”€â”€ Maintenance Mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
python manage.py maintenance --on --message "Deploying v1.1.0"
python manage.py maintenance --on --duration 30m
python manage.py maintenance --off
python manage.py maintenance --status

# â”€â”€ Health Check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
curl http://localhost:8000/api/health/
curl http://localhost:8000/api/version/

# â”€â”€ Docker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
docker build -t NexusOps:$(cat VERSION) .
docker compose up -d
docker compose logs -f web

# â”€â”€ Backup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
python manage.py dumpdata --natural-foreign -o backups/backup-$(date +%Y%m%d).json
```

---

## File Structure (Deployment-related)

```
NexusOps/
â”œâ”€â”€ VERSION                          # Plain-text version (e.g. "1.0.0")
â”œâ”€â”€ CHANGELOG.md                     # Release history
â”œâ”€â”€ DEPLOYMENT.md                    # This file
â”œâ”€â”€ MAINTENANCE.md                   # Maintenance mode docs
â”œâ”€â”€ Dockerfile                       # Multi-stage production build
â”œâ”€â”€ docker-compose.yml               # Docker Compose orchestration
â”œâ”€â”€ .dockerignore                    # Docker build exclusions
â”œâ”€â”€ .env.example                     # Environment variable template
â”œâ”€â”€ .gitignore                       # Git exclusions
â”œâ”€â”€ .github/
â”‚   â””â”€â”€ workflows/
â”‚       â””â”€â”€ ci-cd.yml                # GitHub Actions CI/CD pipeline
â”œâ”€â”€ deploy/
â”‚   â””â”€â”€ nginx/
â”‚       â””â”€â”€ nginx.conf               # Nginx reverse proxy config
â”œâ”€â”€ inventory/
â”‚   â”œâ”€â”€ version.py                   # Version source of truth
â”‚   â””â”€â”€ settings.py                  # Env-aware Django settings
â””â”€â”€ products/
    â”œâ”€â”€ context_processors.py        # Version context for templates
    â””â”€â”€ management/
        â””â”€â”€ commands/
            â””â”€â”€ release.py           # Release management command
```
