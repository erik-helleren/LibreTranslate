import os
from flask import Flask, render_template, jsonify, request, abort, send_from_directory, redirect
from flask_swagger import swagger
from flask_swagger_ui import get_swaggerui_blueprint
from langdetect import detect_langs
from langdetect import DetectorFactory
from pkg_resources import resource_filename
from .api_keys import Database
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
import subprocess
import sys

home_dir=os.getcwd()
DetectorFactory.seed = 0  # deterministic

ALLOWED_EXTENSIONS = {'mp4', 'mkv', 'mp3'}

api_keys_db = None


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


def get_remote_address():
    if request.headers.getlist("X-Forwarded-For"):
        ip = request.headers.getlist("X-Forwarded-For")[0]
    else:
        ip = request.remote_addr or '127.0.0.1'

    return ip


def get_routes_limits(default_req_limit, api_keys_db):
    if default_req_limit == -1:
        # TODO: better way?
        default_req_limit = 9999999999999

    def limits():
        req_limit = default_req_limit

        if api_keys_db:
            if request.is_json:
                json = request.get_json()
                api_key = json.get('api_key')
            else:
                api_key = request.values.get("api_key")

            if api_key:
                db_req_limit = api_keys_db.lookup(api_key)
                if db_req_limit is not None:
                    req_limit = db_req_limit

        return "%s per minute" % req_limit

    return [limits]


def create_app(args):
    logging.basicConfig(level=logging.DEBUG)
    if not args.offline:
        from app.init import boot
        boot()

    from app.language import languages
    app = Flask(__name__)

    project_directory = args.project_directory
    if not os.path.exists(project_directory):
        os.makedirs(project_directory)

    # For faster access
    language_map = {}
    for l in languages:
        language_map[l.code] = l.name

    if args.debug:
        app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024
    # Map userdefined frontend languages to argos language object.
    if args.frontend_language_source == "auto":
        frontend_argos_language_source = type('obj', (object,), {
            'code': 'auto',
            'name': 'Auto Detect'
        })
    else:
        frontend_argos_language_source = next(
            iter([l for l in languages if l.code == args.frontend_language_source]), None)

    frontend_argos_language_target = next(
        iter([l for l in languages if l.code == args.frontend_language_target]), None)

    # Raise AttributeError to prevent app startup if user input is not valid.
    if frontend_argos_language_source is None:
        raise AttributeError(
            f"{args.frontend_language_source} as frontend source language is not supported.")
    if frontend_argos_language_target is None:
        raise AttributeError(
            f"{args.frontend_language_target} as frontend target language is not supported.")

    if args.req_limit > 0 or args.api_keys:
        from flask_limiter import Limiter
        limiter = Limiter(
            app,
            key_func=get_remote_address,
            default_limits=get_routes_limits(
                args.req_limit, Database() if args.api_keys else None)
        )
    model_load_start = timer()
    ds = Model(os.path.join(home_dir,"models","deepspeech-0.9.3-models.tflite"))
    ds.enableExternalScorer(os.path.join(home_dir,"models","deepspeech-0.9.3-models.scorer"))
    model_load_end = timer() - model_load_start
    logging.info('Loaded model in {:.3}s.'.format(model_load_end))
    desired_sample_rate = ds.sampleRate()
    logging.info('Model optimized for a sample rate of ' +
                 str(desired_sample_rate))
    uuid4hex = re.compile(
        '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z', re.I)

    @app.errorhandler(400)
    def invalid_api(e):
        return jsonify({"error": str(e.description)}), 400

    @app.errorhandler(500)
    def server_error(e):
        return jsonify({"error": str(e.description)}), 500

    @app.errorhandler(429)
    def slow_down_error(e):
        return jsonify({"error": "Slowdown: " + str(e.description)}), 429

    @app.route("/")
    @limiter.exempt
    def index():
        return render_template('index.html', gaId=args.ga_id, frontendTimeout=args.frontend_timeout, offline=args.offline, api_keys=args.api_keys, web_version=os.environ.get('LT_WEB') is not None)

    @app.route("/projects")
    @limiter.exempt
    def projects():
        return render_template('projects.html', gaId=args.ga_id, frontendTimeout=args.frontend_timeout, offline=args.offline, api_keys=args.api_keys, projects=loadAllProjects(), web_version=os.environ.get('LT_WEB') is not None)

    @app.route("/project/<id>")
    @limiter.exempt
    def project(id):
        if not uuid4hex.match(id):
            logging.error("Invalid project id")
            return redirect("/projects")
        return render_template('project.html', gaId=args.ga_id, frontendTimeout=args.frontend_timeout, offline=args.offline, api_keys=args.api_keys, project=loadProjectDetails(id), web_version=os.environ.get('LT_WEB') is not None)

    @app.route("/project/<id>/delete")
    @limiter.exempt
    def projectDelete(id):
        delete_project(id)
        return redirect("/projects")

    @app.route("/project/<id>/transcription")
    @limiter.exempt
    def projectTranscribe(id):
        if not uuid4hex.match(id):
            flash("Invalid project id")
            return redirect("/projects")

        subprocess.Popen([sys.executable, os.path.join(home_dir,'scripts', 'batch.py'], cwd=os.path.join(project_directory, id),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
        return redirect("/project/"+id)

    @app.route("/project/<id>/download/<file>")
    def download(id, file):
        # todo validate the file part

        metadata = loadProjectDetails(id)
        if metadata is None:
            logging.info("Unable to find metdata for project ID: "+id)
            return redirect("/projects")
        return send_from_directory(directory=metadata['project_dir'], filename=file, as_attachment=True)

    @app.route("/create-project")
    @limiter.exempt
    def createProject():
        return render_template('create-project.html', gaId=args.ga_id, frontendTimeout=args.frontend_timeout, offline=args.offline, api_keys=args.api_keys, web_version=os.environ.get('LT_WEB') is not None)

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    @app.route('/new-project-upload', methods=['GET', 'POST'])
    def uploadProject():
        if request.method == 'POST':
            # check if the post request has the file part
            if 'file' not in request.files:
                return redirect(request.url)
            file = request.files['file']
            # if user does not select file, browser also
            # submit an empty part without filename
            if file.filename == '':
                return redirect(request.url)
            if file and allowed_file(file.filename):
                project_id = str(uuid.uuid4())
                if not os.path.exists(os.path.join(project_directory, project_id)):
                    os.makedirs(os.path.join(project_directory, project_id))
                fileending = file.filename.rsplit('.', 1)[1].lower()
                file.save(os.path.join(project_directory,
                                       project_id, "rawMedia."+fileending))
                # TODO store original file name
                metadata = createMetadata(
                    project_id, request.form['name'], fileending)
                with open(os.path.join(project_directory, project_id, "metadata.json"), 'w') as f:
                    json.dump(metadata, f)

                return redirect("./project/"+project_id)
        return

    @timeit
    def createMetadata(project_id, name, ending):
        metadata = {"name": name, "fileEnding": ending}
        in_filename = os.path.join(
            project_directory, project_id, "rawMedia."+ending)
        probe = ffmpeg.probe(in_filename)
        video_stream = next(
            (stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        logging.debug(str(video_stream))
        metadata['width'] = int(video_stream['width'])
        metadata['height'] = int(video_stream['height'])
        metadata['durationSeconds'] = float(video_stream['duration'])
        (
            ffmpeg
            .input(in_filename, ss=3)
            .filter('scale', 512, -1)
            .output(os.path.join(project_directory, project_id, "thumbnail.png"), vframes=1)
            .run()
        )
        return metadata

    def delete_project(project_id):
        logging.info("Deleting a project with ID: "+project_id)
        # TODO make sure tha ID is a valid ID an not just some bad path
        shutil.rmtree(os.path.join(project_directory, project_id))

    @app.route("/languages", methods=['GET', 'POST'])
    @limiter.exempt
    def langs():
        """
        Retrieve list of supported languages
        ---
        tags:
          - translate
        responses:
          200:
            description: List of languages
            schema:
              id: languages
              type: array
              items:
                type: object
                properties:
                  code:
                    type: string
                    description: Language code
                  name:
                    type: string
                    description: Human-readable language name (in English)
          429:
            description: Slow down
            schema:
              id: error-slow-down
              type: object
              properties:
                error:
                  type: string
                  description: Reason for slow down
        """
        return jsonify([{'code': l.code, 'name': l.name} for l in languages])

    # Add cors
    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers',
                             "Authorization, Content-Type")
        response.headers.add('Access-Control-Expose-Headers', "Authorization")
        response.headers.add('Access-Control-Allow-Methods', "GET, POST")
        response.headers.add('Access-Control-Allow-Credentials', "true")
        response.headers.add('Access-Control-Max-Age', 60 * 60 * 24 * 20)
        return response

    @app.route("/project", methods=['GET'])
    def list_projects():
        """
        List available projects
        ---
        tags:
          - list
        """
        return jsonify({"projects": loadAllProjects()})

    def loadAllProjects():
        output = []
        for project_id in os.listdir(project_directory):
            project_details = loadProjectDetails(project_id)
            if project_details is not None:
                output.append(project_details)
        return output

    def loadProjectDetails(project_id):
        metadata_path = os.path.join(
            project_directory, project_id, "metadata.json")
        if not os.path.exists(metadata_path):
            return None
        metadata = json.loads(Path(metadata_path).read_text())
        metadata["id"] = project_id
        metadata['project_dir'] = os.path.join(project_directory, project_id)
        # TODO rely on this data for everything
        metadata['subtitles'] = []
        for file in os.listdir(metadata['project_dir']):
            if file.endswith(".srt"):
                metadata['subtitles'].append(file)
        if os.path.exists(os.path.join(project_directory,"subtitles.zip")):
            metadata['subtitles'].insert(0, 'subtitles.zip')
        metadata['inputVideo'] = "rawMedia."+metadata['fileEnding']

        metadata['audio'] = "audio.wav"
        return metadata

    @app.route("/translate", methods=['POST'])
    def translate():
        """
        Translate text from a language to another
        ---
        tags:
          - translate
        parameters:
          - in: formData
            name: q
            schema:
              oneOf:
                - type: string
                  example: Hello world!
                - type: array
                  example: ['Hello world!']
            required: true
            description: Text(s) to translate
          - in: formData
            name: source
            schema:
              type: string
              example: en
            required: true
            description: Source language code
          - in: formData
            name: target
            schema:
              type: string
              example: es
            required: true
            description: Target language code
          - in: formData
            name: api_key
            schema:
              type: string
              example: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            required: false
            description: API key
        responses:
          200:
            description: Translated text
            schema:
              id: translate
              type: object
              properties:
                translatedText:
                  oneOf:
                    - type: string
                    - type: array
                  description: Translated text(s)
          400:
            description: Invalid request
            schema:
              id: error-response
              type: object
              properties:
                error:
                  type: string
                  description: Error message
          500:
            description: Translation error
            schema:
              id: error-response
              type: object
              properties:
                error:
                  type: string
                  description: Error message
          429:
            description: Slow down
            schema:
              id: error-slow-down
              type: object
              properties:
                error:
                  type: string
                  description: Reason for slow down
        """

        if request.is_json:
            json = request.get_json()
            q = json.get('q')
            source_lang = json.get('source')
            target_lang = json.get('target')
        else:
            q = request.values.get("q")
            source_lang = request.values.get("source")
            target_lang = request.values.get("target")

        if not q:
            abort(400, description="Invalid request: missing q parameter")
        if not source_lang:
            abort(400, description="Invalid request: missing source parameter")
        if not target_lang:
            abort(400, description="Invalid request: missing target parameter")

        batch = isinstance(q, list)

        if batch and args.batch_limit != -1:
            batch_size = len(q)
            if args.batch_limit < batch_size:
                abort(400, description="Invalid request: Request (%d) exceeds text limit (%d)" % (
                    batch_size, args.batch_limit))

        if args.char_limit != -1:
            if batch:
                chars = sum([len(text) for text in q])
            else:
                chars = len(q)

            if args.char_limit < chars:
                abort(400, description="Invalid request: Request (%d) exceeds character limit (%d)" % (
                    chars, args.char_limit))

        if source_lang == 'auto':
            candidate_langs = list(
                filter(lambda l: l.lang in language_map, detect_langs(q)))

            if len(candidate_langs) > 0:
                candidate_langs.sort(key=lambda l: l.prob, reverse=True)

                if args.debug:
                    print(candidate_langs)

                source_lang = next(
                    iter([l.code for l in languages if l.code == candidate_langs[0].lang]), None)
                if not source_lang:
                    source_lang = 'en'
            else:
                source_lang = 'en'

            if args.debug:
                print("Auto detected: %s" % source_lang)

        src_lang = next(
            iter([l for l in languages if l.code == source_lang]), None)
        tgt_lang = next(
            iter([l for l in languages if l.code == target_lang]), None)

        if src_lang is None:
            abort(400, description="%s is not supported" % source_lang)
        if tgt_lang is None:
            abort(400, description="%s is not supported" % target_lang)

        translator = src_lang.get_translation(tgt_lang)

        try:
            if batch:
                return jsonify({"translatedText": [translator.translate(text) for text in q]})
            else:
                return jsonify({"translatedText": translator.translate(q)})
        except Exception as e:
            abort(500, description="Cannot translate text: %s" % str(e))

    @app.route("/detect", methods=['POST'])
    def detect():
        """
        Detect the language of a single text
        ---
        tags:
          - translate
        parameters:
          - in: formData
            name: q
            schema:
              type: string
              example: Hello world!
            required: true
            description: Text to detect
          - in: formData
            name: api_key
            schema:
              type: string
              example: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
            required: false
            description: API key
        responses:
          200:
            description: Detections
            schema:
              id: detections
              type: array
              items:
                type: object
                properties:
                  confidence:
                    type: number
                    format: float
                    minimum: 0
                    maximum: 1
                    description: Confidence value
                    example: 0.6
                  language:
                    type: string
                    description: Language code
                    example: en
          400:
            description: Invalid request
            schema:
              id: error-response
              type: object
              properties:
                error:
                  type: string
                  description: Error message
          500:
            description: Detection error
            schema:
              id: error-response
              type: object
              properties:
                error:
                  type: string
                  description: Error message
          429:
            description: Slow down
            schema:
              id: error-slow-down
              type: object
              properties:
                error:
                  type: string
                  description: Reason for slow down
        """
        if request.is_json:
            json = request.get_json()
            q = json.get('q')
        else:
            q = request.values.get("q")

        if not q:
            abort(400, description="Invalid request: missing q parameter")

        candidate_langs = list(
            filter(lambda l: l.lang in language_map, detect_langs(q)))
        candidate_langs.sort(key=lambda l: l.prob, reverse=True)
        return jsonify([{
            'confidence': l.prob,
            'language': l.lang
        } for l in candidate_langs])

    @app.route("/frontend/settings")
    @limiter.exempt
    def frontend_settings():
        """
        Retrieve frontend specific settings
        ---
        tags:
          - frontend
        responses:
          200:
            description: frontend settings
            schema:
              id: frontend-settings
              type: object
              properties:
                charLimit:
                  type: integer
                  description: Character input limit for this language (-1 indicates no limit)
                frontendTimeout:
                  type: integer
                  description: Frontend translation timeout
                language:
                  type: object
                  properties:
                    source:
                      type: object
                      properties:
                        code:
                          type: string
                          description: Language code
                        name:
                          type: string
                          description: Human-readable language name (in English)
                    target:
                      type: object
                      properties:
                        code:
                          type: string
                          description: Language code
                        name:
                          type: string
                          description: Human-readable language name (in English)
        """
        return jsonify({'charLimit': args.char_limit,
                        'frontendTimeout': args.frontend_timeout,
                        'language': {
                            'source': {'code': frontend_argos_language_source.code, 'name': frontend_argos_language_source.name},
                            'target': {'code': frontend_argos_language_target.code, 'name': frontend_argos_language_target.name}}
                        })

    swag = swagger(app)
    swag['info']['version'] = "1.2"
    swag['info']['title'] = "LibreTranslate"

    @app.route("/spec")
    @limiter.exempt
    def spec():
        return jsonify(swag)

    SWAGGER_URL = '/docs'  # URL for exposing Swagger UI (without trailing '/')
    API_URL = '/spec'

    # Call factory function to create our blueprint
    swaggerui_blueprint = get_swaggerui_blueprint(
        SWAGGER_URL,
        API_URL
    )

    app.register_blueprint(swaggerui_blueprint)

    return app
