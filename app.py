from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os, base64, hashlib, json, time, urllib.request
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
DATABASE_URL = os.environ.get('DATABASE_URL')
UPLOAD_FOLDER = 'static/uploads'

# Cloudinary
CLOUD_NAME   = os.environ.get('CLOUDINARY_CLOUD_NAME', 'dqrnjeixk')
CLOUD_KEY    = os.environ.get('CLOUDINARY_API_KEY', '296361868522199')
CLOUD_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '6umCOdfNRvCqfJ07ecJy0tnW5Y8')

def upload_to_cloudinary(file_bytes, filename):
    try:
        ts = str(int(time.time()))
        sig_str = f"timestamp={ts}{CLOUD_SECRET}"
        sig = hashlib.sha1(sig_str.encode()).hexdigest()
        boundary = 'jibek' + ts
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
            + file_bytes
            + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="timestamp"\r\n\r\n{ts}\r\n'.encode()
            + f'--{boundary}\r\nContent-Disposition: form-data; name="api_key"\r\n\r\n{CLOUD_KEY}\r\n'.encode()
            + f'--{boundary}\r\nContent-Disposition: form-data; name="signature"\r\n\r\n{sig}\r\n'.encode()
            + f'--{boundary}--\r\n'.encode()
        )
        req = urllib.request.Request(
            f'https://api.cloudinary.com/v1_1/{CLOUD_NAME}/image/upload',
            data=body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get('secure_url','')
    except Exception as e:
        print(f'Cloudinary error: {e}')
        return ''

ADMINS = {
    'jibek1': os.environ.get('ADMIN_JIBEK1_PASS'),
    'admin2': os.environ.get('ADMIN_JIBEK2_PASS'),
}

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('CREATE SCHEMA IF NOT EXISTS jibek')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.shoes (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL, brand TEXT, category TEXT,
        size TEXT, price TEXT, old_price TEXT,
        description TEXT, images TEXT DEFAULT '[]',
        created_at TIMESTAMP DEFAULT NOW()
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.users (
        id SERIAL PRIMARY KEY,
        email TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
        name TEXT, created_at TIMESTAMP DEFAULT NOW()
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.orders (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES jibek.users(id) ON DELETE SET NULL,
        items TEXT, total TEXT, address TEXT, phone TEXT,
        status TEXT DEFAULT 'новый',
        created_at TIMESTAMP DEFAULT NOW()
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.order_items (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES jibek.orders(id) ON DELETE CASCADE,
        shoe_id INTEGER REFERENCES jibek.shoes(id) ON DELETE SET NULL,
        size TEXT, quantity INTEGER, price TEXT
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.order_history (
        id SERIAL PRIMARY KEY,
        order_id INTEGER REFERENCES jibek.orders(id) ON DELETE CASCADE,
        status TEXT,
        changed_at TIMESTAMP DEFAULT NOW()
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.cart (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES jibek.users(id) ON DELETE CASCADE,
        shoe_id INTEGER REFERENCES jibek.shoes(id) ON DELETE CASCADE,
        quantity INTEGER DEFAULT 1
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.favorites (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES jibek.users(id) ON DELETE CASCADE,
        shoe_id INTEGER REFERENCES jibek.shoes(id) ON DELETE CASCADE,
        UNIQUE(user_id, shoe_id)
    )''')
    cur.execute('''CREATE TABLE IF NOT EXISTS jibek.reviews (
        id SERIAL PRIMARY KEY,
        shoe_id INTEGER REFERENCES jibek.shoes(id) ON DELETE CASCADE,
        user_id INTEGER REFERENCES jibek.users(id) ON DELETE CASCADE,
        user_name TEXT, text TEXT, rating INTEGER,
        created_at TIMESTAMP DEFAULT NOW()
    )''')
    conn.commit()
    cur.close()
    conn.close()

def is_admin(): return session.get('admin') in ADMINS

def current_user():
    uid = session.get('user_id')
    if not uid: return None
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.users WHERE id=%s',(uid,))
    user = cur.fetchone()
    cur.close(); conn.close()
    return user

def cart_count():
    uid = session.get('user_id')
    if not uid: return 0
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT SUM(quantity) FROM jibek.cart WHERE user_id=%s',(uid,))
    r = cur.fetchone()
    cur.close(); conn.close()
    return r['sum'] or 0

def fav_count():
    uid = session.get('user_id')
    if not uid: return 0
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM jibek.favorites WHERE user_id=%s',(uid,))
    r = cur.fetchone()
    cur.close(); conn.close()
    return r['count'] or 0

def get_images(shoe):
    try:
        imgs = json.loads(shoe['images'] or '[]')
        return imgs if imgs else []
    except: return []

def img_url(img):
    if img.startswith('http'): return img
    return '/static/uploads/' + img

app.jinja_env.globals.update(
    cart_count=cart_count, fav_count=fav_count,
    is_admin=is_admin, current_user=current_user,
    get_images=get_images, img_url=img_url
)

def save_photos(req, old_images='[]'):
    images = json.loads(old_images or '[]')
    for pf in req.files.getlist('photos'):
        if pf and pf.filename:
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
            url = upload_to_cloudinary(pf.read(), fname)
            if url: images.append(url)
    for i, pb in enumerate(req.form.getlist('photo_b64')):
        if pb and ',' in pb:
            _, data = pb.split(',',1)
            fname = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}.jpg"
            url = upload_to_cloudinary(base64.b64decode(data), fname)
            if url: images.append(url)
    return json.dumps(images)

# ── КАТАЛОГ ──────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    cat        = request.args.get('category','')
    q          = request.args.get('search','')
    brand      = request.args.get('brand','')
    size       = request.args.get('size','')
    price_from = request.args.get('price_from','')
    price_to   = request.args.get('price_to','')
    sort       = request.args.get('sort','newest')

    conn = get_db(); cur = conn.cursor()
    sql = 'SELECT * FROM jibek.shoes WHERE 1=1'
    p = []
    if cat:        sql += ' AND category=%s'; p.append(cat)
    if q:          sql += ' AND (name ILIKE %s OR brand ILIKE %s)'; p += [f'%{q}%']*2
    if brand:      sql += ' AND brand=%s'; p.append(brand)
    if size:       sql += ' AND size ILIKE %s'; p.append(f'%{size}%')
    if price_from: sql += ' AND CAST(price AS INTEGER) >= %s'; p.append(int(price_from))
    if price_to:   sql += ' AND CAST(price AS INTEGER) <= %s'; p.append(int(price_to))

    if sort == 'price_asc':   sql += ' ORDER BY CAST(NULLIF(price,\'\') AS INTEGER) ASC NULLS LAST'
    elif sort == 'price_desc':sql += ' ORDER BY CAST(NULLIF(price,\'\') AS INTEGER) DESC NULLS LAST'
    elif sort == 'discount':  sql += ' ORDER BY old_price DESC NULLS LAST'
    else: sql += ' ORDER BY id DESC'

    cur.execute(sql, p)
    shoes = cur.fetchall()
    cur.execute('SELECT DISTINCT category FROM jibek.shoes WHERE category IS NOT NULL AND category!=\'\'')
    cats = cur.fetchall()
    cur.execute('SELECT DISTINCT brand FROM jibek.shoes WHERE brand IS NOT NULL AND brand!=\'\'')
    brands = cur.fetchall()
    cur.execute('SELECT DISTINCT size FROM jibek.shoes WHERE size IS NOT NULL AND size!=\'\'')
    sizes = cur.fetchall()
    uid = session.get('user_id')
    favs = set()
    if uid:
        cur.execute('SELECT shoe_id FROM jibek.favorites WHERE user_id=%s',(uid,))
        favs = {r['shoe_id'] for r in cur.fetchall()}
    cur.close(); conn.close()

    has_filters = any([brand, size, price_from, price_to, sort != 'newest'])
    return render_template('index.html', shoes=shoes, cats=cats, brands=brands, sizes=sizes,
                           sel_cat=cat, search=q, brand=brand, size=size,
                           price_from=price_from, price_to=price_to,
                           sort=sort, favs=favs, has_filters=has_filters)

@app.route('/shoe/<int:sid>')
def shoe_detail(sid):
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.shoes WHERE id=%s',(sid,))
    shoe = cur.fetchone()
    uid = session.get('user_id')
    is_fav = False
    if uid:
        cur.execute('SELECT 1 FROM jibek.favorites WHERE user_id=%s AND shoe_id=%s',(uid,sid))
        is_fav = bool(cur.fetchone())
    cur.execute('''SELECT r.*,u.name as user_name FROM jibek.reviews r
        LEFT JOIN jibek.users u ON r.user_id=u.id WHERE r.shoe_id=%s ORDER BY r.id DESC''',(sid,))
    reviews = cur.fetchall()
    cur.execute('SELECT AVG(rating) as a FROM jibek.reviews WHERE shoe_id=%s',(sid,))
    avg = cur.fetchone()
    cur.close(); conn.close()
    if not shoe: return redirect('/')
    return render_template('detail.html', shoe=shoe, is_fav=is_fav,
                           reviews=reviews, avg_rating=avg['a'])

# ── ИЗБРАННОЕ ────────────────────────────────────────────────────────────────
@app.route('/favorites')
def favorites():
    uid = session.get('user_id')
    if not uid: return redirect(url_for('user_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('''SELECT s.* FROM jibek.shoes s JOIN jibek.favorites f ON s.id=f.shoe_id
        WHERE f.user_id=%s ORDER BY f.id DESC''',(uid,))
    shoes = cur.fetchall()
    favs = {s['id'] for s in shoes}
    cur.close(); conn.close()
    return render_template('favorites.html', shoes=shoes, favs=favs)

@app.route('/favorite/toggle/<int:sid>', methods=['POST'])
def fav_toggle(sid):
    uid = session.get('user_id')
    if not uid: return jsonify({'error':'login'}), 401
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT 1 FROM jibek.favorites WHERE user_id=%s AND shoe_id=%s',(uid,sid))
    if cur.fetchone():
        cur.execute('DELETE FROM jibek.favorites WHERE user_id=%s AND shoe_id=%s',(uid,sid))
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status':'removed'})
    else:
        cur.execute('INSERT INTO jibek.favorites (user_id,shoe_id) VALUES (%s,%s)',(uid,sid))
        conn.commit(); cur.close(); conn.close()
        return jsonify({'status':'added'})

# ── АВТОРИЗАЦИЯ ───────────────────────────────────────────────────────────────
@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        pw    = request.form.get('password','')
        name  = request.form.get('name','').strip()
        if len(pw) < 6:
            flash('Пароль минимум 6 символов','error')
            return render_template('register.html')
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute('INSERT INTO jibek.users (email,password,name) VALUES (%s,%s,%s)',
                        (email, generate_password_hash(pw), name))
            conn.commit(); cur.close(); conn.close()
            flash('Аккаунт создан!','success')
            return redirect(url_for('user_login'))
        except psycopg2.errors.UniqueViolation:
            flash('Эта почта уже зарегистрирована','error')
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def user_login():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        pw    = request.form.get('password','')
        conn = get_db(); cur = conn.cursor()
        cur.execute('SELECT * FROM jibek.users WHERE email=%s',(email,))
        user = cur.fetchone()
        cur.close(); conn.close()
        if user and check_password_hash(user['password'], pw):
            session.permanent = True
            session['user_id'] = user['id']
            flash(f'Добро пожаловать{", "+user["name"] if user["name"] else ""}!','success')
            return redirect(url_for('index'))
        flash('Неверная почта или пароль','error')
    return render_template('user_login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# ── КОРЗИНА ───────────────────────────────────────────────────────────────────
@app.route('/cart')
def cart():
    uid = session.get('user_id')
    if not uid: return redirect(url_for('user_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('''SELECT c.id as cid, c.quantity, s.*
        FROM jibek.cart c JOIN jibek.shoes s ON c.shoe_id=s.id WHERE c.user_id=%s''',(uid,))
    items = cur.fetchall()
    cur.close(); conn.close()
    total = sum(int(i['price'] or 0) * i['quantity'] for i in items)
    return render_template('cart.html', items=items, total=total)

@app.route('/cart/add/<int:sid>', methods=['POST'])
def cart_add(sid):
    uid = session.get('user_id')
    if not uid:
        flash('Войди чтобы добавить в корзину','error')
        return redirect(url_for('user_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.cart WHERE user_id=%s AND shoe_id=%s',(uid,sid))
    if cur.fetchone():
        cur.execute('UPDATE jibek.cart SET quantity=quantity+1 WHERE user_id=%s AND shoe_id=%s',(uid,sid))
    else:
        cur.execute('INSERT INTO jibek.cart (user_id,shoe_id) VALUES (%s,%s)',(uid,sid))
    conn.commit(); cur.close(); conn.close()
    flash('Добавлено в корзину ✅','success')
    return redirect(request.referrer or '/')

@app.route('/cart/remove/<int:cid>', methods=['POST'])
def cart_remove(cid):
    uid = session.get('user_id')
    if uid:
        conn = get_db(); cur = conn.cursor()
        cur.execute('DELETE FROM jibek.cart WHERE id=%s AND user_id=%s',(cid,uid))
        conn.commit(); cur.close(); conn.close()
    return redirect(url_for('cart'))

@app.route('/cart/update/<int:cid>', methods=['POST'])
def cart_update(cid):
    uid = session.get('user_id')
    qty = int(request.form.get('quantity',1))
    if uid:
        conn = get_db(); cur = conn.cursor()
        if qty <= 0:
            cur.execute('DELETE FROM jibek.cart WHERE id=%s AND user_id=%s',(cid,uid))
        else:
            cur.execute('UPDATE jibek.cart SET quantity=%s WHERE id=%s AND user_id=%s',(qty,cid,uid))
        conn.commit(); cur.close(); conn.close()
    return redirect(url_for('cart'))

# ── ЗАКАЗЫ ────────────────────────────────────────────────────────────────────
@app.route('/checkout', methods=['GET','POST'])
def checkout():
    uid = session.get('user_id')
    if not uid: return redirect(url_for('user_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('''SELECT c.quantity, s.name, s.price, s.id
        FROM jibek.cart c JOIN jibek.shoes s ON c.shoe_id=s.id WHERE c.user_id=%s''',(uid,))
    items = cur.fetchall()
    cur.execute('SELECT * FROM jibek.users WHERE id=%s',(uid,))
    user = cur.fetchone()
    if not items:
        flash('Корзина пуста','error')
        cur.close(); conn.close()
        return redirect(url_for('cart'))
    total = sum(int(i['price'] or 0) * i['quantity'] for i in items)
    if request.method == 'POST':
        phone   = request.form.get('phone','').strip()
        city    = request.form.get('city','').strip()
        comment = request.form.get('comment','').strip()
        items_text = '; '.join(f"{i['name']} x{i['quantity']} ({int(i['price'] or 0)*i['quantity']} ₸)" for i in items)
        address = f"Город: {city}. Комментарий: {comment}" if comment else city
        cur.execute('''INSERT INTO jibek.orders (user_id,items,total,address,phone)
                      VALUES (%s,%s,%s,%s,%s)''',
                   (uid, items_text, str(total), address, phone))
        cur.execute('DELETE FROM jibek.cart WHERE user_id=%s',(uid,))
        conn.commit(); cur.close(); conn.close()
        flash('Заказ оформлен! 🎉','success')
        return redirect(url_for('my_orders'))
    cur.close(); conn.close()
    return render_template('checkout.html', items=items, total=total, user=user)

@app.route('/my-orders')
def my_orders():
    uid = session.get('user_id')
    if not uid: return redirect(url_for('user_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.orders WHERE user_id=%s ORDER BY id DESC',(uid,))
    orders = cur.fetchall()
    history = {}
    for o in orders:
        cur.execute('SELECT * FROM jibek.order_history WHERE order_id=%s ORDER BY id ASC',(o['id'],))
        history[o['id']] = cur.fetchall()
    cur.close(); conn.close()
    return render_template('my_orders.html', orders=orders, history=history)

@app.route('/order/delete/<int:oid>', methods=['POST'])
def order_delete(oid):
    uid = session.get('user_id')
    if not uid: return redirect(url_for('user_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('DELETE FROM jibek.orders WHERE id=%s AND user_id=%s',(oid,uid))
    cur.execute('DELETE FROM jibek.order_history WHERE order_id=%s',(oid,))
    conn.commit(); cur.close(); conn.close()
    flash('Заказ удалён','success')
    return redirect(url_for('my_orders'))

# ── ADMIN ─────────────────────────────────────────────────────────────────────
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','')
        if ADMINS.get(u) and ADMINS.get(u) == p:
            session['admin'] = u
            return redirect(url_for('admin'))
        flash('Неверный логин или пароль','error')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/')

@app.route('/admin')
def admin():
    if not is_admin(): return redirect(url_for('admin_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.shoes ORDER BY id DESC')
    shoes = cur.fetchall()
    cur.execute('SELECT o.*, u.email as user_email, u.name as user_name FROM jibek.orders o LEFT JOIN jibek.users u ON o.user_id=u.id ORDER BY o.id DESC')
    orders = cur.fetchall()
    cur.execute('SELECT COUNT(*) FROM jibek.users')
    users = cur.fetchone()
    cur.execute("SELECT SUM(CAST(NULLIF(total,'') AS INTEGER)) as s FROM jibek.orders WHERE status='выполнен'")
    revenue = cur.fetchone()
    cur.execute("SELECT COUNT(*) as c FROM jibek.orders WHERE status='новый'")
    new_cnt = cur.fetchone()
    cur.execute('''SELECT r.*,u.name as user_name,s.name as shoe_name FROM jibek.reviews r
        LEFT JOIN jibek.users u ON r.user_id=u.id
        LEFT JOIN jibek.shoes s ON r.shoe_id=s.id ORDER BY r.id DESC''')
    reviews = cur.fetchall()
    history = {}
    for o in orders:
        cur.execute('SELECT * FROM jibek.order_history WHERE order_id=%s ORDER BY id ASC',(o['id'],))
        history[o['id']] = cur.fetchall()
    cur.close(); conn.close()
    return render_template('admin.html', shoes=shoes, orders=orders, users=users,
                           revenue=revenue, new_cnt=new_cnt, reviews=reviews, history=history)

@app.route('/admin/order/<int:oid>/status', methods=['POST'])
def order_status(oid):
    if not is_admin(): return redirect(url_for('admin_login'))
    status = request.form.get('status','')
    conn = get_db(); cur = conn.cursor()
    cur.execute('UPDATE jibek.orders SET status=%s WHERE id=%s',(status,oid))
    cur.execute('INSERT INTO jibek.order_history (order_id,status) VALUES (%s,%s)',(oid,status))
    conn.commit(); cur.close(); conn.close()
    flash('Статус обновлён','success')
    return redirect(url_for('admin'))

@app.route('/admin/order/delete/<int:oid>', methods=['POST'])
def order_delete_admin(oid):
    if not is_admin(): return redirect(url_for('admin_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('DELETE FROM jibek.orders WHERE id=%s',(oid,))
    cur.execute('DELETE FROM jibek.order_history WHERE order_id=%s',(oid,))
    conn.commit(); cur.close(); conn.close()
    flash('Заказ удалён','success')
    return redirect(url_for('admin'))

@app.route('/admin/add', methods=['GET','POST'])
def add_shoe():
    if not is_admin(): return redirect(url_for('admin_login'))
    if request.method == 'POST':
        imgs = save_photos(request)
        conn = get_db(); cur = conn.cursor()
        cur.execute('INSERT INTO jibek.shoes (name,brand,category,size,price,old_price,description,images) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
            (request.form.get('name','').strip(), request.form.get('brand','').strip(),
             request.form.get('category','').strip(), request.form.get('size','').strip(),
             request.form.get('price','').strip(), request.form.get('old_price','').strip(),
             request.form.get('description','').strip(), imgs))
        conn.commit(); cur.close(); conn.close()
        flash('Товар добавлен ✅','success')
        return redirect(url_for('admin'))
    return render_template('shoe_form.html', shoe=None, action='/admin/add', title='Добавить товар')

@app.route('/admin/edit/<int:sid>', methods=['GET','POST'])
def edit_shoe(sid):
    if not is_admin(): return redirect(url_for('admin_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.shoes WHERE id=%s',(sid,))
    shoe = cur.fetchone()
    cur.close(); conn.close()
    if not shoe: return redirect(url_for('admin'))
    if request.method == 'POST':
        imgs = save_photos(request, shoe['images'])
        remove = request.form.getlist('remove_photo')
        if remove:
            current = json.loads(imgs)
            for r in remove:
                if r in current:
                    current.remove(r)
            imgs = json.dumps(current)
        conn = get_db(); cur = conn.cursor()
        cur.execute('UPDATE jibek.shoes SET name=%s,brand=%s,category=%s,size=%s,price=%s,old_price=%s,description=%s,images=%s WHERE id=%s',
            (request.form.get('name','').strip(), request.form.get('brand','').strip(),
             request.form.get('category','').strip(), request.form.get('size','').strip(),
             request.form.get('price','').strip(), request.form.get('old_price','').strip(),
             request.form.get('description','').strip(), imgs, sid))
        conn.commit(); cur.close(); conn.close()
        flash('Товар обновлён ✅','success')
        return redirect(url_for('admin'))
    return render_template('shoe_form.html', shoe=shoe, action=f'/admin/edit/{sid}', title='Редактировать')

@app.route('/admin/delete/<int:sid>', methods=['POST'])
def delete_shoe(sid):
    if not is_admin(): return redirect(url_for('admin_login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT images FROM jibek.shoes WHERE id=%s',(sid,))
    shoe = cur.fetchone()
    cur.execute('DELETE FROM jibek.shoes WHERE id=%s',(sid,))
    conn.commit(); cur.close(); conn.close()
    flash('Товар удалён','success')
    return redirect(url_for('admin'))

# ── ОТЗЫВЫ ────────────────────────────────────────────────────────────────────
@app.route('/reviews')
def reviews():
    conn = get_db(); cur = conn.cursor()
    cur.execute('''SELECT r.*,u.name as user_name,s.name as shoe_name
        FROM jibek.reviews r LEFT JOIN jibek.users u ON r.user_id=u.id
        LEFT JOIN jibek.shoes s ON r.shoe_id=s.id ORDER BY r.id DESC''')
    reviews = cur.fetchall()
    cur.close(); conn.close()
    return render_template('reviews.html', reviews=reviews)

@app.route('/review/add/<int:sid>', methods=['POST'])
def review_add(sid):
    uid = session.get('user_id')
    if not uid: return redirect(url_for('user_login'))
    rating = int(request.form.get('rating', 5))
    text   = request.form.get('text','').strip()
    if not text:
        flash('Напиши текст отзыва','error')
        return redirect(url_for('shoe_detail', sid=sid))
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT name FROM jibek.users WHERE id=%s',(uid,))
    user = cur.fetchone()
    cur.execute('INSERT INTO jibek.reviews (user_id,user_name,shoe_id,rating,text) VALUES (%s,%s,%s,%s,%s)',
               (uid, user['name'] if user else '', sid, rating, text))
    conn.commit(); cur.close(); conn.close()
    flash('Отзыв добавлен! ⭐','success')
    return redirect(url_for('shoe_detail', sid=sid))

@app.route('/review/delete/<int:rid>', methods=['POST'])
def review_delete(rid):
    uid = session.get('user_id')
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT * FROM jibek.reviews WHERE id=%s',(rid,))
    review = cur.fetchone()
    if review and (is_admin() or (uid and review['user_id'] == uid)):
        cur.execute('DELETE FROM jibek.reviews WHERE id=%s',(rid,))
        conn.commit()
        flash('Отзыв удалён','success')
    cur.close(); conn.close()
    return redirect(request.referrer or '/reviews')

# ── ПОИСК ПО ФОТО ────────────────────────────────────────────────────────────
@app.route('/search-by-photo', methods=['POST'])
def search_by_photo():
    photo_b64 = request.form.get('photo_b64','')
    if not photo_b64 or ',' not in photo_b64:
        return jsonify({'error': 'Нет фото'}), 400
    _, img_data = photo_b64.split(',', 1)
    conn = get_db(); cur = conn.cursor()
    cur.execute('SELECT id,name,brand,category,description FROM jibek.shoes')
    shoes = cur.fetchall()
    cur.close(); conn.close()
    catalog = '\n'.join(f"ID:{s['id']} | {s['brand'] or ''} {s['name']} | {s['category'] or ''} | {s['description'] or ''}" for s in shoes)
    prompt = f"""Посмотри на это фото обуви и найди максимально похожие товары из каталога.
Каталог:
{catalog}

Верни ТОЛЬКО JSON без markdown: {{"results": [ID1, ID2, ID3], "description": "краткое описание что на фото"}}
Если ничего похожего нет — верни пустой список results."""

    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_data}},
            {"type": "text", "text": prompt}
        ]}]
    }).encode()

    try:
        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=body,
            headers={
                'Content-Type':'application/json',
                'anthropic-version':'2023-06-01',
                'x-api-key': os.environ.get('ANTHROPIC_API_KEY','')
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        text = data['content'][0]['text'].strip().replace('```json','').replace('```','').strip()
        result = json.loads(text)
        ids = result.get('results', [])
        desc = result.get('description', '')
        conn = get_db(); cur = conn.cursor()
        found = []
        for sid in ids[:6]:
            cur.execute('SELECT * FROM jibek.shoes WHERE id=%s',(sid,))
            s = cur.fetchone()
            if s:
                imgs = get_images(s)
                found.append({
                    'id': s['id'], 'name': s['name'], 'brand': s['brand'] or '',
                    'price': s['price'] or '', 'image': imgs[0] if imgs else ''
                })
        cur.close(); conn.close()
        return jsonify({'results': found, 'description': desc})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

try:
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
except OSError:
    pass

try:
    init_db()
except Exception as e:
    print(f"Database initialization failed: {e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)