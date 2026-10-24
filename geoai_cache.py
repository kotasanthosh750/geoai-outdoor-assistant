import sqlite3, json, time, threading, os
DB = os.environ.get("CACHE_DB", "/tmp/geoai_cache.db")
_lock = threading.Lock()

def _conn():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("create table if not exists kv(k text primary key, v text, exp real)")
    return c

def get(key):
    with _lock:
        c = _conn(); r = c.execute("select v,exp from kv where k=?", (key,)).fetchone(); c.close()
    return json.loads(r[0]) if r and r[1] > time.time() else None

def put(key, val, ttl):
    with _lock:
        c = _conn()
        c.execute("insert or replace into kv values(?,?,?)", (key, json.dumps(val), time.time() + ttl))
        c.commit(); c.close()
