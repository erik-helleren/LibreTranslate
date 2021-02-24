# Todo

## Video transcribe and translate tasks

- [X] Create project concept: 1 video = 1 project = 1 folder
- [X] Delete a project
- [X] GUI: List all projects on a single page
- [X] GUI: Project detail
- [X] GUI + API: Create new project by uploading video to create a new project
- [X] Parse video when creating a new project to: Extract image, detect duration
- [X] Write transcribe API to: 1. Strip audio out of video file. 2. Create a subtitle file from audio file. 3. Add subtitle to project
- [X] Download SRT files, including a zip of all of the files
- [X] Move transcription to an async job/python task/external script.  (Processing time >> Startup time for batch jobs)  
- [ ] Lock requests for translation from coming in while its in progress.  Trigger automatically on upload
- [ ] Fully dockerize the new models
- [ ] Note that transcription in progress on project page
- [ ] Improve visuals on project page and projects list page.  
- [ ] Move downloading models into the docker startup rather than doing it as part of the image


### Optional

## Live  translation

GUI: Web based microphone front end, stream media in chunks to backend.  Display a connection code, and various languages.

Python Transcription script/endpoint: Listen on a microphone attached to server, publish chunks to mqtt.  Chunk has max words.  Publish every N seconds (float)
{lastChunk: "", last_chunk_id=1, inProgressChunkId=2 inProgressChunk: ""}

mqtt "English subtitles"

Python translation script: Startup up with a target language, so need 1 per language.  Read from mqtt english queue and publish to language queue.  
Language queue should be enhanced with english chunks and translated chunk for display.

Front end: Pick a language, displays the latest in your languages queue directly from mqtt.  

- [ ] Build endpoint to receive audio chunks
- [ ] Support multiple streamers using some sort of ID.  Having a god aweful link for now is acceptable.
- [ ] GUI+JS: Create recording web page.  Should spit back transcription as it happens.  
- [ ] Build translation code and chunking logic.  
- [ ] Translation script.  Only translate last_chunk once, based on ID.  New id = new translation.  
- [ ] GUI: Page to start/stop realtime transcription/translation.   Select target languages using combo boxes?  
- [ ] GUI: Student focused, pick one of languages that are supported, connect to mqtt, and start streaming.   
- [ ] Display lag on transcription and translation.   

### Extra options
- [ ] Record audio to file
- [ ] persist transcription
- [ ] persist translations
- [ ]

## Improvements ideas
- [ ] Use a punctuator and training data set, incorporate into subtitle generation and translation.  Punctuation should improve translation, translate a sentence at a time.

## Automation/ease of use
- [ ] Make sure that the env setup scripts are updated to include ffmpeg and deepSpeech
- [ ] Automatically install deepSpeech model

## Cleanup and prep for launch (technical)

- [ ] Remove api keys, Configure rate limit on all actions from env variables. 
- [ ] refactor
- [ ] Linkify live stream so 1 server can serve many streams (If hardware even permits)
- [ ] Clarify API documentation
- [ ] Add test coverage
- [ ] Move transcribing and translation to background threads
- [ ] put FFMPEG into the docker image

## Videos

- [ ] How to use translation page
- [ ] How to transcribe and translate videos
- [ ] How to setup your libretranslate for success

## Stretch deliverables

- Document translation

