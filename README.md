# Telegram Auto Class Indexer — Bot Only

This version does **not** use Telethon, API_ID/API_HASH, a user login, or a session string.

## Setup
1. Create a new Telegram channel.
2. Add this bot as an administrator with permission to post/manage messages (reading channel posts is automatic for admins).
3. Put only `BOT_TOKEN` in Railway Variables.
4. Deploy.
5. Start the bot with `/start`.
6. Post classes in the channel. Every new channel post is automatically indexed.

## Important
The bot intentionally does not scan old channel history. Telegram Bot API bots cannot use the historical `getHistory` method. Therefore, for this no-login design, add the bot before posting classes.

## Commands
- `/start` — library
- `/search <topic>` — search indexed classes
- `/id` — your Telegram ID

There is no owner-only restriction and there is no `/scan` history command. Indexing happens automatically when a new channel post arrives.

## Suggested post format
TITLE: Part-1 सामान्य पशुपालन — नवीनतम पशुगणना — 02-January
BATCH: agriculture MCQ

The bot groups Part-1/Part-2/etc. under one topic and creates buttons that open the original channel post.
