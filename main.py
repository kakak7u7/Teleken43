import os
import re
import sqlite3
import logging
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger('auto-class-indexer')

BOT_TOKEN = os.getenv('BOT_TOKEN','').strip()
CHANNEL_ID_RAW = os.getenv('CHANNEL_ID','').strip()
DB_PATH = os.getenv('DB_PATH','/app/data/classes.db').strip()
PAGE_SIZE = max(5, min(int(os.getenv('PAGE_SIZE','8')), 12))

if not BOT_TOKEN:
    raise RuntimeError('Missing BOT_TOKEN environment variable.')

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

def db():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c

with db() as c:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS messages(
      channel_id INTEGER NOT NULL,
      message_id INTEGER NOT NULL,
      title TEXT NOT NULL,
      topic TEXT NOT NULL,
      topic_key TEXT NOT NULL,
      part INTEGER,
      date_text TEXT,
      link TEXT NOT NULL,
      kind TEXT,
      caption TEXT,
      PRIMARY KEY(channel_id,message_id)
    );
    CREATE INDEX IF NOT EXISTS idx_topic ON messages(channel_id,topic_key);
    CREATE TABLE IF NOT EXISTS channels(channel_id INTEGER PRIMARY KEY, title TEXT, username TEXT);
    ''')

PART_RE = re.compile(r'(?i)\bpart\s*[-_#]?\s*(\d+)\b|\bभाग\s*[-_#]?\s*(\d+)\b')
DATE_PATTERNS = [
 re.compile(r'\b\d{1,2}\s*[-/]\s*(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b',re.I),
 re.compile(r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s*[-/]\s*\d{1,2}\b',re.I),
 re.compile(r'\b\d{1,2}\s*[-/]\s*\d{1,2}(?:\s*[-/]\s*\d{2,4})?\b'),
 re.compile(r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\b',re.I),
]

def clean(s): return re.sub(r'[\u200b\u200c\u200d\ufeff]','',s or '').strip()
def one(s): return re.sub(r'\s+',' ',clean(s)).strip()
def part_of(s):
 m=PART_RE.search(s or ''); return int(m.group(1) or m.group(2)) if m else None
def date_of(s):
 for p in DATE_PATTERNS:
  m=p.search(s or '')
  if m:return m.group(0)
 return ''
def title_of(text):
 text=clean(text)
 for line in text.splitlines():
  m=re.match(r'(?i)^(?:title|tɪᴛʟᴇ)\s*[:：]\s*(.+)$',line.strip())
  if m:return one(m.group(1))
 m=re.search(r'(?i)(?:title|tɪᴛʟᴇ)\s*[:：]\s*(.+)',one(text))
 if m:return one(m.group(1))
 return one(text.splitlines()[0]) if text.splitlines() else ''
def topic_of(title):
 s=one(title)
 s=re.sub(r'(?i)\bpart\s*[-_#]?\s*\d+\b',' ',s)
 s=re.sub(r'\bभाग\s*[-_#]?\s*\d+\b',' ',s)
 for p in DATE_PATTERNS:s=p.sub(' ',s)
 s=re.sub(r'\s{2,}',' ',s).strip(' -–—:|')
 return s or 'Untitled'
def key_of(topic): return re.sub(r'\s+',' ',re.sub(r'[^\w\u0900-\u097F]+',' ',topic.casefold())).strip()
def kind(msg):
 if msg.video or msg.video_note:return '🎬 Video'
 if msg.document:return '📄 File/PDF'
 if msg.photo:return '🖼 Image'
 if msg.audio:return '🎵 Audio'
 return '📝 Text'
def link_for(chat_id,msg_id,username=None):
 if username:return f'https://t.me/{username}/{msg_id}'
 raw=str(abs(int(chat_id)))
 if raw.startswith('100'): return f'https://t.me/c/{raw[3:]}/{msg_id}'
 return ''
def allowed_channel(chat_id):
 if not CHANNEL_ID_RAW:return True
 try:return int(CHANNEL_ID_RAW)==int(chat_id)
 except:return False

def index_message(msg, chat):
 if not msg:return False
 text=msg.text or msg.caption or ''
 if not text and not (msg.video or msg.document or msg.photo or msg.audio):return False
 title=title_of(text) or f'Message {msg.message_id}'
 topic=topic_of(title); key=key_of(topic); part=part_of(title); date=date_of(title)
 link=link_for(chat.id,msg.message_id,getattr(chat,'username',None))
 if not link:
  log.warning('Could not build link for channel %s',chat.id); return False
 with db() as c:
  c.execute('INSERT INTO messages(channel_id,message_id,title,topic,topic_key,part,date_text,link,kind,caption) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(channel_id,message_id) DO UPDATE SET title=excluded.title,topic=excluded.topic,topic_key=excluded.topic_key,part=excluded.part,date_text=excluded.date_text,link=excluded.link,kind=excluded.kind,caption=excluded.caption',
   (chat.id,msg.message_id,title,topic,key,part,date,link,kind(msg),text[:4000]))
  c.execute('INSERT INTO channels(channel_id,title,username) VALUES(?,?,?) ON CONFLICT(channel_id) DO UPDATE SET title=excluded.title,username=excluded.username',(chat.id,chat.title or '',getattr(chat,'username',None)))
 return True

def stats():
 with db() as c:
  return (c.execute('SELECT COUNT(DISTINCT topic_key) n FROM messages').fetchone()['n'],
          c.execute('SELECT COUNT(*) n FROM messages').fetchone()['n'],
          c.execute("SELECT COUNT(*) n FROM messages WHERE kind='🎬 Video'").fetchone()['n'],
          c.execute("SELECT COUNT(*) n FROM messages WHERE kind='📄 File/PDF'").fetchone()['n'])

def topics(page=0):
 with db() as c:
  rows=c.execute('SELECT topic_key,MIN(topic) topic,COUNT(*) cnt FROM messages GROUP BY topic_key ORDER BY MIN(message_id) LIMIT ? OFFSET ?',(PAGE_SIZE,page*PAGE_SIZE)).fetchall()
  total=c.execute('SELECT COUNT(DISTINCT topic_key) n FROM messages').fetchone()['n']
 return rows,total

def topic_items(key):
 with db() as c:return c.execute('SELECT title,part,date_text,link,kind FROM messages WHERE topic_key=? ORDER BY CASE WHEN part IS NULL THEN 999999 ELSE part END,message_id',(key,)).fetchall()
def token(key):
 import hashlib; return hashlib.sha256(key.encode()).hexdigest()[:16]
def key_from_token(t):
 with db() as c: rows=c.execute('SELECT DISTINCT topic_key FROM messages').fetchall()
 for r in rows:
  if token(r['topic_key'])==t:return r['topic_key']
 return None

def home():
 t,p,v,f=stats()
 return f'📚 **MY CLASS LIBRARY**\n\n📚 Topics: **{t}**\n🎓 Classes: **{p}**\n🎬 Videos: **{v}**\n📄 Files: **{f}**\n\nChoose an option:', InlineKeyboardMarkup([
  [InlineKeyboardButton('🔎 Search Class',callback_data='search_help'),InlineKeyboardButton('📚 All Topics',callback_data='topics:0')],
  [InlineKeyboardButton('📊 Statistics',callback_data='stats')],
 ])

async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE): await update.message.reply_text(*home(),parse_mode='Markdown')
async def myid(update:Update,ctx:ContextTypes.DEFAULT_TYPE): await update.message.reply_text(f'🆔 Your Telegram user ID: `{update.effective_user.id}`',parse_mode='Markdown')
async def search(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
 q=' '.join(ctx.args).strip().casefold()
 if not q:return await update.message.reply_text('🔎 Use: `/search नवीनतम पशुगणना`',parse_mode='Markdown')
 with db() as c: rows=c.execute('SELECT topic_key,MIN(topic) topic,COUNT(*) cnt FROM messages WHERE lower(topic) LIKE ? OR lower(title) LIKE ? OR lower(caption) LIKE ? GROUP BY topic_key ORDER BY MIN(message_id) LIMIT 30',(f'%{q}%',f'%{q}%',f'%{q}%')).fetchall()
 if not rows:return await update.message.reply_text('❌ No matching class/topic found.')
 buttons=[[InlineKeyboardButton(f"📂 {r['topic'][:48]} ({r['cnt']})",callback_data=f"topic:{token(r['topic_key'])}")] for r in rows]
 await update.message.reply_text(f'🔎 **SEARCH:** {q}',reply_markup=InlineKeyboardMarkup(buttons),parse_mode='Markdown')

async def channel_post(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
 msg=update.channel_post; chat=update.effective_chat
 if not allowed_channel(chat.id):return
 try:
  if index_message(msg,chat):log.info('Indexed %s / %s',chat.id,msg.message_id)
 except Exception:log.exception('Auto-index failed')

async def topics_cb(q):
 page=int(q.data.split(':')[1]); rows,total=topics(page); pages=max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)
 text=f'📚 **ALL TOPICS** — Page {page+1}/{pages}\n\n'; buttons=[]
 for r in rows:
  text+=f"📂 **{r['topic']}** — {r['cnt']} classes\n"; buttons.append([InlineKeyboardButton(r['topic'][:55],callback_data=f"topic:{token(r['topic_key'])}")])
 nav=[]
 if page>0:nav.append(InlineKeyboardButton('◀️ Previous',callback_data=f'topics:{page-1}'))
 if (page+1)*PAGE_SIZE<total:nav.append(InlineKeyboardButton('Next ▶️',callback_data=f'topics:{page+1}'))
 if nav:buttons.append(nav)
 buttons.append([InlineKeyboardButton('🏠 Home',callback_data='home')])
 await q.edit_message_text(text,reply_markup=InlineKeyboardMarkup(buttons),parse_mode='Markdown')

async def callback(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
 q=update.callback_query; await q.answer(); d=q.data
 if d=='home': await q.edit_message_text(*home(),parse_mode='Markdown'); return
 if d=='stats':
  t,p,v,f=stats(); await q.edit_message_text(f'📊 **STATISTICS**\n\n📚 Topics: **{t}**\n🎓 Classes: **{p}**\n🎬 Videos: **{v}**\n📄 Files: **{f}**',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🏠 Home',callback_data='home')]]),parse_mode='Markdown'); return
 if d=='search_help': await q.edit_message_text('🔎 Search from chat using:\n`/search topic name`',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🏠 Home',callback_data='home')]]),parse_mode='Markdown'); return
 if d.startswith('topics:'): await topics_cb(q); return
 if d.startswith('topic:'):
  key=key_from_token(d.split(':',1)[1])
  if not key:return
  rows=topic_items(key); text=''; buttons=[]
  for i,r in enumerate(rows,1):
   label=r['title'][:90]; text+=f"{i}. {r['kind']} **{label}**"+(f" — {r['date_text']}" if r['date_text'] else '')+'\n'
   buttons.append([InlineKeyboardButton(f"🔗 Open Part {r['part']}" if r['part'] else f'🔗 Open Class {i}',url=r['link'])])
   if len(text)>3300: text+='\n…'; break
  buttons.append([InlineKeyboardButton('◀️ Topics',callback_data='topics:0'),InlineKeyboardButton('🏠 Home',callback_data='home')])
  await q.edit_message_text('📚 **'+(rows[0]['title'] if rows else key)+'**\n\n'+text,reply_markup=InlineKeyboardMarkup(buttons),parse_mode='Markdown')

async def post_init(app):
 me=await app.bot.get_me(); log.info('Bot started: @%s',me.username)

app=Application.builder().token(BOT_TOKEN).post_init(post_init).build()
app.add_handler(CommandHandler('start',start))
app.add_handler(CommandHandler('id',myid))
app.add_handler(CommandHandler('search',search))
app.add_handler(CallbackQueryHandler(callback))
app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST,channel_post))

if __name__=='__main__':
 log.info('Starting bot-only automatic indexer; no user login/session required.')
 app.run_polling(allowed_updates=Update.ALL_TYPES)
