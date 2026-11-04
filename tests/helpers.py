class TestDictionaries:
    words = {
        'en': {'hello', 'world', 'test', 'cat', "don't", 'english'},
        'uk': {'привіт', 'світ', 'україна', 'тест', 'сфе', 'ґанок', "п'ять", 'жук'},
    }

    def check(self, word, language):
        return word.lower() in self.words[language]
