# T11 — Extract presentation from the domain

**Tier 2 · platform surface · area: presentation / i18n**
**Depends on:** T06
**Blocks:** a coherent web/mobile UI

## Why

Content is currently produced as Telegram-rendered strings deep inside domain
code:

- **106 locale strings contain markup** — `<b>`, `<i>`, `<a href>` — in
  `locales/en.json` and `locales/fa.json` (586 keys each)
- **63 `parse_mode` sites** across `bot/`
- `event_presenters.py` and `event_formatters.py` build display strings
  from models, mixing formatting with data access

A web client cannot consume `<b>bold</b>` in a JSON field safely, and a mobile
client certainly cannot. Meanwhile the same strings cannot be reused, because
the markup is baked in.

## What to do

### 1. Separate content from rendering

Domain emits structured data; each transport renders:

```python
# domain
EventSummary(title=..., when=..., confirmed=3, needed=5, organizer=UserRef(...))

# telegram renderer -> "<b>Dinner</b> — 3/5 confirmed"
# web renderer      -> JSON, styled by the client
```

`core/notifier.py`'s `Message`/`Action` split is the same idea applied to
outbound messages; this extends it to read models.

### 2. Strip markup from locale files

Locale values become plain text with placeholders. Emphasis becomes a property
of the *renderer*, not the string. This is also what makes the strings
translatable without translators handling HTML.

Where emphasis is semantic, keep it structured (a field marked "prominent")
rather than embedding tags.

### 3. Move `i18n` out of `bot/`

`bot/common/i18n.py` is transport-neutral already — it loads JSON and
substitutes. It belongs in `core/`. Language resolution currently reaches into
`user_data`; it should read from `user_preferences` (which exists) so every
transport agrees.

### 4. Persian is a first-class constraint

`fa.json` is complete. RTL is a **layout** problem, not a translation one:

- bidirectional text mixing Persian with Latin names, times, `@usernames`
- date/number formatting — consider whether Jalali calendar display is wanted
- mirrored layout in the web/mobile UI, not just `dir="rtl"`

Getting this into the design system from the start is far cheaper than
retrofitting. It also constrains the component library choice.

## Acceptance criteria

- [ ] No HTML tags in `locales/*.json`
- [ ] Domain services return structured read models, not rendered strings
- [ ] Telegram output is byte-identical to today for a sample of flows
- [ ] The same read model renders correctly in a web client
- [ ] RTL verified with mixed Persian/Latin content, not just Persian

## Notes for the target architecture

This is the largest *mechanical* ticket in Tier 2 and the easiest to defer —
which is exactly why it tends to get skipped until the web UI is half-built
and every string needs revisiting. Doing the locale de-markup early is cheap;
doing it after two clients depend on the strings is not.
