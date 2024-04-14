from collections import defaultdict
from random import choice 
import json

text_file = 'source_text.txt'

with open(f'{text_file}', 'r', encoding='utf-8') as file:
    text = file.read().split()


def build_markov_dicts(text):
    markov_dicts = {}
    for order in [2, 3, 4]:
        # Sets list as the default value whenever a key with no value is accessed
        markov_dict = defaultdict(list)

        for i in range(len(text) - order + 1):
            words_same_sentence = True
            prefix = tuple(text[i:i+order-1])
            for word in prefix:
                last_char = word[-1]
                if last_char in ['.', '?', '!']:
                    words_same_sentence = False

            # Only add next word if it's in the same sentence 
            if words_same_sentence:
                prefix = tuple(text[i:i+order-1])
                next_word = text[i+order-1]
                markov_dict[prefix].append(next_word)
        
        markov_dicts[order] = markov_dict

    return markov_dicts

markov_dicts = build_markov_dicts(text)

for order, markov_dict in markov_dicts.items():
    # Json keys must be strings, not tuples
    # Convert tuple keys (A, B) into string keys "A B"
    json_friendly_markov_dict = { " ".join(k): v for k, v in markov_dict.items() }
    with open(f'markov_dict_{order}', 'w') as file:
        json.dump(json_friendly_markov_dict, file)

# To avoid copying word-for-word from text, whenever there is only one possible next word, there's a 75% chance to lower the order of approximation by 1