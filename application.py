import os # Route and file manipulation
from sql import SQL # CS50's SQL class in a detatched document
from flask import Flask, redirect, render_template, request, session, json, abort, send_from_directory, url_for # Flask basics
from flask_session import Session # For session, to stay logged in for more than 0ms
from tempfile import mkdtemp # Create temporary folder on user's computer for cookies
from werkzeug.security import generate_password_hash, check_password_hash # Password hasing and checking
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError, RequestEntityTooLarge # Handle exceptions, such as 404 and 500
from datetime import datetime # Get current time with datetime.now()
from uuid import uuid4 # For unique IDs
from functools import wraps # For @login_required decorator
from werkzeug.utils import secure_filename # Make sure files aren't malicious
from http import HTTPStatus # Allow the fun feature of /status/<status>

genHash=lambda p:generate_password_hash(p,method='pbkdf2:sha256',salt_length=14) # Generate a hash of length 100 from a given password

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
@app.after_request
def after_request(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Expires'] = 0
    response.headers['Pragma'] = 'no-cache'
    return response
app.config['SESSION_FILE_DIR'] = mkdtemp()
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0 # Cache for how long
app.config['MAX_CONTENT_LENGTH'] = 20 * 1000 * 1000 # Max file upload size: 20MB
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads') # Set default upload folder
Session(app) # Initialize session
db = SQL('sqlite:///storage.db') # db.execute() will run SQL commands on db, a database

# If this decorator is on a route and the user is not logged in, they will be redirected
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('id') is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function

@app.errorhandler(Exception)
def err(error):
    #return render_template('error.html', eCode = error.code, error = str(error).split(':')[0])
    return render_template('error.html', eCode = 500, error = '500 Internal Server Error')


@app.route('/')
def homepage():
    return render_template('index.html')


@app.route('/historytest')
def historytest():
    return render_template('historytesting.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        errors = []
        # If they somhow submitted invalid data with JS checking then they tried to be malicious
        if len(request.form['uname']) > 32 or len(request.form['email']) > 200 or len(request.form['name']) > 50:
            errors += 'malicious'
            return errors
        # If the referral code is invalid
        if len(request.form['refer'])!=36 and len(db.execute('SELECT*FROM users WHERE uname=?AND hash=?',request.form['refer'].split('#')[0],request.form['refer'].split('#')[1]))!=1:
            errors += 'iR'
        # If chosen hash is invalid
        if ((len(request.form['hash']) % 2 != 0) or (len(request.form['hash']) < 2) or (len(request.form['hash']) > 8)):
            errors += 'iH'
        # If passwords don't match
        if request.form['pass1'] != request.form['pass2']:
            errors += 'pNM'
        # Check if username and hash are taken
        if db.execute('SELECT username FROM users WHERE uname = ? AND hash = ?', request.form['uname'], request.form['hash']):
            errors += 'uT'
        # If all required fields aren't full
        if len(request.form) != 7:
            errors += 'aFR'
        if errors:
            return errors
        referrer=request.form['refer']if len(db.execute('SELECT*FROM users WHERE id4=?',request.form['refer']))==1 else db.execute('SELECT id FROM users WHERE uname=?AND hash=?',request.form['refer'].split('#')[0],request.form['refer'].split('#')[1])
        # Insert new user into database
        db.execute('INSERT INTO users(id4,name,email,bday,pass,uname,hash,ref,reg)VALUES(?,?,?,?,?,?,?,?,?,?)',\
                    str(uuid4()).encode(),request.form['name'],request.form['email'],request.form['bday'],\
                    generate_password_hash(request.form['pass1'],method='pbkdf2:sha256',salt_length=14),\
                    request.form['uname'],request.form['hash'],referrer,datetime.now())
        # Get returned data from new user
        uD = db.execute('SELECT*FROM users WHERE uname=?',request.form['uname'])
        session['id'],session['uname']=uD[0]['id4'],uD[0]['uname']
        return redirect('/')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # All fields required
        if len(request.form)!=2:
            return{'error':'aFR'}
        uD=db.execute('SELECT*FROM users WHERE uname=?AND hash=?',\
                       request.form['uname'].split('#')[0],request.form['uname'].split('#')[1])
        # Checks if username exists and password is correct
        if len(uD)!=1 or not check_password_hash(uD[0]['pass'],request.form['pass']):
            return{'error':'iD'}
        # Everything checks out
        else:
            session['id'],session['uname']=uD[0]['id4'],uD[0]['uname']
        return redirect('/')
    return render_template('login.html')

@app.route('/dm/<user>')
@login_required
def dm(user):
    if user not in db.execute('SELECT id FROM users'):
        abort(404)
    insert = db.execute('INSERT INTO msgs(rcpt,sndr,msg,time)VALUES(?,?,?,?)',\
                         user,session['id'],request.form['msg'].escape_string(),datetime.now(),str(uuid4()))
    # Use AJAX to submit msg form so return something that can be interpreted
    return{'error':'false'}if insert else{'error':'true'}

@app.route('/pm/<srvr>/<channel>')
@login_required
def pm(srvr,channel):
    if srvr not in db.execute('SELECT srvr FROM srvrs') or channel not in db.execute('SELECT clink FROM channels WHERE srvr=?',srvr):
        abort(404)
    insert = db.execute('INSERT INTO srvrmsgs (user, srvr, clink, msg, time, msgid) VALUES (?, ?, ?, ?)', session['id'], srvr, channel, request.form['msg'], datetime.now(), str(uuid4()))
    return{'error':'false'}if insert else{'error':'true'}

@app.route('/new_server', methods = ['GET','POST'])
def genserver():
    if request.method == 'POST':
        srvrid = str(uuid4())[:13].replace('-','')
        # Create server, #general, and add creator as member
        db.execute('INSERT INTO srvrs (name, srvr, created) VALUES (?, ?, ?);\
                    INSERT INTO channels (srvr, clink, created) VALUES (?, ?, ?);\
                    INSERT INTO members (id, srver, joined, owner, mod) VALUES (?, ?, ?, ?, ?)'\
                    ,request.form['srvrname'],srvrid,datetime.now()\
                    ,srvrid,str(uuid4())[:23].replace('-',''),datetime.now()\
                    ,session['id'],srvrid,datetime.now(),'true','true')
        return 'false'
    return render_template('newserver.html')

@app.route('/new_channel', methods = ['GET', 'POST'])
def genchannel():
    if request.method == 'POST':
        db.execute('INSERT INTO channels (name, srvr, clink, created) VALUES (?, ?, ?, ?)', request.form['name'], request.form['srvr'], str(uuid4())[:23].replace('-',''), datetime.now())
        return redirect('/')
    return '''
    <!doctype html>
    <title>Upload new File</title>
    <h1>Create New Channel</h1>
    <form method=post>
      <input type=text name=name>
      <input type=text name=srvr placeholder='where to?'>
      <input type=submit value=Upload>
    </form>'''


@app.route('/files/<path:filename>')
def send_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'],filename)

@app.route('/server/<srvr>')
@app.route('/server/<srvr>/<channel>', methods = ['GET','POST'])
@login_required
def server(srvr,channel=''):
    if request.method == 'POST':
        return db.execute('SELECT * FROM srvrmsgs WHERE link = ? AND clink = ? AND time < ? ORDER BY time ASC LIMIT 50', srvr, channel, request.form['oldest'])
    if channel == '':
        channels = db.execute('SELECT * FROM channels WHERE srvr=?',srvr)[0]['clink']
        return redirect(f'{request.url}/{channels}')
    return render_template('server.html')

@app.route('/generaldata/<srvr>/<channel>')
def getAllData(srvr,channel):
    data = {'srvrs':[],'srvrname':None,'channels':[],'members':[],'msgs':[]}
    # Get all user's servers
    for s in db.execute('SELECT * FROM srvrs INNER JOIN members ON srvrs.srvr = members.srver WHERE srvr IN (SELECT srver FROM members WHERE user_id = ?) ORDER BY joined DESC', session['id']):
        icon = db.execute('SELECT path FROM files WHERE srvr=?',s['srvr'])[0]['path']
        data['srvrs'].append({'name':s['name'],'srvr':s['srvr'],'created':s['created'],'icon':url_for('send_file',filename=f'srvricons/{icon}')})
    # Get current server's name and channels
    data['srvrname'] = db.execute('SELECT name FROM srvrs WHERE srvr = ?', srvr)[0]['name']
    data['channels'] = db.execute('SELECT name, clink FROM channels WHERE srvr = ?', srvr)
    # Get members in server
    for m in db.execute('SELECT * FROM members INNER JOIN files ON files.user = members.user_id WHERE srver = ?', srvr):
        data['members'].append({'id':m['user_id'],'joined':m['joined'],'owner':m['owner'],'mod':m['mod'],'icon':url_for('send_file',filename=m['user_id']+'/'+m['path'])})
    # Load first 50 messages
    for m in db.execute('SELECT * FROM msgs WHERE channel = ? AND server = ? ORDER BY sent ASC LIMIT 50', channel, srvr):
        data['msgs'].append(m if m else '')
    return data



# DO NOT USE
@app.route('/fillserver/<srvr>/<channel>')
def genmsgs(srvr,channel):
    for i in range(500):
        db.execute('INSERT INTO msgs (msg_id, sndr, channel, server, msg, sent) VALUES (?, ?, ?, ?, ?, ?)', str(uuid4()), session['id'], channel, srvr, i, datetime.now())
    return 'true'


# Needs to be improved... Almost everything is manual
@app.route('/uploads', methods=['GET','POST'])
@login_required
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)
        if file and file.filename.endswith(('.png','.jpg','.jpeg','.gif')) and request.form['to'] == 'srvricons':
            newname = f"{str(uuid4()):1.8}-{secure_filename(file.filename)}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'srvricons', newname))
            # db.execute('INSERT INTO files(path,srvr,uploader,uploaded)VALUES(?,?,?,?)',newname,None,session['id'],datetime.now())
            return redirect('/')
        if file and file.filename.endswith(('.png','.jpg','.jpeg','.gif')):
            if not os.path.isdir(os.path.join(app.config['UPLOAD_FOLDER'], session['id'])):
                os.mkdir(os.path.join(app.config['UPLOAD_FOLDER'], session['id']))
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], session['id'], f"{str(uuid4()):1.8}-{secure_filename(file.filename)}"))
            return redirect('/')
        else:
            return redirect(request.url)
    return '''
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form method=post enctype=multipart/form-data>
      <input type=file name=file>
      <input type=text name=to>
      <input type=submit value=Upload>
    </form>'''



@app.route('/logstar')
def loginstarstalker():
    session['id'] = '20061127-5374-6172-7374-616c6b6572ff'
    return redirect('/')



@app.route('/status/<err>')
def errors(err):
    for i in list(HTTPStatus):
        if i.value == int(err):
            return render_template('error.html', eCode = i.value, error = f"{i.value} {i.phrase}")
    return render_template('error.html', eCode = 999, error = '999 Invalid HTTP Response')


# WIP - DOES NOT WORK
@app.route('/optimize_server_icons')
def optimize_icons():
    print(app.config['UPLOAD_FOLDER'])
    for file in os.path.join(app.config['UPLOAD_FOLDER'],'srvricons'):
        print('I suppose there happens to be files here :P')
        if file.endswith(('jpeg','jpg','png','gif')):
            print(file)
    print([file for file in os.path.join(app.config['UPLOAD_FOLDER'],'srvricons').listdir() if file.endswith(('jpeg','jpg','png','gif'))],end='\n\n')
    images = [file for file in os.path.join(app.config['UPLOAD_FOLDER'],'srvricons').listdir() if file.endswith(('jpeg','jpg','png','gif'))]
    for image in images:
        print(image)
        img = Image.open(os.path.join(app.config['UPLOAD_FOLDER'],'srvricons',image))
        img.thumbnail((600,600))
        img.save(os.path.join(app.config['UPLOAD_FOLDER'],'srvricons',image), optimize=True, quality=40)
    return 'Everything worked'