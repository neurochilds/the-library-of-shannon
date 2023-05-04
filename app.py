from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import json
import random
import asyncio


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
    '''
    Creates websocket with client, recieves form data and passes data as an argument to construct_book()
    '''
    await websocket.accept()
    data = await websocket.receive_json()
    book = data["book"]
    words = data["words"]
    order = data["order"]
    await construct_book(websocket, book=book, words=words, order=order)

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
        'finished_constructing': False
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
    '''
    This function constructs the text by calling other functions that construct a single sentence and itself structures the text into paragraphs.
    The sentence constructing function chosen depends on the order of approx.
    This function never inserts a new para until at least 4 sentences have been produced. 
    When there are between 5-20 sentences, there is a 1/16 chance that a new para will be inserted after each new sentence.
    It will always inserts a new para after 20 sentences have been produced. 
    '''
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

    state['finished_constructing'] = True

    return await send_text_to_client(websocket, state=state, params=params) 


async def construct_random_text(websocket: WebSocket, state, params, dictionary):
    '''
    This function constructs the text by randomly selecting words from a dictionary, where each word has equal probability of being selected.
    This leads to a zero-order approximation to natural English.
    There is a 1/15 chance that each word selected will end the sentence. Paragraphs will be produced the same way as construct_text() above.
    '''
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

        await send_text_to_client(websocket, state=state, params=params) 
    
    state['finished_constructing'] = True

    if await is_stop_requested(websocket):
        return
    
    return await send_text_to_client(websocket, state=state, params=params) 
    

async def construct_first_order_sentence(websocket: WebSocket, params, state):
    '''
    This function randomly selects words from a source text file. 
    This leads to a first-order approximation to natural English, as the probability of a word being included in the constructed text depends on it's frequency of occurence in natural English (the source text being sampled).
    '''
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
    '''
    This function randomly selects (order - 1) words from the source text until these words match the last (order - 1) words in the constructed sentence.
    The word adjacent to these words in the source text is then chosen as the next word in the constructed sentence. 
    This leads to an (order)-approximation to natural English, as the probability of a word being selected as the next word in the constructed text depends on the frequency with which it follows the last (order - 1) words in natural English (the source text being sampled). 
    '''
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
                
                await add_word_ending_and_noise(websocket, new_word, state=state, params=params)


async def add_word_ending_and_noise(websocket: WebSocket, word, state, params):
    '''
    This function inserts spaces after each word and ensures the generated text always ends in a period. 
    '''
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

    return await send_text_to_client(websocket, state=state, params=params) 


async def send_text_to_client(websocket:WebSocket, state, params):
    '''
    This function sends the current sentence, selected book, selected order, and whether or not the text construction is complete to the client via the websocket.
    '''
    if websocket is not None:
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
        'finished_constructing': True
    }
    return 'Reset words'