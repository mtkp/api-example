"""
Partner example app

Start a simple app server:
 - allow user login via Climate
 - display user's Climate fields
 - retrieve field boundary info
 - basic file upload to Climate

We use Flask in this example to provide a simple HTTP server. You will notice
that some of the functions in this file are decorated with @app.route() which
registers them with Flask as functions to service requests to the specified
URIs.

This file (main.py) provides the web UI and framework for the demo app. All
the work with the Climate API happens in climate.py.

Note: For this example, only one "user" can be logged into the example app at
a time.

License:
Copyright © 2018 The Climate Corporation
"""

import json
import os
from logger import Logger

from flask import Flask, request, redirect, url_for, send_from_directory
from flask import Response, stream_with_context
import climate

# Configuration of your Climate partner credentials. This assumes you have
# placed them in your environment. You may
# also choose to just hard code them here if you prefer.

CLIMATE_API_ID = os.environ['CLIMATE_API_ID']         # OAuth2 client ID
CLIMATE_API_SECRET = os.environ['CLIMATE_API_SECRET']   # OAuth2 client secret
CLIMATE_API_SCOPES = os.environ['CLIMATE_API_SCOPES']  # Oauth2 scope list
CLIMATE_API_KEY = os.environ['CLIMATE_API_KEY']       # X-Api-Key header
# Partner app server

app = Flask(__name__)
logger = Logger(app.logger)

# User state - only one user at a time. In your application this would be
# handled by your session management and backing
# storage.

_state = {}


def set_state(**kwargs):
    global _state
    if 'access_token' in kwargs:
        _state['access_token'] = kwargs['access_token']
    if 'refresh_token' in kwargs:
        _state['refresh_token'] = kwargs['refresh_token']
    if 'user' in kwargs:
        _state['user'] = kwargs['user']
    if 'fields' in kwargs:
        _state['fields'] = kwargs['fields']


def clear_state():
    set_state(access_token=None, refresh_token=None, user=None, fields=None)


def state(key):
    global _state
    return _state.get(key)


# Routes


@app.route('/home')
def home():
    if state('user'):
        return user_homepage()
    return no_user_homepage()


def no_user_homepage():
    """
    This is logically the first place a user will come. On your site it will
    be some page where you present them with a link to Log In with FieldView.
    The main thing here is that you provide a correctly formulated link with
    the required parameters and correct button image.
    :return: None
    """
    url = climate.login_uri(CLIMATE_API_ID, CLIMATE_API_SCOPES, redirect_uri())
    return """
            <h1>Partner API Demo Site</h1>
            <h2>Welcome to the Climate Partner Demo App.</h2>
            <p>Imagine that this page is your great web application and you
            want to connect it with Climate FieldView. To do this, you need
            to let your users establish a secure connection between your app
            and FieldView. You do this using Log In with FieldView.</p>
            <p style="text-align:center"><a href="{}">
            <img src="./res/fv-login-button.png"></a></p>""".format(url)


def user_homepage():
    """
    This page just demonstrates some basic Climate FieldView API operations
    such as getting field details, accessing user information and and
    refreshing the authorization token.
    :return: None
    """
    field_list = render_ul(render_field_link(f) for f in state('fields'))
    return """
           <h1>Partner API Demo Site</h1>
           <p>User name retrieved from FieldView: {first} {last}</p>
           <p>Access Token: {access_token}</p>
           <p>Refresh Token: {refresh_token}
           (<a href="{refresh}">Refresh</a>)</p>
           <table style="border-spacing: 50px 0;"><tr><td>
           <p>Your Climate fields:{fields}</p>
           <p><a href="{upload}">Upload data</a></p>
           <p><a href="{scouting_observations}">Scouting Observations</a></p>
           </td><td>
           <p>Your fields activities:</p>
           <p><a href="{as_planted}" > asPlanted </a></p>
           <p><a href="{as_harvested}" > asHarvested </a></p>
           <p><a href="{as_applied}" > asApplied</a></p>
           </td></tr></table>
           <p><a href="{logout}">Log out</a></p>
           """.format(first=state('user')['firstname'],
                      last=state('user')['lastname'],
                      access_token=state('access_token'),
                      refresh_token=state('refresh_token'),
                      fields=field_list,
                      upload=url_for('upload_form'),
                      logout=url_for('logout_redirect'),
                      refresh=url_for('refresh_token'),
                      scouting_observations=url_for('scouting_observations'),
                      as_planted=url_for('as_planted'),
                      as_harvested=url_for('as_harvested'),
                      as_applied=url_for('as_applied'))


@app.route('/login-redirect')
def login_redirect():
    """
    This is the page a user will come back to after having successfully logged
    in with FieldView. The URI was provided as one of the parameters to the
    login URI above. The "code" parameter in the URI's query string contains
    the access_token and refresh_token.
    :return:
    """
    code = request.args['code']
    if code:
        resp = climate.authorize(code,
                                 CLIMATE_API_ID,
                                 CLIMATE_API_SECRET,
                                 redirect_uri())
        if resp:
            # Store tokens and user in state for subsequent requests.
            access_token = resp['access_token']
            refresh_token = resp['refresh_token']
            set_state(user=resp['user'],
                      access_token=access_token,
                      refresh_token=refresh_token)

            # Fetch fields and store in state just for example purposes. You
            # might well do this at the time of need,
            # or not at all depending on your app.
            fields = climate.get_fields(access_token, CLIMATE_API_KEY)
            set_state(fields=fields)

    return redirect(url_for('home'))


@app.route('/refresh-token')
def refresh_token():
    """
    This route doesn't have any page associated with it; it just refreshes the
    authorization token and redirects back to the home page. As a by-product,
    this also refreshes the user data.
    :return:
    """
    resp = climate.reauthorize(state('refresh_token'),
                               CLIMATE_API_ID,
                               CLIMATE_API_SECRET)
    if resp:
        # Store tokens and user in state for subsequent requests.
        access_token = resp['access_token']
        refresh_token = resp['refresh_token']
        set_state(user=resp['user'], access_token=access_token,
                  refresh_token=refresh_token)

    return redirect(url_for('home'))


@app.route('/logout-redirect')
def logout_redirect():
    """
    Clears all current user data. Does not make any Climate API calls.
    :return:
    """
    clear_state()
    return redirect(url_for('home'))


@app.route('/field/<field_id>')
def field(field_id):
    """
    Shows how to fetch field boundary information and displays it as raw
    geojson data.
    :param field_id:
    :return:
    """
    field = [f for f in state('fields') if f['id'] == field_id][0]

    boundary = climate.get_boundary(field['boundaryId'],
                                    state('access_token'),
                                    CLIMATE_API_KEY)

    return """
           <h1>Partner API Demo Site</h1>
           <h2>Field Name: {name}</h2>
           <p>Boundary info:<pre>{boundary}</pre></p>
           <p><a href="{home}">Return home</a></p>
           """.format(name=field['name'],
                      boundary=json.dumps(boundary, indent=4, sort_keys=True),
                      home=url_for('home'))


@app.route('/upload', methods=['GET', 'POST'])
def upload_form():
    """
    Initially (when method=GET) render the upload form to collect information
    about the file to upload.When the form is POSTed, invoke the actual Climate
    API code to do the chunked upload.
    :return:
    """
    if request.method == 'POST':
        if 'file' not in request.files or request.files['file'].stream is None:
            return redirect(url_for('upload_form'))

        f = request.files['file']
        content_type = request.form['file_content_type']
        upload_id = climate.upload(
            f, content_type, state('access_token'), CLIMATE_API_KEY)

        return """
            <h1>Partner API Demo Site</h1>
            <h2>Upload data</h2>
            <p>File uploaded: {upload_id}
            <a href='{status_url}'>Get Status</a></p>
            <p><a href="{home}">Return home</a></p>
            """.format(upload_id=upload_id,
                       status_url=url_for(
                           'update_status', upload_id=upload_id),
                       home=url_for('home'))

    return """
           <h1>Partner API Demo Site</h1>
           <h2>Upload data</h2>
           <form method=post enctype=multipart/form-data>
           <p>Content type:<input type=text name=file_content_type /></p>
           <p><input type=file name=file /></p>
           <p><input type=submit value=Upload /></p>
           </form>
           <p><a href="{home}">Return home</a></p>
           """.format(home=url_for('home'))


@app.route('/upload/<upload_id>', methods=['GET'])
def update_status(upload_id):
    """
    Shows the status of an upload. Uploads are processed asynchronously so to
    know if an upload was successful you need to check its status until it is
    either in the INBOX or SUCCESS state (it worked) or the INVALID state
    (it failed). This method demonstrates the API call to get the status for
    a single upload id. There is also a call to get stattus for a list
    of upload ids.
    :param upload_id: uuid of upload returned by API.
    :return:
    """
    status = climate.get_upload_status(upload_id,
                                       state('access_token'),
                                       CLIMATE_API_KEY)

    return """
           <h1>Partner API Demo Site</h1>
           <h2>Upload ID: {upload_id}</h2>
           <p>Status: {status} <a href="#" onclick="location.reload();">
           Refresh</a></p>
           <p><a href="{home}">Return home</a></p>
           """.format(upload_id=upload_id,
                      status=status.get('status'),
                      home=url_for('home'))


# Various utilities just to make the demo app work. No Climate API stuff here.


@app.route('/res/<path:path>')
def send_res(path):
    """
    Sends a static resource.
    """
    return send_from_directory('res', path)


def render_ul(xs):
    return '<ul>{}</ul>'.format('\n'.join('<li>{}</li>'.format(x) for x in xs))


def render_field_link(field):
    field_id = field['id']
    return '<a href="{link}">{name} ({id})</a>'.format(
        link=url_for('field', field_id=field_id),
        name=field['name'],
        id=field_id)


def render_scouting_observation_link(scouting_observation):
    oid = scouting_observation['id']
    return '<a href="{link}">{oid}</a>'.format(
        link=url_for('scouting_observation', scouting_observation_id=oid),
        oid=oid)


def render_attachment_link(scouting_observation_id, attachment):
    attachment_id = attachment['id']
    if attachment['status'] == 'DELETED':
        link = ''
    else:
        link = ': <a href="{link}" >Get contents</a>'.format(
            link=url_for('scouting_observation_attachments_contents',
                         scouting_observation_id=scouting_observation_id,
                         attachment_id=attachment_id,
                         contentType=attachment['contentType'],
                         length=attachment['length']))

    return """<h2>{attachment_id}{link}</h2>
            <p><pre>{info}</pre></p>
            """.format(link=link,
                       attachment_id=attachment_id,
                       info=json.dumps(attachment, indent=4, sort_keys=True))


def render_activitiy_link(activity, link):
    activity_id = activity['id']
    link = '{link}/{activity_id}/contents?length={length}'.format(
        link=link,
        activity_id=activity_id,
        length=activity['length'])

    return """
            {activity_id} : <a href="{link}"> Get contents </a>
            <p><pre>{body}</pre></p>
           """.format(activity_id=activity_id,
                      link=link,
                      body=json.dumps(activity, indent=4, sort_keys=True))


def redirect_uri():
    """
    :return: Returns uri for redirection after Log In with FieldView.
    """
    return url_for('login_redirect', _external=True)


@app.route('/scouting-observation/<scouting_observation_id>', methods=['GET'])
def scouting_observation(scouting_observation_id):
    """
    Shows the details of a scouting observation
    :param scouting_observation_id: a scouting observation identifier

    :return: returns the html response
    """
    observation = climate.get_scouting_observation(state('access_token'),
                                                   CLIMATE_API_KEY,
                                                   scouting_observation_id)
    return """
        <h1>Partner API Demo Site</h1>
        <h2>Scouting Observation ID: {scouting_observation_id}</h2>
        <p><pre>{json}</pre></p>
        <p><a href='{attachments}'>List attachments</a></p>
        <p><a href='{observations}'>Return to Observations list</a></p>
        <p><a href='{home}'>Return home</a></p>
        """.format(scouting_observation_id=scouting_observation_id,
                   json=json.dumps(observation, indent=4, sort_keys=True),
                   observations=url_for('scouting_observations'),
                   attachments=url_for(
                       'scouting_observation_attachments',
                       scouting_observation_id=scouting_observation_id),
                   home=url_for('home'))


@app.route('/scouting-observations', methods=['GET'])
def scouting_observations():
    """
    Displays the list of scouting observations

    :return: returns the html response which shows list of observations
    """
    observations = climate.get_scouting_observations(state('access_token'),
                                                     CLIMATE_API_KEY,
                                                     100)
    body = "<p>No Scouting Observations found!</p>"
    if observations:
        scouting_observations = render_ul(
            render_scouting_observation_link(o) for o in observations)
        body = "<p>Your Climate Scouting Observations:\
        {scouting_observations}</p>".format(
            scouting_observations=scouting_observations)

    return """
            <h1>Partner API Demo Site</h1>
            {body}
            <p><a href='{home}'>Return home</a></p>
            """.format(body=body, home=url_for('home'))


@app.route('/scouting-observation/<scouting_observation_id>/attachments',
           methods=['GET'])
def scouting_observation_attachments(scouting_observation_id):
    """
    Shows the list of attachments for a given scouting observation
    :param scouting_observation_id: a scouting observation identifier
    :return: returns html which shows list of attachments.
    """
    ats = climate.get_scouting_observation_attachments(state('access_token'),
                                                       CLIMATE_API_KEY,
                                                       scouting_observation_id)

    body = "<p>No attachments found!</p>"
    if ats:
        attachments = render_ul(
            render_attachment_link(scouting_observation_id, a) for a in ats)
        body = "<p>Your Climate Scouting Observations attachments:\
        {attachments}</p>".format(
            attachments=attachments)

    return """
            <h1>Partner API Demo Site</h1>
            {body}
            <p><a href='{attachments}'>Return to Observation:{soid}</a></p>
            <p><a href='{home}'>Return home</a></p>
            """.format(body=body,
                       home=url_for('home'),
                       attachments=url_for(
                           'scouting_observation',
                           scouting_observation_id=scouting_observation_id),
                       soid=scouting_observation_id)


@app.route(
    '/scouting-observation/<scouting_observation_id>'
    '/attachments/<attachment_id>',
    methods=['GET'])
def scouting_observation_attachments_contents(scouting_observation_id,
                                              attachment_id):
    """
    Downloads the attachment contents
    :param scouting_observation_id: a scouting observation identifier
    :param attachment_id: an attachment identifier
    :return: returns contents of attachment.
    """
    content_type = request.args.get('contentType')
    length = int(request.args.get('length'))
    # stream the content back to client
    headers = {
        'Content-type': 'image/jpeg'
    }
    content = climate.get_scouting_observation_attachments_contents(
        state('access_token'),
        CLIMATE_API_KEY,
        scouting_observation_id,
        attachment_id,
        content_type,
        length
    )
    return Response(response=content, headers=headers)


def get_callee(activity):
    method = 'get_{}'.format(activity)
    return getattr(climate, method)


def handle_activity(activity):

    next_token = request.args.get('next_token')
    has_more_records, activities = get_callee(activity)(
        state('access_token'),
        CLIMATE_API_KEY,
        next_token)

    body = "<p>No data found!</p>"

    if activities is not None:
        activities_list = render_ul(render_activitiy_link(
            a, url_for(activity)) for a in activities)
        body = "<p>Your Climate {activity} activities:{activities_list}</p>"\
            .format(activities_list=activities_list, activity=activity)

    more_records_html = ""
    if has_more_records is not None:
        next_link = url_for(activity, next_token=has_more_records)
        more_records_html = "<p><a href='{next_link}'>More records >>\
                            </a></p>".format(next_link=next_link)
    return """
            <h1>Partner API Demo Site</h1>
            {body}
            {more_records_html}
            <p><a href='{home}'>Return home</a></p>
            """.format(body=body,
                       home=url_for('home'),
                       more_records_html=more_records_html)


@app.route('/layers/asPlanted', methods=['GET'])
def as_planted():
    """
    Shows list of planting activities
    :return: returns planting activities.
    """
    return handle_activity("as_planted")


@app.route('/layers/asHarvested', methods=['GET'])
def as_harvested():
    """
    Shows list of harvesting activities
    :return: returns harvesting activities.
    """
    return handle_activity("as_harvested")


@app.route('/layers/asApplied', methods=['GET'])
def as_applied():
    """
    Shows list of application activities
    :return: returns application activities.
    """
    return handle_activity("as_applied")


@app.route('/layers/<layer_id>/<activity_id>/contents')
def get_activity_contents(layer_id, activity_id):
    """
    Download the contents of given activity
    :param layer_id: name of activity
    :param activity_id: id of activity
    :return: returns contents of given activity.
    """
    length = int(request.args.get('length'))
    content = climate.get_activity_contents(
        state('access_token'),
        CLIMATE_API_KEY,
        layer_id,
        activity_id,
        length)
    response = Response(stream_with_context(content),
                        mimetype='application/zip')
    response.headers['Content-Disposition'] = 'attachment; filename=data.zip'
    return response


# start app


if __name__ == '__main__':
    clear_state()
    app.run(
        host="localhost",
        port=8080
    )
