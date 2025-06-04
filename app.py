from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import uuid

import json
import random
import asyncio


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="SECRET_KEY") # CHANGE SECRET KEY
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

sessions = {}

TEXT_FILE = 'source_text.txt'
WORD_DICTIONARY = 'words_dictionary.json'


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    '''
    Creates websocket with client, recieves form data and passes data as an argument to construct_book()
    '''
    await websocket.accept()
    session_id = None

    try:
        print('Awaiting data')
        data = await websocket.receive_json()
        book = data["book"]
        words = data["words"]
        order = data["order"]

        session_id = str(uuid.uuid4()) # Generate unique ID
        print('Session started', session_id)
        websocket.session_id = session_id # Assign unique ID to the session
        sessions[websocket.session_id] = { 
            'params': {},
            'state': {}
        } # Add session to global variable
        await websocket.send_json({'session_id': session_id}) # Send to client

        print('Constructing book')
        await construct_book(websocket, book=book, words=words, order=order)
        print('Book constructed!')

    except WebSocketDisconnect:
        print("WebSocket disconnected")

    finally:
        await websocket.close()
        if session_id is not None and session_id in sessions:
            del sessions[session_id]
            print('Deleted ID: ', session_id)
        print("Connection closed")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse('index.html', {"request": request})


@app.get('/info.html', response_class=HTMLResponse)
async def info(request: Request):
    return templates.TemplateResponse('info.html', {"request": request})


async def construct_book(websocket: WebSocket, book, words, order):
    '''
    Initializes state and params global variables, then calls a text constructing function depending on the form data.
    The chosen 'book' is used to seed the random number generator, 'words' determines the number of words construct, and 'order' determines the order of approximation and hence which text construction function to execute.
    '''

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

    sessions[websocket.session_id]['params'] = {
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
    
    sessions[websocket.session_id]['state'] = {
        'stop_requested': False,
        'first_word': True,
        'n_words': 0,
        'words': [0, 0, 0, 0],
        'sentences': 0,
        'sentence_ended': False,
        'ends_in_comma': False,
        'curr_order_of_approx': 1,
        'sentence': '',
        'finished_constructing': False
        }
    
    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']

    params['rand'].seed(book)
    params['noise_rand'].seed(book)

    if params['max_order_of_approx'] == 0:
        await construct_random_text(websocket, dictionary=dictionary)
    elif params['max_order_of_approx'] == 1:
        await construct_text(websocket, is_first_order=True)
    else:
        await construct_text(websocket)

    print('Returning from construct_book function')
    return {'status': 'success'}


async def send_error_message(websocket: WebSocket, message: str):
    if websocket is not None:
        print('Returning from send_error_message function')
        return await websocket.send_json({'message': message})


async def load_text(folder_path):
    with open(f'{folder_path}', 'r', encoding='utf-8') as file:
        return file.read().split()
    

async def construct_text(websocket: WebSocket, is_first_order=False):
    '''
    This function constructs the text by calling other functions that construct a single sentence and itself structures the text into paragraphs.
    The sentence constructing function chosen depends on the order of approx.
    This function never inserts a new para until at least 4 sentences have been produced. 
    When there are between 5-20 sentences, there is a 1/16 chance that a new para will be inserted after each new sentence.
    It will always inserts a new para after 20 sentences have been produced. 
    '''
    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']


    while state['n_words'] < params['max_words'] and not state['stop_requested']:
        if is_first_order:
            await construct_first_order_sentence(websocket)
        else:
            await construct_markov_sentence(websocket)

        if state['stop_requested']:
            print('Returning from construct_text function')
            return

        if state['n_words'] < params['max_words']:
            if state['sentences'] > params['rand'].randint(5, 20):
                state['sentence'] += '<<' # New para. JS code will convert '<' to '<br>'.
                state['sentences'] = 0

    sessions[websocket.session_id]['state']['finished_constructing'] = True
    
    print('Calling send_text_to_client from construct_text function')
    return await send_text_to_client(websocket) 


async def construct_random_text(websocket: WebSocket, dictionary):
    '''
    This function constructs the text by randomly selecting words from a dictionary, where each word has equal probability of being selected.
    This leads to a zero-order approximation to natural English.
    There is a 1/15 chance that each word selected will end the sentence. Paragraphs will be produced the same way as construct_text() above.
    '''
    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']

    while state['n_words'] < params['max_words'] and not state['stop_requested']:
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
                state['sentence'] += '.<<' # New para. JS code will convert '<' to '<br>'.
                state['sentences'] = 0
                state['first_word'] = True
            else:
                state['sentence'] += '. '
                state['sentences'] += 1 
                state['first_word'] = True
        else:
            state['sentence'] += ' '

        if await is_stop_requested(websocket):
            print('Returning from construct_random_text function')
            return
        else:
            await send_text_to_client(websocket) 
    
    state['finished_constructing'] = True

    if await is_stop_requested(websocket):
        print('Returning from construct_random_text function')
        return
    
    return await send_text_to_client(websocket) 
    

async def construct_first_order_sentence(websocket: WebSocket):
    '''
    This function randomly selects words from a source text file. 
    This leads to a first-order approximation to natural English, as the probability of a word being included in the constructed text depends on it's frequency of occurence in natural English (the source text being sampled).
    '''

    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']

    state['sentence_ended'] = False
    state['first_word'] = True
    text = params['text']

    while not state['sentence_ended']:
        if state['n_words'] >= params['max_words']:
            break
        word_found = False
        while not word_found:
            if state['stop_requested']:
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

        await add_word_ending_and_noise(websocket, new_word)
        print('Returning from construct_first_order_sentence function')


async def construct_markov_sentence(websocket: WebSocket):
    '''
    This function randomly selects (order - 1) words from the source text until these words match the last (order - 1) words in the constructed sentence.
    The word adjacent to these words in the source text is then chosen as the next word in the constructed sentence. 
    This leads to an (order)-approximation to natural English, as the probability of a word being selected as the next word in the constructed text depends on the frequency with which it follows the last (order - 1) words in natural English (the source text being sampled). 
    '''

    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']

    text = params['text']
    state['sentence_ended'] = False

    while not state['sentence_ended']:
        if state['n_words'] >= params['max_words']:
            break
        count = 0
        word_found = False
        while not word_found:
            if state['stop_requested']:
                return
            index = params['rand'].randint(0, len(text) - state['curr_order_of_approx'])
            if state['curr_order_of_approx'] > 1:
                new_words = {}
                for i in range(state['curr_order_of_approx'] - 1):
                    new_words[i] = text[index + i]

                    # If order of current new words does not match order of last words in sentence, start again
                    if new_words[i].lower() != state['words'][i]: 
                        break 

                    # If this word is not a proper noun and it's preceding n words match the last n words in the sentence, it will be selected as the new word in the sentence 
                    if new_words.get(state['curr_order_of_approx'] - 2) and text[index + state['curr_order_of_approx'] -1].islower(): 
                        new_word = text[index + state['curr_order_of_approx'] -1]
                        state['words'][state['curr_order_of_approx'] - 1] = new_word
                        word_found = True
                        state['n_words'] += 1
                        state['curr_order_of_approx'] += 1

                count += 1
                if not word_found and count >= params['max_searches']:
                    # If we reached max count at order_of_approx = 2, then we will give up and pick the next word independently of all previous words (i.e. at order = 1). 
                    # If the last word does not end in a comma, we will replace the it's whitespace with a period and start a new sentence.
                    # If ends in comma, we will simply print a space.
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

                    # If we reach max count at order_of_approx > 2, we will stop trying to find the current (n = order_of_approx) words, as it is taking too long, and instead reduce the order by 1 and resume looking at this lower order.
                    else: 
                        state['words'][0], state['words'][1], state['words'][2] = state['words'][1], state['words'][2], 0
                    state['curr_order_of_approx'] -= 1
                    break

            elif state['curr_order_of_approx'] == 1:
                word = text[index]
                if word[-1] in params['sentence_enders']: 
                    new_word = text[index + 1]

                    # If previous word was comma, next word should be lowercase and included in the same sentence
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
                
                await add_word_ending_and_noise(websocket, new_word)
                print('Finished constructing_markov_sentence function')


async def add_word_ending_and_noise(websocket: WebSocket, word):
    '''
    This function inserts spaces after each word and ensures the generated text always ends in a period. 
    '''

    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']

    if await is_stop_requested(websocket):
        print('Returning from add_word_ending_and_noise function')
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

    return await send_text_to_client(websocket) 


async def send_text_to_client(websocket:WebSocket):
    '''
    This function sends the current sentence, selected book, selected order, and whether or not the text construction is complete to the client via the websocket.
    '''

    state = sessions[websocket.session_id]['state']
    params = sessions[websocket.session_id]['params']


    if websocket is not None:
        print('Returning from send_text_to_client function')
        return await websocket.send_json({'constructed_text': state['sentence'], 'book': params['book'], 'order': params['max_order_of_approx'], 'finished_constructing': state['finished_constructing']})


async def add_noise(word, noise, noise_rand):
    '''
    This function has not yet been implemented on the client side.
    '''
    if noise:
        word = ''.join(c if noise_rand.randint(0, 99) > noise else '*' for c in word)
    return word


async def is_stop_requested(websocket: WebSocket):
    '''
    This function waits 0.1 seconds to see if client has sent a request to stop constructing text. If so, closes the socket and updates the global stop_requested variable to stop text construction.
    '''
    # THIS CODE IS MESSY AND SHIT IN HOW IT handles sessions and session_ID...don't need to call it explicitly so much...
    # as in don't need to check if it exists when I've already called it explicitly...and I set stop_requested twice
    print('Checking if stop requested')
    session_id = websocket.session_id
    state = sessions[session_id]['state']

    try:
        data = await asyncio.wait_for(websocket.receive_json(), timeout=.1)
        if "stop" in data and data["stop"]:
            print('Stop was requested')
            state['stop_requested'] = True

            if session_id in sessions:
                sessions[session_id]['state'] = {
                    'stop_requested': True,
                    'first_word': True,
                    'n_words': 0,
                    'words': [0, 0, 0, 0],
                    'sentences': 0,
                    'sentence_ended': False,
                    'ends_in_comma': False,
                    'curr_order_of_approx': 1,
                    'sentence': '',
                    'finished_constructing': True
                }
                print('Stop requested so reset data for ID:', session_id)
            print('Returning from is_stop_requested function')
            return True
    except asyncio.TimeoutError:
        return False


@app.post('/reset_words')
async def reset_words(request: Request):
    session_data = await request.form()
    session_id = session_data.get('session_id')

    if session_id in sessions:
        sessions[session_id]['state'] = {
            'stop_requested': True,
            'first_word': True,
            'n_words': 0,
            'words': [0, 0, 0, 0],
            'sentences': 0,
            'sentence_ended': False,
            'ends_in_comma': False,
            'curr_order_of_approx': 1,
            'sentence': '',
            'finished_constructing': True
        }
        print('Reset words for ID:', session_id)
        return 'Reset words'
    return 'Session not found'