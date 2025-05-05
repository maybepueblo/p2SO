from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
import random
from collections import defaultdict
import time
import logging
import requests

# Basic configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Game state structures
games = {}
players = {}
player_to_game = {}

# Backup word list (500+ English words)
ENGLISH_WORDS_BACKUP = [
    "ABBEY", "ABOUT", "ACTOR", "ADAPT", "ADOPT", "ADORE", "AFTER", "AGAIN",
    "AGENT", "ALARM", "ALBUM", "ALERT", "ALIKE", "ALIVE", "ALLOW", "ALONE",
    "ALONG", "ALTER", "AMBER", "ANGEL", "ANGER", "ANGRY", "ANNOY", "APPLE",
    "APRIL", "ARGUE", "ARISE", "ARROW", "AUDIO", "AUGUST", "AUNTY", "AVOID",
    "AWARD", "AWARE", "BADGE", "BASIC", "BEACH", "BEGIN", "BEING", "BELOW",
    "BIRTH", "BLACK", "BLAME", "BLIND", "BLOCK", "BLOOD", "BOARD", "BORED",
    "BRAIN", "BRAND", "BREAD", "BREAK", "BRICK", "BRIDE", "BRING", "BROAD",
    "BROWN", "BRUSH", "BUILD", "BUNCH", "CANDY", "CAREFUL", "CHAIN", "CHAIR",
    "CHASE", "CHEAP", "CHECK", "CHEER", "CHEST", "CHIEF", "CHILD", "CHOSE",
    "CLAIM", "CLASS", "CLEAN", "CLEAR", "CLIMB", "CLOCK", "CLOSE", "CLOTH",
    "CLOUD", "COACH", "COAST", "COMFY", "COURT", "COVER", "CRASH", "CRAZY",
    "CRIME", "CROSS", "CROWD", "CRUEL", "DAILY", "DANCE", "DEATH", "DELAY",
    "DEPTH", "DIRTY", "DONOR", "DOUBT", "DOZEN", "DRAFT", "DRAMA", "DREAM",
    "DRESS", "DRINK", "DRIVE", "DUTCH", "EAGER", "EARLY", "EARTH", "EIGHT",
    "ELITE", "EMPTY", "ENEMY", "ENJOY", "ENTER", "EQUAL", "ERROR", "EVENT",
    "EVERY", "EXACT", "EXIST", "EXTRA", "FAITH", "FALSE", "FAULT", "FAVOR",
    "FENCE", "FEVER", "FIGHT", "FINAL", "FIRST", "FIXED", "FLASH", "FLESH",
    "FLOOD", "FLOOR", "FOCUS", "FORCE", "FORTY", "FOUND", "FRAME", "FRESH",
    "FRONT", "FRUIT", "FUNNY", "GIANT", "GLASS", "GLOBE", "GRAND", "GRASS",
    "GREEN", "GROSS", "GROUP", "GROWN", "GUARD", "GUESS", "GUIDE", "HAPPY",
    "HEARD", "HEART", "HEAVY", "HONEY", "HOTEL", "HOUSE", "HUMAN", "HUMOR",
    "IDEAL", "IMAGE", "IMPLY", "INPUT", "IRONY", "JUICE", "KNIFE", "LABEL",
    "LARGE", "LAUGH", "LEARN", "LEAST", "LEAVE", "LEGAL", "LEVEL", "LIGHT",
    "LIMIT", "LOCAL", "LOOSE", "LOVER", "LOWER", "LUCKY", "LUNCH", "MAJOR",
    "MARCH", "MARRY", "MATCH", "MAYBE", "METAL", "MIXED", "MONEY", "MONTH",
    "MOTOR", "MOUNT", "MOUSE", "MOUTH", "MOVIE", "MUSIC", "NAKED", "NASTY",
    "NIGHT", "NOISE", "NORTH", "OCCUR", "OCEAN", "OFFER", "OFTEN", "ORDER",
    "OTHER", "OUGHT", "PAINT", "PANIC", "PAPER", "PARTY", "PASTA", "PAUSE",
    "PEACH", "PHONE", "PIANO", "PILOT", "PITCH", "PLACE", "PLAIN", "PLANE",
    "PLANT", "PLATE", "POINT", "POUND", "POWER", "PRESS", "PRICE", "PRIDE",
    "PRIME", "PRIZE", "PROOF", "PROUD", "PUPIL", "QUIET", "RADIO", "RAISE",
    "RANGE", "RAPID", "REACH", "REACT", "READY", "REFER", "RELAX", "REPLY",
    "RIVER", "ROBOT", "ROUGH", "ROUND", "ROYAL", "RURAL", "SADLY", "SALAD",
    "SCALE", "SCARE", "SCENE", "SCOPE", "SENSE", "SERVE", "SEVEN", "SHADE",
    "SHAKE", "SHAME", "SHAPE", "SHARE", "SHARP", "SHEEP", "SHEET", "SHELF",
    "SHELL", "SHIFT", "SHINE", "SHIRT", "SHOCK", "SHOOT", "SHORT", "SHOWN",
    "SIGHT", "SILLY", "SINCE", "SIXTH", "SLEEP", "SLICE", "SLIDE", "SMALL",
    "SMART", "SMILE", "SMOKE", "SOLID", "SOLVE", "SORRY", "SOUND", "SOUTH",
    "SPACE", "SPARE", "SPEAK", "SPEED", "SPEND", "SPOON", "SPORT", "STAFF"
]

def get_word_from_api():
    """Get a random 5-letter English word from API"""
    try:
        # Try specialized English word API
        response = requests.get('https://random-word-api.herokuapp.com/word?length=5', timeout=3)
        if response.status_code == 200:
            word = response.json()[0].upper()
            if len(word) == 5 and word.isalpha():
                return word

        # Fallback to another API
        response = requests.get('https://random-word-form.herokuapp.com/random/noun?count=1', timeout=3)
        if response.status_code == 200:
            word = response.json()[0].upper()
            if len(word) == 5 and word.isalpha():
                return word

    except Exception as e:
        logger.error(f"API Error: {str(e)}")

    return None

def get_random_word():
    """Get a random word with API priority"""
    # 1. Try API first
    api_word = get_word_from_api()
    if api_word:
        logger.info(f"API Word: {api_word}")
        return api_word

    # 2. Use local backup
    local_word = random.choice(ENGLISH_WORDS_BACKUP)
    logger.warning(f"Using backup word: {local_word}")
    return local_word

def evaluate_attempt(attempt, secret_word):
    """Evaluate attempt against secret word"""
    result = []
    secret = list(secret_word)
    attempt_letters = list(attempt)

    # First pass: correct letters
    for i in range(5):
        if attempt_letters[i] == secret[i]:
            result.append(('correct', attempt_letters[i]))
            secret[i] = None
        else:
            result.append((None, attempt_letters[i]))

    # Second pass: present letters
    for i in range(5):
        if result[i][0] is None and attempt_letters[i] in secret:
            result[i] = ('present', attempt_letters[i])
            secret[secret.index(attempt_letters[i])] = None

    # Third pass: absent letters
    for i in range(5):
        if result[i][0] is None:
            result[i] = ('absent', attempt_letters[i])

    return result

@app.route('/')
def index():
    return render_template('index.html')

# Socket.IO Handlers
@socketio.on('connect')
def handle_connect():
    logger.info(f"Client connected: {request.sid}")
    emit('connection_ack', {'status': 'Connected'})

@socketio.on('disconnect')
def handle_disconnect():
    player_id = request.sid
    if player_id in player_to_game:
        game_id = player_to_game[player_id]
        leave_room(game_id)
        if game_id in games:
            games[game_id]['players'].remove(player_id)
            emit('player_left', {'player_id': player_id}, room=game_id)
            if not games[game_id]['players']:
                del games[game_id]
        del player_to_game[player_id]
        if player_id in players:
            del players[player_id]

@socketio.on('create_game')
def handle_create_game(data):
    try:
        player_name = data.get('player_name', 'Anonymous').strip()
        player_id = request.sid

        if not player_name:
            emit('error', {'message': 'Enter your name'})
            return

        secret_word = get_random_word()

        game_id = str(random.randint(1000, 9999))
        while game_id in games:
            game_id = str(random.randint(1000, 9999))

        games[game_id] = {
            'word': secret_word,
            'creator': player_id,
            'players': [player_id],
            'attempts': defaultdict(list),
            'status': 'waiting',
            'max_attempts': 6,
            'typing_player': None,
            'created_at': time.time()
        }

        players[player_id] = {
            'name': player_name,
            'game_id': game_id
        }
        player_to_game[player_id] = game_id
        join_room(game_id)

        emit('game_created', {
            'game_id': game_id,
            'word_length': 5,
            'is_creator': True,
            'player_name': player_name
        })

        logger.info(f"Game {game_id} created. Word: {secret_word}")

    except Exception as e:
        logger.error(f"Error creating game: {str(e)}")
        emit('error', {'message': 'Error creating game'})

@socketio.on('join_game')
def handle_join_game(data):
    try:
        game_id = data.get('game_id', '').strip()
        player_name = data.get('player_name', 'Anonymous').strip()
        player_id = request.sid

        if not game_id:
            emit('error', {'message': 'Enter game ID'})
            return

        if not player_name:
            emit('error', {'message': 'Enter your name'})
            return

        if game_id not in games:
            emit('error', {'message': 'Game not found'})
            return

        if games[game_id]['status'] != 'waiting':
            emit('error', {'message': 'Game already started'})
            return

        games[game_id]['players'].append(player_id)
        players[player_id] = {
            'name': player_name,
            'game_id': game_id
        }
        player_to_game[player_id] = game_id
        join_room(game_id)

        emit('game_joined', {
            'game_id': game_id,
            'word_length': 5,
            'is_creator': False,
            'player_name': player_name
        })

        emit_game_update(game_id)

    except Exception as e:
        logger.error(f"Join game error: {str(e)}")
        emit('error', {'message': 'Error joining game'})

@socketio.on('start_game')
def handle_start_game():
    try:
        player_id = request.sid
        if player_id not in players:
            return

        game_id = players[player_id]['game_id']

        if game_id in games and games[game_id]['creator'] == player_id:
            games[game_id]['status'] = 'playing'
            emit('game_started', {
                'word_length': 5
            }, room=game_id)
            emit_game_update(game_id)

    except Exception as e:
        logger.error(f"Start game error: {str(e)}")

@socketio.on('submit_attempt')
def handle_submit_attempt(data):
    try:
        player_id = request.sid
        if player_id not in players:
            emit('error', {'message': 'Player not found'})
            return

        game_id = players[player_id]['game_id']

        if game_id not in games:
            emit('error', {'message': 'Game not found'})
            return

        if games[game_id]['status'] != 'playing':
            emit('error', {'message': 'Game not active'})
            return

        attempt = data.get('attempt', '').upper().strip()
        secret_word = games[game_id]['word']

        if len(attempt) != 5:
            emit('error', {'message': 'Word must be 5 letters'})
            return

        if not attempt.isalpha():
            emit('error', {'message': 'Only letters allowed'})
            return

        attempts = games[game_id]['attempts'][player_id]

        if len(attempts) >= 6:
            emit('error', {'message': 'No more attempts left'})
            return

        evaluation = evaluate_attempt(attempt, secret_word)
        attempts.append({
            'word': attempt,
            'evaluation': evaluation
        })

        if all([r[0] == 'correct' for r in evaluation]):
            games[game_id]['status'] = 'finished'
            games[game_id]['winner'] = player_id
            emit('player_won', {
                'player_id': player_id,
                'player_name': players[player_id]['name']
            }, room=game_id)

        check_game_completion(game_id)
        emit_game_update(game_id)

    except Exception as e:
        logger.error(f"Attempt error: {str(e)}")
        emit('error', {'message': 'Error processing attempt'})

@socketio.on('player_typing')
def handle_player_typing():
    player_id = request.sid
    if player_id not in players:
        return

    game_id = players[player_id]['game_id']
    if game_id not in games:
        return

    games[game_id]['typing_player'] = player_id

    emit('typing_update', {
        'typing_player': player_id,
        'player_name': players[player_id]['name']
    }, room=game_id)

@socketio.on('player_stopped_typing')
def handle_player_stopped_typing():
    player_id = request.sid
    if player_id not in players:
        return

    game_id = players[player_id]['game_id']
    if game_id not in games:
        return

    if games[game_id]['typing_player'] == player_id:
        games[game_id]['typing_player'] = None
        emit('typing_update', {
            'typing_player': None
        }, room=game_id)

def check_game_completion(game_id):
    if game_id not in games or games[game_id]['status'] == 'finished':
        return

    word = games[game_id]['word']
    all_finished = True

    for player_id in games[game_id]['players']:
        attempts = games[game_id]['attempts'].get(player_id, [])
        if len(attempts) < 6:
            if not attempts or not all(r[0] == 'correct' for r in attempts[-1]['evaluation']):
                all_finished = False
                break

    if all_finished:
        games[game_id]['status'] = 'finished'
        emit('game_ended', {'word': word}, room=game_id)

def emit_game_update(game_id):
    if game_id not in games:
        return

    game = games[game_id]
    players_info = []

    for player_id in game['players']:
        attempts = game['attempts'].get(player_id, [])
        players_info.append({
            'id': player_id,
            'name': players[player_id]['name'],
            'attempts': attempts,
            'attempts_count': len(attempts),
            'is_creator': player_id == game['creator'],
            'has_won': attempts and all([r[0] == 'correct' for r in attempts[-1]['evaluation']])
        })

    game_state = {
        'word_length': 5,
        'max_attempts': 6,
        'players': players_info,
        'status': game['status'],
        'typing_player': game['typing_player']
    }

    emit('game_update', game_state, room=game_id)

if __name__ == '__main__':
    logger.info("English Wordle server started")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)