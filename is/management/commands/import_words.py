import os
from django.core.management.base import BaseCommand
from audiomixer.models import Text, Language
from django.conf import settings


class Command(BaseCommand):
    help = 'Import words from file'
    """
    Built on top of opensutitles.com corpora
    """
    FILENAME_PATTERN = '%s_50k.txt'

    def add_arguments(self, parser):
        parser.add_argument('langs', nargs='+', type=str)
        parser.add_argument('minCh', nargs='+', type=int)
        parser.add_argument('minVw', nargs='+', type=int)

    def handle(self, *args, **options):

        for lang in options['langs']:

            lang_obj = Language.objects.get_or_create(code=lang)
            lang_folder = settings.OS_WORDS_PATH / lang

            lang_file = lang_folder / (self.FILENAME_PATTERN % lang)
            if not os.path.exists(lang_file):
                continue
            with open(lang_file) as fp:
                line = fp.readline()

                cnt = 1
                while line:
                    count_char = 0
                    count_vowels = 0
                    word, relevance = line.split(' ')
                    for i in word:
                        i = i.lower()
                        if (i == "a" or i == "e" or i == "i" or i == "o" or i == "u"):
                            count_vowels += 1
                        else:
                            count_char   += 1
                    if count_char >= options.get('minCh')[0] & count_vowels >= options.get('minVw')[0]:
                        word_obj = Word.objects.get_or_create(
                            word=word,
                            relevance=relevance,
                            language=lang_obj[0],
                            count_char=count_char,
                            count_vowels=count_vowels
                        )

                        if not word_obj[1]:
                            word_obj[0].relevance = relevance
                            word_obj[0].save()
                    line = fp.readline()
                    cnt += 1
