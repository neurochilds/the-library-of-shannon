from flask import Flask, render_template, request, jsonify
import random
import json

app = Flask(__name__)

global stop_requested 
global params
global state
global selection
global sentence


@app.route("/")
def index():
    return render_template('index.html')


@app.route('/info.html', methods=['GET'])
def info():
    return render_template('info.html')


@app.route('/fetch_generated_text', methods=['GET'])
def fetch_generated_text():
    return jsonify(generated_text=state['sentence'], finished_generating=state['finished_generating'], book=selection['book'], order=selection['order'])


@app.route("/generate_words", methods=["POST"])
def generate_words():
    if request.method == "POST":
        global stop_requested 
        stop_requested = False
        book = request.form.get("book")
        words = request.form.get("words")
        order = request.form.get("order")

        global selection
        selection = {'book':book, 'words':words, 'order':order}

        if not (book and words and order):
            return apology("Please fill in all fields.")
        
        try:
            book = int(book)
            if book < 1:
                return apology("Book must be a positive integer.")
        except:
            return apology("Book must be a positive integer.")
        
        try:
            words = int(words)
            if words < 1:
                return apology("Words must be a positive integer.")
        except:
            return apology("Words must be a positive integer.")
        
        try:
            order = int(order) 
            if order < 0 or order > 4:
                return apology("Order must be an integer between 0-4.")
        except:
            return apology("Order must be an integer between 0-4.")
        
        text_file = 'source_text.txt'
        word_dictionary = 'words_dictionary.json'
        dictionary = []
        with open(word_dictionary, 'r') as file:
            dictionary = list(json.load(file).keys())

        global params
        params = {
            'text': load_text(text_file), 
            'max_searches': 500000, 
            'noise': 0, 
            'rand': random.Random(), 
            'noise_rand': random.Random(),
            'sentence_enders': ['.', '!', '?'],
            'max_order_of_approx': order,
            'max_words': words,
            'type_delay': 0.025
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
            print_random(params=params, state=state, dictionary=dictionary)
        elif params['max_order_of_approx'] == 1:
            print_text(params=params, state=state, selection=selection, is_first_order=True)
        else:
            print_text(params=params, state=state, selection=selection)
    return "", 204


def apology(message):
    return render_template("apology.html", message=message)


def load_text(folder_path):
    with open(f'{folder_path}', 'r', encoding='utf-8') as file:
        return file.read().split()
    

def print_text(params, state, selection, is_first_order=False):
    while state['n_words'] < params['max_words'] and not stop_requested:
        if is_first_order:
            construct_first_order_sentence(params=params, state=state, selection=selection)
        else:
            construct_markov_sentence(params=params, state=state, selection=selection)

        if stop_requested:
            return
        elif state['n_words'] < params['max_words']:
            if state['sentences'] > params['rand'].randint(5, 20):
                state['sentence'] += '<br><br>' # New para
                state['sentences'] = 0
    state['finished_generating'] = True


def print_random(dictionary, params, state):
    while state['n_words'] < params['max_words'] and not stop_requested:
        index = params['rand'].randint(0, len(dictionary) - 1)
        new_word = dictionary[index]
        if state['first_word']:
            new_word = new_word.capitalize()
            state['first_word'] = False
        state['sentence'] += add_noise(new_word, params['noise'], params['noise_rand'])
        state['n_words'] += 1
        
        if state['n_words'] == params['max_words']:
            state['sentence'] += '.'
        elif params['rand'].randint(0, 20) > 19:
            state['sentence'] += '.<br><br>' # New para
            state['first_word'] = True
        else:
            state['sentence'] += ' '


def construct_first_order_sentence(params, state, selection):
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

        add_word_ending_and_noise(new_word, state=state, params=params)


def construct_markov_sentence(state, params, selection):
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
                    # If we reached max count at order_of_approx = 1, then we will give up and pick the next word randomly and independently
                    # of all previous words. If the last word does not end in a comma, we will print a full stop and start a new sentence with word.capitalize().
                    # If ends in comma, we will simply print a space and won't capitalize the next word.
                    # If we reach max count at order_of_approx > 1, we will stop trying to find the current (n = order_of_approx) words
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
                
                add_word_ending_and_noise(new_word, state=state, params=params)


def add_word_ending_and_noise(word, state, params):
    if state['n_words'] == params['max_words']:
        if word[-1] not in params['sentence_enders']:
            if word[-1] == ',':
                state['sentence'] += add_noise(word[:-1], params['noise'], params['noise_rand']) + '.'
            else:
                state['sentence'] += add_noise(word, params['noise'], params['noise_rand']) + '.'
        else:
            state['sentence'] += add_noise(word, params['noise'], params['noise_rand'])
    else:
        state['sentence'] += add_noise(word, params['noise'], params['noise_rand']) + ' '


def add_noise(word, noise, noise_rand):
    if noise:
        word = ''.join(c if noise_rand.randint(0, 99) > noise else '*' for c in word)
    return word


@app.route('/stop_generating_words', methods=['GET'])
def stop_generating_words():
    global stop_requested
    stop_requested = True
    state['finished_generating'] = True
    return 'Stopped generating words'


@app.route('/reset_words', methods=['POST'])
def reset_words():
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