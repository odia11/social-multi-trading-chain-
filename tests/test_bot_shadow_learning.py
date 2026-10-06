import os, sqlite3, tempfile, time
import bot_shadow_learning as sl


def token(mint, now, price=1.0, age_min=120, change=8.0, score=7.5):
    return {
        'mint': mint, 'symbol': mint[:6], 'price': price, 'score': score,
        'change5m': change, 'change1h': change,
        'pairCreatedAt': int((now-age_min*60)*1000),
        'market_cap': 1_000_000, 'liquidity': 150_000,
        'txns_buys': 150, 'txns_sells': 100,
        'volume5m': 20_000, 'volume1h': 100_000,
    }


def fresh_db():
    return os.path.join(tempfile.mkdtemp(prefix='shadow-learning-'), 'x.db')


checks=[]
def check(name, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name)


db=fresh_db()
base=1_800_000_000.0
check('below +7% is never added to the shadow dataset',
      not sl.observe(db, token('LOW', base, change=6.9), now=base))
check('+7% candidate is observed without user/account input',
      sl.observe(db, token('GOOD0', base, change=7.0), now=base))
with sqlite3.connect(db) as c:
    cols=[r[1] for r in c.execute('PRAGMA table_info(bot_shadow_candidates)').fetchall()]
check('shadow table has no user id, wallet, balance or private data columns',
      not any(x in cols for x in ('user_id','wallet','wallet_address','balance','private_key')))

# A candidate remains the same paper episode across a 6h bucket boundary and
# keeps being tracked even after its current move falls back below +7%.
edge_start=(int(base//sl.EPISODE_SEC)+2)*sl.EPISODE_SEC-120
edge=token('EDGE',edge_start,price=1.0,age_min=30,change=8.0)
check('edge episode starts at +7%+', sl.observe(db,edge,now=edge_start))
edge_later=token('EDGE',edge_start+sl.HORIZON_SEC+1,price=0.91,age_min=90,change=1.0)
check('existing episode resolves even after momentum falls below +7%',
      sl.observe(db,edge_later,now=edge_start+sl.HORIZON_SEC+1))
with sqlite3.connect(db) as c:
    edge_row=c.execute("SELECT resolved,ret_60m FROM bot_shadow_candidates WHERE mint='EDGE' ORDER BY first_seen").fetchone()
check('cross-bucket episode is resolved once with the 60m outcome',
      edge_row[0]==1 and edge_row[1] < -8)

# If it disappears from the normal scanner, due_mints/resolve_price can finish
# the sample from a bounded fresh public price read.
due_start=edge_start+sl.EPISODE_SEC
check('off-list test candidate starts',sl.observe(db,token('DUE',due_start,change=8.0),now=due_start))
due_at=due_start+sl.HORIZON_SEC+5
check('off-list candidate becomes due for resolution','DUE' in sl.due_mints(db,due_at,limit=5))
check('bounded fresh-price resolver finishes the due sample',sl.resolve_price(db,'DUE',0.93,due_at))
with sqlite3.connect(db) as c:
    due_row=c.execute("SELECT resolved,ret_60m FROM bot_shadow_candidates WHERE mint='DUE'").fetchone()
check('due sample is a real resolved loss, not silently dropped',due_row[0]==1 and due_row[1] < -6)

# Build 50 resolved public-market examples. The only systematically bad feature
# is "under 15 minutes old": 20 examples lose 12%; 30 older examples gain 6%.
for i in range(50):
    mint='Y%03d'%i if i<20 else 'O%03d'%i
    age=5 if i<20 else 120
    start=base + i*sl.EPISODE_SEC
    first=token(mint,start,price=1.0,age_min=age,change=8.0)
    second=token(mint,start+sl.HORIZON_SEC+1,price=(0.88 if i<20 else 1.06),
                 age_min=age+60,change=8.0)
    check('observe start '+mint, sl.observe(db, first, now=start))
    check('resolve '+mint, sl.observe(db, second, now=start+sl.HORIZON_SEC+1))

st=sl.status(db)
check('market brain waits for enough resolved paper examples', st['resolved'] >= sl.MIN_RESOLVED)
check('stable bad young-token pattern becomes a veto',
      'token under 15 min old' in st['avoid'])

now=time.time()
young=token('LIVEY',now,age_min=5,change=8.0)
older=token('LIVEO',now,age_min=120,change=8.0)
check('learned public-market rule vetoes matching weak setup',
      sl.veto_reason(db,young)=='token under 15 min old')
check('same model does not veto the otherwise-identical older setup',
      sl.veto_reason(db,older)!='token under 15 min old')

# A veto is one-way: module has no API that approves or executes a buy.
check('shadow module exposes no buy/execute/position mutator',
      not any(hasattr(sl,n) for n in ('buy','execute','open_position','set_take_profit','set_stop_loss')))

# Pure random public outcomes should almost never create a learned veto.
import random
false_positive=0
for seed in range(12):
    ndb=fresh_db()
    rng=random.Random(9000+seed)
    with sqlite3.connect(ndb) as c:
        sl._ensure(c)
        for i in range(100):
            age=rng.choice([5,30,120,600,2000])
            score=rng.uniform(5,10)
            mcap=10**rng.uniform(4.8,7.2)
            bsr=rng.uniform(.4,3.0)
            liq=10**rng.uniform(4.2,6.0)
            mom=rng.uniform(7,45)
            accel=rng.uniform(.4,2.5)
            ret=rng.gauss(1.0,12.0)
            c.execute("""INSERT INTO bot_shadow_candidates(
 mint,episode,symbol,first_seen,last_seen,entry_price,last_price,max_price,min_price,
 entry_score,pair_age_minutes,market_cap,buy_sell_ratio,liquidity,change5m,change1h,
 volume_accel,ret_60m,max_gain_60m,max_drawdown_60m,resolved)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                      ('N'+str(i),i,'N',base+i,base+i+3600,1,1+ret/100,1.2,.8,
                       score,age,mcap,bsr,liq,mom,mom,accel,ret,max(0,ret+5),max(0,5-ret)))
        c.commit()
    false_positive += bool(sl.status(ndb)['avoid'])
check('random shadow histories rarely invent a public-market veto ('+str(false_positive)+'/12)',
      false_positive <= 1)

raise SystemExit(0 if all(checks) else 1)
