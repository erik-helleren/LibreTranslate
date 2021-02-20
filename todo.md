# Todo

## Video transcribe and translate tasks

- [X] Create project concept: 1 video = 1 project = 1 folder
- [X] Delete a project
- [X] GUI: List all projects on a single page
- [X] GUI: Project detail
- [X] GUI + API: Create new project by uploading video to create a new project
- [ ] Parse video when creating a new project to: Extract image, detect duration
- [ ] Write transcribe API to: 1. Strip audio out of video file. 2. Create a subtitle file from audio file. 3. Add subtitle to project
- [ ] Make sure that the env setup scripts are updated to include ffmpeg and deepSpeech
- [ ] Automatically install deepSpeech model

## Live  translation

- [ ] Figure out the right architecutre for this... Considering english transcription sent to client, client pick language on their end, and the web browser makes translation requests to the server.  Alt, Transcribe and then translate in line to N configured languages the teacher picks when starting the stream.  
- [ ] Create live audio stream to server + transcribe to log as first pass
- [ ] Option to save audio and transcript if you want. 
- [ ] Break transcription into sentences, phrases etc and stream to clients
- [ ] Video: How to setup your classroom

## Cleanup and prep for launch (technical)

- [ ] Remove api keys, Configure rate limit on all actions from env variables
- [ ] Linkify live stream so 1 server can serve many streams

## Videos

- [ ] How to use translation page
- [ ] How to transcribe and translate videos
- [ ] How to setup your libretranslate for success

## Streach deliverables

- Document translation

