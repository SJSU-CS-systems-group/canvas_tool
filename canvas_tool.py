from canvasapi import Canvas
from canvasapi.course import Course
import click
from collections import defaultdict, namedtuple
from configparser import ConfigParser
import datetime
import glob
import os
import re
import sys
import urllib

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
        return canvas
    except:
        error(f"there was a problem accessing canvas. try using help-me-setup.")
        sys.exit(2)


@click.group()
def canvas_tool():
    pass


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

            
@canvas_tool.command()
@click.argument('course_name', metavar='course_name')
@click.argument('assignment_name', metavar='assignment_name')
def grade_discussion(course_name, assignment_name):
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

        grade = len(s.discussion_entries)
        if (grade > 2):
            grade = 2
        grades[s] = grade

    if skipped == processed:
        error(f"'{assignment.name}' doesn't appear to be a discussion assignment")
        sys.exit(2)

    info(f"processed {processed}, skipped {skipped}.")

    with click.progressbar(length=len(grades), label="updating grades", show_pos=True) as bar:
        for i in grades.items():
            i[0].edit(submission={'posted_grade': i[1]})
            bar.update(1)


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
        info(f"{c.id} {format_course_name(name, matcher, formatter)} {c.start:%Y-%m-%d} {c.end:%Y-%m-%d}")


@canvas_tool.command()
@click.argument('course')
@click.option('--active/--inactive', default=True, help="show only active courses")
@click.option('--emails/--no_emails', help="list student emails")
def list_students(course, active, emails):
    '''list the students in a course'''
    canvas = get_canvas_object()
    course = get_course(canvas, course, active)
    info(f"found {course.name}")
    info_keys = "name" + (" email" if emails else "")
    results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
               enrollmentsConnection { nodes { user {''' + info_keys + '''} } }
           } }''')
    for r in results['data']['course']['enrollmentsConnection']['nodes']:
        user = r['user']
        print(f"    {user['name']} {user['email'] if 'email' in user else ''}")


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
            print(f'{label} {" ".join([g.category+":"+g.grade for g in i[1]])}')
    

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
