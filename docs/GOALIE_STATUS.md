# Goalie Status Management System

## Overview

The goalie status system allows captains to self-manage their team's goalie availability for upcoming games, and provides a public status board showing which games need substitute goalies.

## URLs

| Page | URL | Access |
|------|-----|--------|
| Public Status Board | `/goalie-status/` | Anyone |
| Captain Update Page | `/goalie-status/captain/<access_code>/` | Team captains (secret URL) |

## For Admins

### Getting Captain URLs

To get the list of captain URLs for all current season teams:

```bash
# Production (Render shell)
python manage.py list_captain_urls

# Local development
python manage.py list_captain_urls --base-url http://127.0.0.1:8000

# All active teams (not just current season)
python manage.py list_captain_urls --all
```

### Setting Primary Goalie

1. Go to Django Admin → Teams → Select a team
2. In the Roster section, find the goalie entries
3. Check **"Is primary goalie"** for the team's main goalie
4. This goalie will be the default in dropdowns and status displays

### Quick Add Goalie Sub

1. Go to Django Admin → MatchUps
2. Click **"Add Goalie Sub"** button (top right)
3. Enter the sub's name and select the team
4. The player is created and added to the roster automatically

### Player Activation

- **View inactive players**: Player list → Filter by "Active Status" → "Inactive"
- **Re-activate a player**: Edit player → Check "Is active"
- **Protect from auto-deactivation**: Check "Exclude from auto deactivation"

## For Captains

### Accessing Your Captain Page

Each team has a unique secret URL for updating goalie status. The URL looks like:
```
https://dcstreethockey.com/goalie-status/captain/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/
```

**Keep this URL private** - anyone with it can update your team's goalie status.

### Updating Goalie Status

1. Open your team's captain URL
2. You'll see all upcoming games for your team
3. For each game:
   - **Status**: Set to "Confirmed", "Sub Needed", or "Unconfirmed"
   - **Goalie**: Select your roster goalie or choose a different sub from the dropdown
4. Click **"Update"** to save

### Status Meanings

| Status | Meaning |
|--------|---------|
| ✅ **Confirmed** | Goalie is confirmed to play |
| ❌ **Sub Needed** | Team needs a substitute goalie |
| ⏳ **Unconfirmed** | Captain hasn't confirmed availability yet |

### Tips

- When you set status to "Sub Needed", the goalie field is automatically cleared
- When you set status to "Unconfirmed", it defaults back to your roster goalie
- Changes are saved immediately when you click Update

## Public Status Board

The public board at `/goalie-status/` shows:
- All upcoming games for current seasons
- Goalie status for each team
- Alert banner showing how many games need subs

This helps substitute goalies see where they're needed.
