# Interactive Bot DM Menus

## Overview

The bot now provides **persistent interactive menus** in DMs, allowing users to navigate and interact with events using buttons instead of typing commands.

## Features

### 1. Main Menu (`/start`)

When users type `/start` or `/help`, they see a main menu with buttons:

```
👋 Welcome, User!

I'm your coordination bot. I help organize group events with AI-powered scheduling.

💡 Use the menu buttons below to navigate instead of typing commands!

[📋 My Events]  [👤 My Profile]
[⭐ My Reputation]  [📜 My History]
[✏️ Organize Event]  [🔧 Modify Event]
[👥 My Groups]  [❓ Help]
```

### 2. Events List with Clickable Buttons

When users click **"📋 My Events"**:

- Shows paginated list of events (5 per page)
- Each event displayed as: **ID + 3-word description**
- **Clickable buttons** for each event
- Navigation buttons (Previous/Next)

Example:
```
📋 Your Events

1. ID `123` - Dinner at Mario's
   04-10 19:00 | proposed | Social Group

2. ID `124` - Weekend hiking trip
   04-12 09:00 | confirmed | Outdoor Club

[1. Dinner at Mario's (#123)]  ← Clickable button
[2. Weekend hiking trip (#124)] ← Clickable button
[⬅️ Prev]  [Next ➡️]
[🔙 Back to Main Menu]
```

### 3. Event Detail View with Action Buttons

When users click on an event button, they see:

- Full event details (using existing formatters)
- **Context-aware action buttons** based on:
  - User's participation status (not joined/joined/confirmed)
  - Event state (proposed/interested/confirmed/locked)

Example for user who hasn't joined:
```
📊 Event #123 Status

Type: social
Description: Dinner at Mario's
Time: Evening (6PM-10PM)
Location Type: Cafe/Restaurant
Budget: Budget-friendly

[✅ Join Event]
[📊 Status]  [📝 Details]
[📅 Set Availability]
[🔙 Back to Events List]  [🏠 Main Menu]
```

Example for user who has joined:
```
[✅ Confirm]  [❌ Cancel]
[📊 Status]  [📝 Details]
[📅 Set Availability]
[🔙 Back to Events List]  [🏠 Main Menu]
```

### 4. Help Menu

Interactive help with topics:
```
❓ Help & Information

[📖 Getting Started]  [🎯 How Events Work]
[📅 Scheduling]  [⭐ Reputation]
[🔙 Back to Main Menu]
```

## Files Added/Modified

### New Files
- `bot/common/menus.py` - Keyboard builders for menus
- `bot/handlers/menus.py` - Callback handlers for menu interactions

### Modified Files
- `bot/commands/start.py` - Shows main menu on /start
- `main.py` - Registers menu callback handler

## Menu Navigation Flow

```
/start
  ↓
Main Menu
  ↓
[My Events] → Events List (paginated with buttons)
  ↓
[Click Event #123] → Event Detail View
  ↓
[Join/Confirm/Status/etc.] → Existing handlers process action
  ↓
Returns to event detail or appropriate view
```

## Callback Pattern

All menu callbacks use pattern: `menu_<action>_<params>`

Examples:
- `menu_main` - Show main menu
- `menu_my_events` - Show events list
- `menu_events_next_0` - Next page from page 0
- `menu_event_select_123` - Select event #123
- `menu_my_profile` - Show profile
- `menu_help` - Show help menu
- `help_start` - Show getting started topic

## Benefits

1. **No need to remember commands** - Everything accessible via buttons
2. **Faster navigation** - One tap instead of typing `/events` then finding ID then typing `/event_details 123`
3. **Visual event discovery** - See events with descriptions at a glance
4. **Context-aware actions** - Buttons change based on user status and event state
5. **Reduced errors** - Can't mistype event IDs or commands
6. **Better UX** - Modern, intuitive interface

## Extending Menus

To add a new menu button:

1. Add button to `build_main_menu()` in `bot/common/menus.py`
2. Add handler in `bot/handlers/menus.py`
3. Register callback route in `main.py` (if needed)

Example:
```python
# In menus.py
def build_main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📋 My Events", callback_data="menu_my_events"),
            InlineKeyboardButton("🆕 New Feature", callback_data="menu_new_feature"),
        ],
        ...
    ]

# In handlers/menus.py
async def handle_menu_callback(...):
    if data == "menu_new_feature":
        await _show_new_feature(query, context)
```

## Future Enhancements

Possible improvements:
- [ ] Persistent bottom menu bar (ReplyKeyboardMarkup) that always shows
- [ ] Search/filter events in list
- [ ] Quick actions (join all proposed events)
- [ ] Notifications settings via menu
- [ ] Settings/preferences menu
- [ ] Direct event creation via menu wizard
