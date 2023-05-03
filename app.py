from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import random
import time
import asyncio

old_time = time.time()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

state = {}
params = {}
stop_requested = False

TEXT_FILE = 'source_text.txt'
WORD_DICTIONARY = 'words_dictionary.json'

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_json()
    book = data["book"]
    words = data["words"]
    order = data["order"]
    await generate_words(websocket, book=book, words=words, order=order)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse('index.html', {"request": request})


@app.get('/info.html', response_class=HTMLResponse)
async def info(request: Request):
    return templates.TemplateResponse('info.html', {"request": request})


async def generate_words(websocket: WebSocket, book, words, order):
    global stop_requested
    stop_requested = False

    if not (book and words and order):
        return await send_error_message(websocket, "Please fill in all fields.")
    
    try:
        book = int(book)
        words = int(words)
        order = int(order)
        if (book < 1) or (words < 1) or (order < 0) or (order > 4):
            return await send_error_message(websocket, "Book and words must be a positive integer. Order must be an integer between 0-4.")
    except ValueError:
        return await send_error_message(websocket, "Book and words must be a positive integer. Order must be an integer between 0-4.")
    
    dictionary = []
    with open(WORD_DICTIONARY, 'r') as file:
        dictionary = list(json.load(file).keys())

    global params
    params = {
        'text': await load_text(TEXT_FILE), 
        'max_searches': 500000, 
        'noise': 0, 
        'rand': random.Random(), 
        'noise_rand': random.Random(),
        'sentence_enders': ['.', '!', '?'],
        'max_order_of_approx': order,
        'max_words': words,
        'type_delay': 0.025,
        'book': book
        }
    
    global state
    state = {
        'first_word': True,
        'n_words': 0,
        'words': [0, 0, 0, 0],
        'sentences': 0,
        'sentence_ended': False,
        'ends_in_comma': False,
        'curr_order_of_approx': 1,
        'sentence': '',
        'finished_generating': False
        }

    params['rand'].seed(book)
    params['noise_rand'].seed(book)

    if params['max_order_of_approx'] == 0:
        await construct_random_text(websocket, params=params, state=state, dictionary=dictionary)
    elif params['max_order_of_approx'] == 1:
        await construct_text(websocket, params=params, state=state, is_first_order=True)
    else:
        await construct_text(websocket, params=params, state=state)

    return {'status': 'success'}


async def send_error_message(websocket: WebSocket, message: str):
    if websocket is not None:
        return await websocket.send_json({'message': message})


async def load_text(folder_path):
    with open(f'{folder_path}', 'r', encoding='utf-8') as file:
        return file.read().split()
    

async def construct_text(websocket: WebSocket, params, state, is_first_order=False):
    while state['n_words'] < params['max_words'] and not stop_requested:
        if is_first_order:
            await construct_first_order_sentence(websocket, params=params, state=state)
        else:
            await construct_markov_sentence(websocket, params=params, state=state)

        if stop_requested:
            return

        if state['n_words'] < params['max_words']:
            if state['sentences'] > params['rand'].randint(5, 20):
                state['sentence'] += '<<' # New para. JS code will conver '<' to '<br>'
                state['sentences'] = 0

    state['finished_generating'] = True

    return await send_text_to_client(websocket, state=state, params=params) 


async def construct_random_text(websocket: WebSocket, state, params, dictionary):
    while state['n_words'] < params['max_words'] and not stop_requested:
        index = params['rand'].randint(0, len(dictionary) - 1)
        new_word = dictionary[index]
        if state['first_word']:
            new_word = new_word.capitalize()
            state['first_word'] = False
        state['sentence'] += await add_noise(new_word, params['noise'], params['noise_rand'])
        state['n_words'] += 1
        
        if state['n_words'] == params['max_words']:
            state['sentence'] += '.'
        elif params['rand'].randint(0, 15) > 14:
            if state['sentences'] > params['rand'].randint(5, 20):
                state['sentence'] += '.<<' # New para. JS code will conver '<' to '<br>'
                state['sentences'] = 0
                state['first_word'] = True
            else:
                state['sentence'] += '. '
                state['sentences'] += 1 
                state['first_word'] = True
        else:
            state['sentence'] += ' '

        global old_time
        if time.time() - old_time > 1: 
            old_time = time.time()
            await send_text_to_client(websocket, state=state, params=params) 
    
    state['finished_generating'] = True

    if await is_stop_requested(websocket):
        return
    
    return await send_text_to_client(websocket, state=state, params=params) 
    

async def construct_first_order_sentence(websocket: WebSocket, params, state):
    state['sentence_ended'] = False
    state['first_word'] = True
    text = params['text']
    while not state['sentence_ended']:
        if state['n_words'] >= params['max_words']:
            break
        word_found = False
        while not word_found:
            if stop_requested:
                return
            index = params['rand'].randint(0, len(text) - 2)
            new_word = text[index]
            if state['first_word'] or new_word[0].islower(): 
                word_found = True
                state['n_words'] += 1
                        
        if state['first_word']:
            new_word = new_word.capitalize()
            state['first_word'] = False

        if new_word[-1] in params['sentence_enders']:
            state['sentence_ended'] = True
            state['sentences'] += 1

        await add_word_ending_and_noise(websocket, new_word, state=state, params=params)


async def construct_markov_sentence(websocket: WebSocket, state, params):
    text = params['text']
    state['sentence_ended'] = False
    while not state['sentence_ended']:
        if state['n_words'] >= params['max_words']:
            break
        count = 0
        word_found = False
        while not word_found:
            if stop_requested:
                return
            index = params['rand'].randint(0, len(text) - state['curr_order_of_approx'])
            if state['curr_order_of_approx'] > 1:
                new_words = {}
                for i in range(state['curr_order_of_approx'] - 1):
                    new_words[i] = text[index + i]

                    # If order of current new words does not match order of last words in sentence, start again
                    if new_words[i].lower() != state['words'][i]: 
                        break 

                    # If this word is not a proper noun and it's preceding n words match  the last n words in the sentence, it will be selected as the new word in the sentence 
                    if new_words.get(state['curr_order_of_approx'] - 2) and text[index + state['curr_order_of_approx'] -1].islower(): 
                        new_word = text[index + state['curr_order_of_approx'] -1]
                        state['words'][state['curr_order_of_approx'] - 1] = new_word
                        word_found = True
                        state['n_words'] += 1
                        state['curr_order_of_approx'] += 1

                count += 1
                if not word_found and count >= params['max_searches']:
                    # If we reached max count at order_of_approx = 2, then we will give up and pick the next word randomly and independently
                    # of all previous words. If the last word does not end in a comma, we will print a full stop and start a new sentence with word.capitalize().
                    # If ends in comma, we will simply print a space and won't capitalize the next word.
                    # If we reach max count at order_of_approx > 2, we will stop trying to find the current (n = order_of_approx) words
                    # randomly, as it is taking too long, and instead just look for the latest n - 1 words.
                    if state['curr_order_of_approx'] == 2:
                        last_char_of_last_word = state['words'][0][-1]
                        if last_char_of_last_word != ',':
                            if last_char_of_last_word not in params['sentence_enders']:
                                state['sentence'] = state['sentence'][:-1] + '. '
                            state['ends_in_comma'] = False
                            state['sentence_ended'] = True
                            state['sentences'] += 1
                        else:
                            state['ends_in_comma'] = True
                        state['words'][0] = 0
                    else: 
                        state['words'][0], state['words'][1], state['words'][2] = state['words'][1], state['words'][2], 0
                    state['curr_order_of_approx'] -= 1
                    break

            elif state['curr_order_of_approx'] == 1:
                word = text[index]
                if word[-1] in params['sentence_enders']: 
                    new_word = text[index + 1]

                    # If previous word was comma, next word should be lowercase as same sentence
                    if state['ends_in_comma']:
                        new_word = new_word.lower()
                        state['ends_in_comma'] = False
                    else:
                        new_word = new_word.capitalize()
                    state['words'][0] = new_word.lower()
                    word_found = True
                    state['n_words'] += 1
                    state['curr_order_of_approx'] = 2

            if word_found:
                if new_word[-1] in params['sentence_enders']:
                    state['words'][0], state['words'][1], state['words'][2], state['words'][3] = 0, 0, 0, 0
                    state['curr_order_of_approx'] = 1
                    state['sentences'] += 1
                    state['sentence_ended'] = True
                    
                elif state['curr_order_of_approx'] > params['max_order_of_approx']:
                    for i in range(params['max_order_of_approx'] - 1):
                        state['words'][i] = state['words'][i+1]
                    state['words'][params['max_order_of_approx'] -1] = 0
                    state['curr_order_of_approx'] -= 1
                
                await add_word_ending_and_noise(websocket, new_word, state=state, params=params)


async def add_word_ending_and_noise(websocket: WebSocket, word, state, params):
    if await is_stop_requested(websocket):
        return
    
    if state['n_words'] == params['max_words']:
        if word[-1] not in params['sentence_enders']:
            if word[-1] == ',':
                state['sentence'] += await add_noise(word[:-1], params['noise'], params['noise_rand']) + '.'
            else:
                state['sentence'] += await add_noise(word, params['noise'], params['noise_rand']) + '.'
        else:
            state['sentence'] += await add_noise(word, params['noise'], params['noise_rand'])
    else:
        state['sentence'] += await add_noise(word, params['noise'], params['noise_rand']) + ' '

   # If last update was sent more than 1 second ago, send updated text to client via WebSocket
    global old_time
    if time.time() - old_time > 1:
        old_time = time.time()
        return await send_text_to_client(websocket, state=state, params=params) 
    return


async def send_text_to_client(websocket:WebSocket, state, params):
    if websocket is not None:
        return await websocket.send_json({'generated_text': state['sentence'], 'book': params['book'], 'order': params['max_order_of_approx'], 'finished_generating': state['finished_generating']})


async def add_noise(word, noise, noise_rand):
    if noise:
        word = ''.join(c if noise_rand.randint(0, 99) > noise else '*' for c in word)
    return word


async def is_stop_requested(websocket: WebSocket):
    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=.1)
        if "stop" in data and data["stop"]:
            await websocket.close()
            global stop_requested
            stop_requested = True
            return True
    except asyncio.TimeoutError:
        return False


@app.post('/reset_words')
async def reset_words():
    global stop_requested
    stop_requested = True
    global state
    state = {
        'first_word': True,
        'n_words': 0,
        'words': [0, 0, 0, 0],
        'sentences': 0,
        'sentence_ended': False,
        'ends_in_comma': False,
        'curr_order_of_approx': 1,
        'sentence': '',
        'finished_generating': True
    }
    return 'Reset words'