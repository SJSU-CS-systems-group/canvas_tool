from canvasapi import Canvas
from canvasapi.course import Course
from canvasapi.requester import Requester
import click
from collections import defaultdict, namedtuple
from configparser import ConfigParser
import datetime
import functools
import glob
import logging
from html.parser import HTMLParser
import os
import re
import shutil
import string
import sys
import urllib
import urllib.request

import requests

course_name_matcher=r"((\S*): (\S+)\s.*)"
course_name_formatter=r"\2:\3"

def format_course_name(name, matcher=course_name_matcher, formatter=course_name_formatter):
    if formatter == '-':
        return name
    return re.sub(matcher, formatter, name)

def introspect(o):
    print("class", o.__class__)
    for i in dir(o):
        print(i)

# this file has the url and token we will use
config_ini = click.get_app_dir("canvas_tool.ini")


def error(message):
    click.echo(click.style(message, fg='red'))


def info(message):
    click.echo(click.style(message, fg='blue'))


def output(message):
    click.echo(message)


@functools.lru_cache
def get_requester():
    parser = ConfigParser()
    parser.read([config_ini])
    if "SERVER" not in parser:
        error(f"did not find [SERVER] section in {config_ini}")
        info("try using the help-me-setup command")
        sys.exit(1)
    return Requester(parser['SERVER']['url'], parser['SERVER']['token'])
    

access_token = None
canvas_url = None

def get_canvas_object():
    parser = ConfigParser()
    parser.read([config_ini])
    if "SERVER" not in parser:
        error(f"did not find [SERVER] section in {config_ini}")
        info("try using the help-me-setup command")
        sys.exit(1)
    if 'url' not in parser['SERVER'] or 'token' not in parser['SERVER']:
        error(f"did not find url or token in {config_ini}")
        info("try using the help-me-setup command")
        sys.exit(1)
    try:
        canvas = Canvas(parser['SERVER']['url'], parser['SERVER']['token'])
        user = canvas.get_current_user()
        info(f"accessing canvas as {user.name} ({user.id})")
        canvas.user_id = user.id
        global access_token, canvas_url
        access_token = parser['SERVER']['token']
        canvas_url = parser['SERVER']['url']
        return canvas
    except:
        error(f"there was a problem accessing canvas. try using help-me-setup.")
        sys.exit(2)


@click.group()
@click.option("--log-level",
    type=click.Choice(['CRITICAL','ERROR', 'WARNING', 'INFO', 'DEBUG'], case_sensitive=False),
    help="set python logging level")
def canvas_tool(log_level):
    if log_level:
        log_level_int = getattr(logging, log_level.upper())
        print(log_level_int)
        logging.basicConfig(level=log_level_int)


def get_course(canvas, name, is_active=True) -> Course:
    ''' find one course based on partial match '''
    course_list = get_courses(canvas, name, is_active) 
    if len(course_list) == 0:
        error(f'no courses found that contain {name}. options are:')
        for c in get_courses(canvas, "", is_active):
            error(fr"    {c.name}")
        sys.exit(2)
    elif len(course_list) > 1:
        error(f"multiple courses found for {name}:")
        for c in course_list:
            error(f"    {c.name}")
        sys.exit(2)
    return course_list[0]

def get_courses(canvas: Canvas, name: str, is_active=True, is_finished=False) -> [Course]:
    ''' find the courses based on partial match '''
    courses = canvas.get_courses(enrollment_type="teacher")
    now = datetime.datetime.now(datetime.timezone.utc)
    course_list = []
    for c in courses:
        start = c.start_at_date if hasattr(c, "start_at_date") else now
        end = c.end_at_date if hasattr(c, "end_at_date") else now
        if is_active and (start > now or end < now):
            continue
        if is_finished and end < now:
            contine
        if name in c.name:
            c.start = start
            c.end = end
            course_list.append(c)
    return course_list


def get_assignment(course, title):
    ''' find the assignment based on partial match '''
    assignments = list(course.get_course_level_assignment_data())
    filtered_assignments = [a for a in assignments if title in a['title']]
    if not title:
        # if an assignment title wasn't specified, we don't want to return
        # anything even if there is one result.
        output(f'possible assignments for {course.name}')
        for a in assignments:
            output(f"    {a['title']}")
        sys.exit(1)
    if len(filtered_assignments) == 0:
        error(f'{title} assignment not found. possible assignments are:')
        for a in assignments:
            error(f"    {a['title']}")
        sys.exit(2)
    if len(filtered_assignments) > 1:
        error(f'multiple assignments found matching {title}:')
        for a in filtered_assignments:
            error(f"    {a['title']}")
        sys.exit(2)
    return course.get_assignment(filtered_assignments[0]['assignment_id'])


def maybe_a_word(word):
    if not word.isalpha():
        return False

    word = word.strip().lower()
    vowels = [x for x in word if x in "aeiou"]
    if not vowels:
        return False

    ratio = round(len(word)/len(vowels),1)
    return 1.5 <= ratio <= 8.0

class WordCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.checked_word_count = 0
        self.word_count = 0

    def handle_data(self, data):
        data.translate(str.maketrans('', '', string.punctuation))
        words = re.findall(r'\w+', data)
        self.word_count += len(words)
        self.checked_word_count += len(set([w for w in words if maybe_a_word(w)]))


def count_words(content):
        wc = WordCounter()
        wc.feed(content)
        return wc.checked_word_count




@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
        help="only show the grade, don't actually set it")
def download_submissions(course_name, assignment_name, dryrun):
    '''
    download submissions for an assignment.
    '''

    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    assignment = get_assignment(course, assignment_name)

    query = """
    query submissions($assignmentid: ID!) {
        assignment(id: $assignmentid) { submissionsConnection {
            nodes { attachments { url displayName } user { name }
                    commentsConnection { nodes { comment attachments { url displayName}}}
            }
        }}
    }
    """
    session = requests.Session()
    with session.post(canvas_url+"/api/graphql",
                      json={"query": query, "variables": {"assignmentid": assignment.id}},
                      headers={
                           "X-CSRF-Token": "{CSRF}",
                           "Content-Type": "application/json",
                           "Accept": "application/json+canvas-string-ids, application/json, text/plain, */*",
                           "Cookie": "_ga={GA}; fs_uid={UID}; _gid={GID}; _csrf_token={urlencode(CSRF)}; log_session_id={log_sid}; _legacy_normandy_session={leg_norm_sess}; canvas_session={canvas_session}; _gat=1"
                           }) as response:
        result = response.json()
    submissions = result['data']['assignment']['submissionsConnection']['nodes']
    
    if dryrun:
        info(f"{len(submissions)} submissions to download")
        sys.exit(0)

    with click.progressbar(length=len(submissions), label="downloading submission", show_pos=True) as bar:
        for s in submissions:
            count = 1
            name = s['user']['name']
            dir = os.path.join(assignment_name, name.replace(' ', '-'))
            os.makedirs(dir, exist_ok=True)
            for a in s['attachments']:
                download_attachment(f'{dir}/submission{count}', a)
                count += 1
            count = 1
            for c in s['commentsConnection']['nodes']:
                with open(os.path.join(dir, f"comment{count}.txt"), 'w') as fd:
                    fd.write(c['comment'])
                subcount = 1
                for ca in c['attachments']:
                    download_attachment(f'{dir}/comment{count}attachment{subcount}', ca)
                    subcount += 1
                count += 1
            bar.update(1)

def download_attachment(basename, a):
    fname = a['displayName']
    suffix = os.path.splitext(fname)[1]
    durl = a['url']
    with requests.get(durl) as response:
        if response.status_code != 200:
            error(f'error {response.status_code} fetching {durl}')
            return
        with open(f"{basename}{suffix}", "wb") as fd:
            for chunk in response.iter_content():
                fd.write(chunk)

@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
        help="only show the grade, don't actually set it")
@click.option('--min-words', default=5, show_default=True,
        help="the minimum number of valid words to get credit")
def grade_discussion(course_name, assignment_name, dryrun, min_words):
    '''
    grade a discussion assignment based on participation.

    one point is added for a post and another for a reply for a total of 2.
    this tool assumes that the student must post first to reply.

    course_name - any part of an active course name. for example, 249 will match CS249.
    the course must active (it has not passed the end date) to be eligible for matching.
    only the first match will be used.

    assignment_name - any part of an assigment's name will be matched. only the first
    match will be used.
    '''

    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    assignment = get_assignment(course, assignment_name)
    submissions = assignment.get_submissions()
    grades = {}
    skipped = 0
    processed = 0

    # we calculate the grades and upload them in two steps since the second
    # step is slow so we want to do a progress bar. we could still do it all
    # in one pass if we could get the count. i can't find a way to do that
    # without going through the submissions
    for s in submissions:
        processed += 1
        if not hasattr(s, "discussion_entries"):
            skipped += 1
            continue

        grade = 0
        for entry in s.discussion_entries:
            if 'message' in entry and count_words(entry['message']) > 5:
                grade = min(grade+1, 2)

        grades[s] = grade

    if skipped == processed:
        error(f"'{assignment.name}' doesn't appear to be a discussion assignment")
        sys.exit(2)

    info(f"processed {processed}, skipped {skipped}.")

    if dryrun:
        info("would have posted:")
        for i in grades.items():
            info(f"    {i[0]} {i[1]}")
    else:
        with click.progressbar(length=len(grades), label="updating grades", show_pos=True) as bar:
            for i in grades.items():
                i[0].edit(submission={'posted_grade': i[1]})
                bar.update(1)


@canvas_tool.command()
@click.argument('course_name')
@click.argument('quiz_name', default='')
@click.argument('points', default=-1)
def set_fudge_points(course_name, quiz_name, points):
    '''
    set the fudge points for a quiz.

    course_name - any part of an active course name. for example, 249 will match CS249.
    the course must active (it has not passed the end date) to be eligible for matching.
    only the first match will be used.

    quiz_name - any part of an quiz's name will be matched. if multiple quizes match, the
    points will not be set.
    '''

    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    quizzes = list(course.get_quizzes())
    selected_quizzes = [q for q in quizzes if quiz_name in q.title]

    if not selected_quizzes:
        error(f"could not find {quiz_name} in {', '.join([q.title for q in quizzes])}")
    elif len(selected_quizzes) > 1:
        error(f"multiple matches for {quiz_name}: {', '.join([q.title for q in selected_quizzes])}")
    else:
        for s in selected_quizzes[0].get_submissions():
            if points == -1:
                info(f"{s.user_id} {s.fudge_points}")
            else:
                s.update_score_and_comments(fudge_points=points)


@canvas_tool.command()
@click.option('--active/--inactive', default=True, help="show only active courses")
@click.option('--matcher', default=course_name_matcher, show_default=True,
              metavar="match_re_expression", help="course name regular expressions matcher")
@click.option('--formatter', default=course_name_formatter, show_default=True,
              metavar="format_re_expression", help="""
              course name regular expressions formatter based on the matcher pattern.
              a format pattern of - will turn off formatting.
              """
             )
def list_courses(active, matcher, formatter):
    '''list courses i am teaching. --inactive will include past and future courses.'''
    canvas = get_canvas_object()
    courses = get_courses(canvas, "", is_active=active)
    for c in courses:
        name = c.name if hasattr(c, "name") else "none"
        output(f"{c.id} {format_course_name(name, matcher, formatter)} {c.start:%Y-%m-%d} {c.end:%Y-%m-%d}")


@canvas_tool.command()
@click.argument('course')
@click.option('--active/--inactive', default=True, help="show only active courses")
@click.option('--emails/--no_emails', help="list student emails")
def list_students(course, active, emails):
    '''list the students in a course'''
    canvas = get_canvas_object()
    course = get_course(canvas, course, active)
    output(f"found {course.name}")
    info_keys = "name" + (" email" if emails else "")
    results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
               enrollmentsConnection { nodes { user {''' + info_keys + '''} } }
           } }''')
    for r in results['data']['course']['enrollmentsConnection']['nodes']:
        user = r['user']
        output(f"    {user['name']} {user['email'] if 'email' in user else ''}")


@canvas_tool.command()
@click.argument('course')
@click.argument('subject')
@click.option('--course-in-subject/--no-course-in-subject', show_default=True, default=True,
              help='include the course name in []s in the subject line')
@click.option('--message', help="message to send")
@click.option('--from-file', help="file containing message to send (- for stdin)",
                             type=click.File('r'))
@click.argument('students', nargs=-1, required=True)
def message_students(course, subject, message, course_in_subject, from_file, students):
    '''message students in a course'''
    canvas = get_canvas_object()
    course = get_course(canvas, course)

    message_to_send = ""
    if message:
        if not message.endswith("\n"):
            message += "\n"
        message_to_send += message
    if from_file:
        message_to_send += from_file.read()
    if not message and not from_file:
        error("either --message or --from_file must be specified")
        sys.exit(2)

    if course_in_subject:
        subject = f'[{format_course_name(course.name)}] {subject}'

    found_error = False
    to_message = []
    for student in students:
        users = list(course.get_users(search_term=student))
        if not len(users):
            error(f"could not find {student}")
            found_error = True
            continue
        elif len(users) > 1:
            error(f"multiple matches for {student}: {', '.join([str(u) for u in users])}")
            found_error = True
            continue
        to_message.append(users[0])
    if found_error:
        sys.exit(2)

    for user in to_message:
        # we set group_conversation to true to make sure it shows up as a new conversation
        canvas.create_conversation([user.id], message_to_send, subject=subject, group_conversation=True)

def to_plus(grade, levels):
    """ convert a score to a list of pluses based on grade """
    pluses = ""
    for level in levels:
        if grade >= level:
            pluses += '+'
    return pluses

@canvas_tool.command()
@click.argument("course")
@click.option('-t', 'thresholds', metavar='threshold', multiple=True, default=[84,90,95],
              show_default=True, type=click.INT,
              help="""
              assignment groups with grades about the lowest threshold will have a +, the next
              lowest gets ++, and so on. assignment groups below the lowest threshold will not
              be printed.
              """
             )
@click.option('-s', 'skip', metavar='skip_assignment', multiple=True,
              default=['iclickr', 'ungraded', 'imported'], show_default=True,
              help="""
              assignment groups with the listed keywords will not be collected.
              """
             )
def collect_reference_info(course, thresholds, skip):
    '''collect high level information about students of previous classes to help writing reference letters'''
    Grade = namedtuple('Grade', ['category', 'grade'])
    canvas = get_canvas_object()
    for course in get_courses(canvas, course, is_active=False, is_finished=True):
        results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
              assignmentGroupsConnection {
                  nodes { name
                          gradesConnection {
                              edges { node { currentScore
                                             enrollment { user { name } }
                                           } } } } } } }''')
        grades_by_student = defaultdict(list)
        for assignment_group in results['data']['course']['assignmentGroupsConnection']['nodes']:
            category = assignment_group['name']
            if any(x in category.lower() for x in skip):
                continue
            for grade in assignment_group['gradesConnection']['edges']:
                score = grade['node']['currentScore']
                if score:
                    pluses = to_plus(score, thresholds)
                    if pluses:
                        name = grade['node']['enrollment']['user']['name']
                        grades_by_student[name].append(Grade(category, pluses))
        for i in grades_by_student.items():
            label = f'{i[0]}@{format_course_name(course.name)}'
            output(f'{label} {" ".join([g.category+":"+g.grade for g in i[1]])}')
    

def print_config_ini_format(is_info):
    func = info if is_info else error
    func("""[SERVER]
url=https://XXXXX.instructure.com
token=YYYYYYYYYYYYYYYYYYYYYYY

where XXXXX is your organization identifier. for example, SJSU is sjsu.
YYYYYYYYYYYYYYYYYYYYY is the token you generate in canvas with Account->Settings->[New Access Token]
it will look like a long list of letters, numbers, and symbols. copy them after token=
""")


def check_key(key, obj):
    if key not in obj:
        error(f"{key} not in {config_ini}. make sure it has the format of:")
        print_config_ini_format(False)
        sys.exit(2)
    return obj[key]


@canvas_tool.command()
def help_me_setup():
    '''provide guidance through the setup process'''
    if os.path.isfile(config_ini):
        info(f"great! {config_ini} exists. let's check it!")
    else:
        error(f"""{config_ini} does not exist. you need to create it.
it should have the form:""")
        print_config_ini_format(True)
        sys.exit(2)

    parser = ConfigParser()
    try:
        parser.read([config_ini])
    except:
        error(f"there was a problem reading {config_ini}. make sure it has the format of:")
        print_config_ini_format(False)

    check_key("SERVER", parser)
    url = check_key("url", parser["SERVER"])
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        error(f"url in {config_ini} must start with https://")
        sys.exit(2)

    if p.path:
        error(f"url in {config_ini} must have the form http://hostname with no other /")
        sys.exit(2)

    try:
        with urllib.request.urlopen(url) as con:
            info(f"{url} is reachable.")
    except Exception as e:
        error(f"got '{e}' accessing {url}. please check the url in {config_ini}.")
        sys.exit(2)

    token = check_key("token", parser["SERVER"])
    if token and len(token) > 20:
        info(f"token found. checking to see if it is usable")
    else:
        error(f"token is too short. make sure you have copied it correctly from canvas.")
        sys.exit(2)

    try:
        canvas = Canvas(url, token)
        info(f"you are successfully able to use canvas as {canvas.get_current_user().name}")
    except Exception as e:
        error(f"problem accessing canvas: {e}")
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    canvas_tool()
