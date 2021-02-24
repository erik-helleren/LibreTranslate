import argparse
import os
from langdetect import detect_langs
from langdetect import DetectorFactory
from pkg_resources import resource_filename
from pathlib import Path
import json
import uuid
import shutil
import ffmpeg
from datetime import datetime, timedelta
from deepspeech import Model, version
from timeit import default_timer as timer
import wave
import numpy as np
import logging
import srt
import glob
import re
import zipfile
from app.language import languages

home_dir=os.getcwd()

SUBTITLE_BREAK_GAP_SECONDS = 0.5
SUBTITLE_MAX_CHARS = 47
SUBTITLE_MAX_DURATION_SECONDS = 7

class LoggerWriter:
    def __init__(self, level):
        # self.level is really like using log.debug(message)
        # at least in my case
        self.level = level

    def write(self, message):
        # if statement reduces the amount of newlines that are
        # printed to the logger
        if message != '\n':
            self.level(message)

    def flush(self):
        # create a flush method so things can be flushed when
        # the system wants to. Not sure if simply 'printing'
        # sys.stderr is the correct way to do it, but it seemed
        # to work properly for me.
        self.level(sys.stderr)

def timeit(method):
    def timed(*args, **kw):
        ts = timer()
        result = method(*args, **kw)
        te = timer()
        if 'log_time' in kw:
            name = kw.get('log_name', method.__name__.upper())
            kw['log_time'][name] = int((te - ts) * 1000)
        else:
            logging.info('%r  %2.2f ms' % (method.__name__, (te - ts) * 1000))
        return result
    return timed

def main():
    parser = argparse.ArgumentParser(description='LibreTranslate - Free and Open Source Translation API')
    parser.add_argument('--target-dir', type=str,
                        help='Directory of the project to translate (%(default)s)', required=True)
    args = parser.parse_args()
    global target_dir
    target_dir=args.target_dir
    os.chdir(target_dir)
    logging.basicConfig(filename="batch.log", level=logging.DEBUG)
    sys.stdout = LoggerWriter(logging.debug)
    sys.stderr = LoggerWriter(logging.warning)

    ## create lock file
    load()
    create_wav_file_if_needed()
    transcribe()
    ## Signal completion/progress

@timeit
def load():
    global language_map
    language_map = {}
    for l in languages:
        language_map[l.code] = l.name
    load_transcribe_model()

@timeit
def load_transcribe_model():
    model_load_start = timer()
    global ds
    ds = Model(os.path.join(home_dir,"models","deepspeech-0.9.3-models.pbmm"))
    ds.enableExternalScorer(os.path.join(home_dir,"models","deepspeech-0.9.3-models.scorer"))
    model_load_end = timer() - model_load_start
    logging.info('Loaded model in {:.3}s.'.format(model_load_end))
    global desired_sample_rate
    desired_sample_rate = ds.sampleRate()
    logging.info('Model optimized for a sample rate of ' +
                 str(desired_sample_rate))
    

@timeit
def create_wav_file_if_needed():
    metadata = loadProjectDetails()
    in_filename = "rawMedia." + metadata['fileEnding']
    if not os.path.exists("audio.wav"):
        create_wav_file(in_filename, "audio.wav")
@timeit
def create_wav_file(in_filename, out_path):
    os.system("ffmpeg -i "+in_filename+" -ac 1 -ar 16000 "+out_path)

@timeit
def loadProjectDetails():
    metadata_path = "metadata.json"
    if not os.path.exists(metadata_path):
        return None
    metadata = json.loads(Path(metadata_path).read_text())
    return metadata

@timeit
def transcribe():
    logging.debug("Loading wav file for project ")
    fin = wave.open("audio.wav", 'rb')
    fs_orig = fin.getframerate()
    if fs_orig != desired_sample_rate:
        logging.error('Original sample rate ({}) is different than {}hz. Resampling might produce erratic speech recognition.'.format(
            fs_orig, desired_sample_rate))
    audio = np.frombuffer(fin.readframes(fin.getnframes()), np.int16)
    audio_length = fin.getnframes() * (1/fs_orig)
    fin.close()
    metadata = performSpeechToText(audio)
    logging.debug(str(metadata))
    words = words_from_candidate_transcript(metadata.transcripts[0])
    logging.debug(str(words))
    srt_chunks = build_srt_chunks(words)
    logging.debug(str(srt_chunks))
    srt_content = create_srt_file(srt_chunks)
    logging.debug("SRT content: "+srt_content)
    translate_subtitles_to_all_languages(srt_content)
    zip_all_subtitles()

@timeit
def zip_all_subtitles():
    zipf = zipfile.ZipFile('subtitles.zip','w', zipfile.ZIP_DEFLATED)
    for file in os.listdir("./"):
        if file.endswith(".srt"):
            zipf.write(file)

@timeit
def translate_subtitles_to_all_languages(srt_content):
    src_lang = next(
        iter([l for l in languages if l.code == "en"]), None)
    for tgt_lang in languages:
        if(tgt_lang.code == src_lang.code):
            continue
        translate_subtitles_to_one_language(
            src_lang, tgt_lang, srt_content)

@timeit
def translate_subtitles_to_one_language(src_lang, tgt_lang, srt_content):
    translator = src_lang.get_translation(tgt_lang)
    translated_content = translator.translate(srt_content)
    write_srt_file(translated_content, tgt_lang.code)

@timeit
def write_srt_file(content, lang_code):
    with open(lang_code+".srt", 'w') as f:
        f.write(content)

@timeit
def performSpeechToText(audio):
    return ds.sttWithMetadata(audio)


@timeit
def words_from_candidate_transcript(metadata):
    word = ""
    word_list = []
    word_start_time = 0
    word_duration = 0
    # Loop through each character
    for i, token in enumerate(metadata.tokens):
        # Append character to word if it's not a space
        if token.text != " ":
            if len(word) == 0:
                # Log the start time of the new word
                word_start_time = token.start_time

            word = word + token.text
            word_duration = token.start_time - word_start_time

        # Word boundary is either a space or the last character in the array
        if token.text == " " or i == len(metadata.tokens) - 1:

            if word_duration < 0:
                word_duration = 0

            each_word = dict()
            each_word["text"] = word
            each_word["start_time"] = round(word_start_time, 4)
            each_word["duration"] = round(word_duration, 4)

            word_list.append(each_word)
            # Reset
            word = ""
            word_start_time = 0

    return word_list

@timeit
def build_srt_chunks(word_list):
    srt_chunks = []
    srt_chunks.append(
        {"start_time": word_list[0]['start_time'], "end_time": word_list[0]['start_time']+word_list[0]['duration'], "text": ""})
    for word in word_list:
        if word is None:
            continue
        last_chunk = srt_chunks[-1]
        too_long_characters = len(
            last_chunk['text'])+len(word['text'])+1 > SUBTITLE_MAX_CHARS
        paused = word['start_time'] - \
            last_chunk['end_time'] > SUBTITLE_BREAK_GAP_SECONDS
        too_long_duration = word['start_time']+word['duration'] - \
            last_chunk['start_time'] > SUBTITLE_MAX_DURATION_SECONDS
        if too_long_characters or paused or too_long_duration:
            srt_chunks.append(
                {"start_time": word['start_time'], "end_time": word['start_time']+word['duration'], "text": word['text']})
        else:
            last_chunk['text'] = last_chunk['text']+" "+word['text']
            last_chunk['end_time'] = word['start_time']+word['duration']
    return srt_chunks

@timeit
def create_srt_file(srt_chunks):
    subtitles = []
    for i, chunk in enumerate(srt_chunks):
        end_time = chunk['end_time']
        if i != len(srt_chunks) - 1:
            end_time = srt_chunks[i+1]['start_time']
        subtitles.append(srt.Subtitle(
            i+1, timedelta(seconds=chunk['start_time']), timedelta(seconds=end_time), chunk['text'].strip()))
    srt_content = srt.compose(subtitles)
    write_srt_file(srt_content, "en")
    return srt_content

@timeit
def write_srt_file(content, lang_code):
    with open(lang_code+".srt", 'w') as f:
        f.write(content)




if __name__ == "__main__":
    main()

