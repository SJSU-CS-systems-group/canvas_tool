import datetime
import functools
import logging
import os
import re
import string
import sys
import tempfile
import urllib
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict, namedtuple
from configparser import ConfigParser
from html.parser import HTMLParser
from typing import NamedTuple

import canvasapi.file
import click
import mosspy
import requests
from canvasapi import Canvas
from canvasapi.course import Course
from canvasapi.discussion_topic import DiscussionEntry
from canvasapi.requester import Requester

course_name_matcher = r"((\S*): (\S+)\s.*)"
course_name_formatter = r"\2:\3"


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


def warn(message):
    click.echo(click.style(message, fg='yellow'))


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
@click.option("--log-level", type=click.Choice(['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], case_sensitive=False),
              help="set python logging level")
def canvas_tool(log_level):
    if log_level:
        log_level_int = getattr(logging, log_level.upper())
        print(log_level_int)
        logging.basicConfig(level=log_level_int)


def get_course(canvas, name, is_active=True) -> Course:
    """ find one course based on partial match """
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
        if is_finished and end >= now:
            continue
        if name in c.name:
            c.start = start
            c.end = end
            course_list.append(c)
    return course_list


def get_assignments(course, title):
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
    return filtered_assignments


def get_assignment(course, title):
    filtered_assignments = get_assignments(course, title)
    if len(filtered_assignments) == 0:
        error(f'{title} assignment not found. possible assignments are:')
        for a in get_assignments(course, ""):
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

    ratio = round(len(word) / len(vowels), 1)
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
    result = canvas.graphql(query, {"assignmentid": assignment.id})
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


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('assignment_name', metavar='assignment', default='')
@click.argument('language', metavar='language')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
              help="only show the grade, don't actually set it")
def code_similarity(course_name, language, assignment_name, dryrun):
    '''
    check submissions for code similarity using stanford MOSS.
    '''
    canvas = get_canvas_object()
    course = get_course(canvas, course_name)
    usermap = {u.id: u.name for u in course.get_users()}
    assignment = get_assignment(course, assignment_name)
    parser = ConfigParser()
    parser.read([config_ini])
    moss_userid = parser['MOSS']['userid']
    moss = mosspy.Moss(moss_userid, language)
    with tempfile.TemporaryDirectory("canvas_tool.attach") as tempdir:
        submissions = list(assignment.get_submissions())
        with click.progressbar(length=len(submissions), label="downloading", item_show_func=lambda x: x) as bar:
            for sub in assignment.get_submissions():
                if sub.user_id not in usermap:
                    continue
                udir = f"{tempdir}/{usermap[sub.user_id]}"
                os.makedirs(udir)
                bar.update(1, usermap[sub.user_id])
                for attachment in sub.attachments:
                    aname = f"{udir}/{attachment.filename}"
                    with open(aname, "wb") as f:
                        f.write(requests.get(attachment.url).content)
                    if aname.endswith(".zip"):
                        with zipfile.ZipFile(aname, "r") as zf:
                            zf.extractall(udir)
        moss.addFilesByWildcard(f"{tempdir}/**/*.{language}")
        count = len(moss.files)
        with click.progressbar(length=count, label="uploading", item_show_func=lambda x: x) as bar:
            moss_url = moss.send(on_send=lambda fp, dn: bar.update(1, dn))
        print(moss_url)


def download_attachment(basename, a):
    fname = a['displayName']
    suffix = os.path.splitext(fname)[1]
    durl = a['url']
    info(f'downloading {a}')
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
@click.option('--min-words', default=5, show_default=True, help="the minimum number of valid words to get credit")
@click.option('--points-comment', default=1, show_default=True, help="number of points for posting a comment")
@click.option('--max-points', default=2, show_default=True, help="maximum number of points to give")
def grade_discussion(course_name, assignment_name, dryrun, min_words, points_comment, max_points):
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

    now = datetime.datetime.now(datetime.timezone.utc)
    assignments = get_assignments(course, assignment_name)
    for assignment_data in assignments:
        info(f"grading {assignment_data['title']}")
        assignment = course.get_assignment(assignment_data['assignment_id'])
        due_at_date = assignment.due_at_date
        if due_at_date > now:
            warn(f"{assignment_data['title']} not due: skipping")
            continue
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
                entry = DiscussionEntry(None, entry)
                if entry.created_at_date > due_at_date:
                    info(
                        f"skipping discussion from {s.user_id} submitted at {entry.created_at_date} but due {due_at_date}")
                    continue
                if count_words(entry.message) > 5:
                    grade = min(grade + points_comment, max_points)

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
@click.argument('points', default=-666, type=float)
@click.option('--dryrun/--no-dryrun', default=True, show_default=True,
              help="only show the grade, don't actually set it")
@click.option('--decrease/--no-decrease', default=False, show_default=True,
              help='If not true, the fudge points will not be updated if new points < old points.')
def set_fudge_points(course_name, quiz_name, points, dryrun, decrease):
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
            if points == -666:
                info(f"{s.user_id} {s.fudge_points}")
            else:
                if not decrease and s.fudge_points > points:
                    info(f"skipping {s.user_id} with {s.fudge_points} points")
                else:
                    if dryrun:
                        info(f"would update fudge points for {s.user_id} from {s.fudge_points} to {points}")
                    else:
                        info(f"updating fudge points for {s.user_id} from {s.fudge_points} to {points}")
                        # s.update_score_and_comments(fudge_points=points)
                        s.update_score_and_comments(quiz_submissions=[{"attempt": s.attempt, 'fudge_points': points}])


@canvas_tool.command()
@click.option('--active/--inactive', default=True, help="show only active courses")
@click.option('--matcher', default=course_name_matcher, show_default=True, metavar="match_re_expression",
              help="course name regular expressions matcher")
@click.option('--formatter', default=course_name_formatter, show_default=True, metavar="format_re_expression", help="""
              course name regular expressions formatter based on the matcher pattern.
              a format pattern of - will turn off formatting.
              """)
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
        if emails:
            output(f"    {user['email']} {user['name']} ")
        else:
            output(f"    {user['name']} ")


@canvas_tool.command()
@click.argument('course')
@click.argument('subject')
@click.option('--course-in-subject/--no-course-in-subject', show_default=True, default=True,
              help='include the course name in []s in the subject line')
@click.option('--message', help="message to send")
@click.option('--from-file', help="file containing message to send (- for stdin)", type=click.File('r'))
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


letter_grades = [(98, "A+"), (92, "A"), (90, "A-"), (88, "B+"), (82, "B"), (80, "B-"), (78, "C+"), (72, "C"),
                 (70, "C-"), (68, "D+"), (62, "D"), (60, "D-"), (0, "F")]


def points_to_letter(points, round):
    if not points:
        return 'WU'
    points += round
    for letter in letter_grades:
        if points >= letter[0]:
            return letter[1]


@canvas_tool.command()
@click.argument("course")
@click.option("--round", default=0.0, help="points to add to the final score before calculating the letter grade.")
@click.option("--dryrun/--no-dryrun", default=True)
def set_letter_grade(course, round, dryrun):
    ''' calculate the letter grade based on the final score in the class.

    the "Reported Letter Grade" assignment must be created in the gradebook as a letter grade assignment
    before this command is run.
    the command will loop through all the students in the class and set the letter grade in that assignment
    based on the final score in the class.
    '''

    canvas = get_canvas_object()
    course = get_course(canvas, course)

    rlg_assignment = get_assignment(course, "Reported Letter Grade")
    if not rlg_assignment:
        error('the "Reported Letter Grade" assignment hasn\'t been set up')
        exit(2)

    user_to_grade = {}
    for enrollment in course.get_enrollments(include=['grades']):
        if hasattr(enrollment, "grades"):
            current_score = enrollment.grades['current_score']
            final_score = enrollment.grades['final_score']
            if current_score != final_score:
                warn(f"current_score of {current_score} != {final_score} for {enrollment.user['name']} SKIPPING")
                continue
            letter = points_to_letter(enrollment.grades['final_score'], round)
            user_to_grade[enrollment.user['id']] = (enrollment.user, letter, enrollment.grades['final_score'])

    if dryrun:
        for submission in rlg_assignment.get_submissions():
            if submission.user_id in user_to_grade:
                (user, letter, score) = user_to_grade[submission.user_id]
                info(f"{letter} {score} {user['name']}")
        warn("This was a dryrun. Nothing has been updated")
    else:
        with click.progressbar(length=len(user_to_grade), label="updating grades", show_pos=True) as bar:
            for submission in rlg_assignment.get_submissions():
                if submission.user_id in user_to_grade:
                    (user, letter, score) = user_to_grade[submission.user_id]
                    submission.edit(submission={'posted_grade': letter})
                    bar.update(1)


@canvas_tool.command()
@click.argument("course")
@click.argument("csv_output_file", type=click.File("w"))
def export_letter_grade(course, csv_output_file):
    ''' export course letter grade to CSV

    the "Reported Letter Grade" column must be setup in the gradebook.
    this command will pull down the letter grades from that column an print a CSV record
    with the student id and the corresponding letter grade.
    output will got to the indicated csv_output_file.
    an output file name of - will go to stdout.
    '''

    canvas = get_canvas_object()
    course = get_course(canvas, course)

    rlg_assignment = get_assignment(course, "Reported Letter Grade")
    if not rlg_assignment:
        error('the "Reported Letter Grade" assignment hasn\'t been set up')
        exit(2)

    count = 0
    csv_output_file.write("Student ID,Grade\n")
    for submission in rlg_assignment.get_submissions():
        user = course.get_user(submission.user_id)
        if user.sis_user_id:
            csv_output_file.write(f"{user.sis_user_id}, {submission.grade}\n")
            count += 1

    info(f"{count} records written to {csv_output_file.name}")


def to_letter_grade(score):
    if score > 89:
        return 'A'
    if score > 79:
        return 'B'
    if score > 69:
        return 'C'
    if score > 59:
        return 'D'
    return 'F'


@canvas_tool.command()
@click.argument("course")
@click.option('-m', 'min_grade', default=50.0, show_default=True, help="""
              the minimum assignment grade. any score below this grade will be set to
              this minimum score.
              """)
def min_grade_analyzer(course, min_grade):
    '''see what the scores would look like with minimum grade'''
    canvas = get_canvas_object()
    min_grade = min_grade / 100
    for course in get_courses(canvas, course, is_active=False, is_finished=True):
        # first get all the grade categories and track the ones with weights
        results = canvas.graphql('query { course(id: "' + str(course.id) + '''") {
                    enrollmentsConnection {
                        nodes {
                            grades { currentScore }
                            user { name }
                        }
                    }
                    assignmentGroupsConnection {
                      nodes {
                        groupWeight
                        name
                        id
                      }
                    }
                  }
                } ''')
        class_grade_by_student = {}
        for enrollment in results['data']['course']['enrollmentsConnection']['nodes']:
            class_grade_by_student[enrollment['user']['name']] = enrollment['grades']['currentScore']

        grades_by_student = defaultdict(lambda: defaultdict(list))
        assignment_groups = [assignment_group for assignment_group in
                             results['data']['course']['assignmentGroupsConnection']['nodes'] if
                             assignment_group['groupWeight']]
        weights = {}
        for assignment_group in assignment_groups:
            category = assignment_group['name']
            weight = assignment_group['groupWeight']
            weights[category] = weight
            assignment_group_id = assignment_group['id']
            assignments = canvas.graphql('query { assignmentGroup(id: "' + assignment_group_id + '''") {
                                         assignmentsConnection {
                                             nodes {
                                                 id
                                                 name
                                             }
                                         }}}''')
            for assignment in assignments['data']['assignmentGroup']['assignmentsConnection']['nodes']:
                assignment_id = assignment['id']
                scores = canvas.graphql('query { assignment(id: "' + assignment_id + '''") {
                                             name
                                             pointsPossible
                                             submissionsConnection {
                                                 nodes {
                                                     score
                                                      user { name }
                                                 }
                                             }
                                         } }''')
                points_possible = scores['data']['assignment']['pointsPossible']
                for score in scores['data']['assignment']['submissionsConnection']['nodes']:
                    currentScore = score['score']
                    name = score['user']['name']
                    if currentScore == None:
                        continue
                    grades_by_student[name][category].append((currentScore, points_possible))

        for (name, assignments) in grades_by_student.items():
            total = 0.0
            min_total = 0.0
            components = []
            for (cat, scores) in assignments.items():
                cat_total = sum([current_score for (current_score, points_possible) in scores])
                min_scores = [(
                    current_score if not points_possible or current_score >= points_possible * min_grade else points_possible * min_grade,
                    points_possible) for (current_score, points_possible) in scores]
                min_cat_total = sum([current_score for (current_score, points_possible) in min_scores])
                cat_possible = sum([points_possible for (current_score, points_possible) in scores])
                if cat_possible == 0:
                    cat_possible = 100
                cat_avg = cat_total / cat_possible
                min_avg = min_cat_total / cat_possible
                inc = cat_avg * weights[cat]
                min_inc = min_avg * weights[cat]
                total += inc
                min_total += min_inc
                components.append((cat,
                                   cat_avg * 100))  # print(f'{scores} {cat_avg} {weights[cat]} {inc} {total} {min_total} {" " if total == min_total else "*****"}')
            letter = to_letter_grade(total)
            min_letter = to_letter_grade(min_total)
            if letter != min_letter:
                output(f'{name}@{class_grade_by_student[name]}@{total}({letter}) {min_total}({min_letter})')


@canvas_tool.command()
@click.argument("course")
@click.option('-t', 'thresholds', metavar='threshold', multiple=True, default=[84, 90, 95], show_default=True,
              type=click.INT, help="""
              assignment groups with grades about the lowest threshold will have a +, the next
              lowest gets ++, and so on. assignment groups below the lowest threshold will not
              be printed.
              """)
@click.option('-s', 'skip', metavar='skip_assignment', multiple=True, default=['iclickr', 'ungraded', 'imported'],
              show_default=True, help="""
              assignment groups with the listed keywords will not be collected.
              """)
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
                name = grade['node']['enrollment']['user']['name']
                if score:
                    pluses = to_plus(score, thresholds)
                    if pluses:
                        grades_by_student[name].append(Grade(category, pluses))
        for i in grades_by_student.items():
            label = f'{i[0]}@{format_course_name(course.name)}'
            output(f'{label} {" ".join([g.category + ":" + g.grade for g in i[1]])}')


def print_config_ini_format(is_info):
    func = info if is_info else error
    func("""[SERVER]
url=https://XXXXX.instructure.com
token=YYYYYYYYYYYYYYYYYYYYYYY
[MOSS]
userid=ZZZZZZZZZXX

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


# very simple sanitizer to escape semicolons, tabs, and newlines
def sanitize(name):
    return name.replace(';', ',').replace("\n", "\\n").replace("\t", "\\t")


ResourceRecord = namedtuple("ResourceRecord", ["id", "url", "type", "name"])

# rr4name and rr4id will have the ResourceRecord type prepended
rr4name = {}
rr4id = {}
rr4url = {}


def process_resource_record(rr):
    rr4name[rr.type + rr.name] = rr
    rr4id[rr.type + str(rr.id)] = rr
    rr4url[rr.url] = rr


# strip any query params off (in different places the same url will have different params
def base_url(url):
    return url.split("?")[0]


def map_course_resource_records(course):
    for folder in course.get_folders():
        for file in folder.get_files():
            process_resource_record(
                ResourceRecord(file.id, base_url(file.url), "File", os.path.join(str(folder), str(file))))

    for assignment in course.get_assignments():
        process_resource_record(
            ResourceRecord(assignment.id, base_url(assignment.html_url), "Assignment", assignment.name))
    for discussion in course.get_discussion_topics():
        process_resource_record(
            ResourceRecord(discussion.id, base_url(discussion.html_url), "Discussion", discussion.title))
    for page in course.get_pages():
        process_resource_record(ResourceRecord(page.page_id, base_url(page.html_url), "Page", page.title))
    for quiz in course.get_quizzes():
        process_resource_record(ResourceRecord(quiz.id, base_url(quiz.html_url), "Quiz", quiz.title))


def download_modules(course, target, dryrun):
    def get_name_from_url(url):
        # super hacky!!! for some reason /api/v1 is in the module url but not in the url of the objects
        url = url.replace("/api/v1", "")
        if url not in rr4url:
            error(f"{url} is not in {rr4url.keys()}")
        return sanitize(rr4url[base_url(url)].name)

    def base_inner_module_to_str(module_item):
        return f'{"  " * (module_item.indent + 1)}* {sanitize(module_item.title)}{"" if module_item.published else "; !published"}'

    def named_inner_module_to_str(module_item):
        return f'{base_inner_module_to_str(module_item)}; {module_item.type}: {get_name_from_url(module_item.url)}'

    module_renderers = {
        "Assignment": named_inner_module_to_str,
        "Page": named_inner_module_to_str,
        "Quiz": named_inner_module_to_str,
        "Discussion": named_inner_module_to_str,
        "SubHeader": base_inner_module_to_str,
        "ExternalUrl": lambda
            mi: f'{base_inner_module_to_str(mi)}; ExternalUrl; {"" if mi.new_tab else "!"}newtab; {mi.external_url}',
        "ExternalTool": lambda
            mi: f'{base_inner_module_to_str(mi)}; ExternalTool; {"" if mi.new_tab else "!"}newtab; {mi.url}; {mi.external_url}',
    }

    top_modules = []
    id2name = {}
    output = ''
    for module in course.get_modules():
        id2name[module.id] = module.name
        ms = f"# {module.name}"
        if module.unlock_at:
            ms += f"; unlock={module.unlock_at}"
        if module.require_sequential_progress:
            ms += f"; sequential"
        if module.prerequisite_module_ids:
            ms += f"; prereqs={','.join([id2name[id] for id in module.prerequisite_module_ids])}"
        if module.completed_at:
            ms += f"; completed={module.completed_at}"
        if not module.published:
            ms += f"; !published"
        output += ms + '\n'
        for item in module.get_module_items():
            if item.type in module_renderers:
                output += module_renderers[item.type](item) + '\n'
            else:
                warn(f"cannot render {item.__dict__}")

    if dryrun:
        info(f"would have written:\n{output}to {target}")
    else:
        with open(target, "w") as fd:
            fd.write(output)


def download_discussions(course, target, dryrun):
    pass


def download_assignments(course, target, dryrun):
    pass


def download_pages(course, target, dryrun):
    pass


def download_files(course, target, dryrun):
    class ToDownload(NamedTuple):
        file: canvasapi.file.File
        target: str

    error_seen = False
    to_download = []
    for folder in course.get_folders():
        target_dir = os.path.join(target, str(folder))
        if os.path.exists(target_dir):
            if not os.path.isdir(target_dir):
                error(f"{target_dir} is not a directory. skipping")
                error_seen = True
                continue
        else:
            if dryrun:
                info(f"would create {target_dir}")
            else:
                os.makedirs(target_dir)

        for file in folder.get_files():
            full_name = os.path.join(str(folder), str(file))
            target_file = os.path.join(target_dir, str(file))
            if dryrun:
                info(f"would download {full_name} to {target_file}")
            else:
                if os.path.exists(target_file):
                    warn(f"{target_file} already exists. skipping")
                else:
                    to_download.append(ToDownload(file, target_file))

    if to_download:
        with click.progressbar(to_download, label="downloading",
                               item_show_func=lambda i: str(i.file) if i else "") as tds:
            for td in tds:
                td.file.download(td.target)
    if error_seen:
        exit(2)


def download_announcements(course, target, dryrun):
    pass


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True, help="show what would happen, but don't do it.")
@click.option('--modules/--no-modules', default=False, show_default=True,
              help=f"download modules to the {click.style('modules', underline=True, italic=True)} file.")
@click.option('--discussions', default=False, show_default=True,
              help=f"download discussions to the {click.style('discussions', underline=True, italic=True)} subdirectory.")
@click.option('--assignments', default=False, show_default=True,
              help=f"download assignments to the {click.style('assignments', underline=True, italic=True)} subdirectory.")
@click.option('--pages', default=False, show_default=True,
              help=f"download pages to the {click.style('pages', underline=True, italic=True)} subdirectory.")
@click.option('--files', default=False, show_default=True,
              help=f"download files to the {click.style('files', underline=True, italic=True)} subdirectory.")
@click.option('--announcements', default=False, show_default=True,
              help=f"download announcements to the {click.style('announcements', underline=True, italic=True)} subdirectory.")
@click.option('--all/--no-all', default=False, show_default=True,
              help="download all content to corresponding directories")
@click.option("--target", default='.', show_default=True, help="download content parent directory.")
def download_course_content(course_name, dryrun, modules, discussions, assignments, pages, files, announcements, all,
                            target):
    canvas = get_canvas_object()
    course = get_course(canvas, course_name, is_active=False)
    output(f"found {course.name}")
    map_course_resource_records(course)

    if all:
        modules = discussions = assignments = pages = files = announcements = True

    if not (modules or discussions or assignments or pages or files or announcements):
        error("nothing selected to download")
        exit(1)

    if modules:
        download_modules(course, os.path.join(target, 'modules'), dryrun)
    if discussions:
        download_discussions(course, os.path.join(target, 'discussions'), dryrun)
    if assignments:
        download_assignments(course, os.path.join(target, 'assignments'), dryrun)
    if pages:
        download_pages(course, os.path.join(target, 'pages'), dryrun)
    if files:
        download_files(course, os.path.join(target, 'files'), dryrun)
    if announcements:
        download_announcements(course, os.path.join(target, 'announcements'), dryrun)


def upload_modules(course, target, dryrun):
    pass


def upload_discussions(course, target, dryrun):
    pass


def upload_assignments(course, target, dryrun):
    pass


def upload_pages(course, target, dryrun):
    pass


def upload_files(course, target, dryrun):
    to_upload = set([os.path.join(d, f)[len(target) + 1:] for (d, sds, fs) in os.walk(target) for f in fs])

    existing_files = set()
    for folder in course.get_folders():
        for file in folder.get_files():
            existing_files.add(os.path.join(str(folder), str(file)))

    for common in to_upload.intersection(existing_files):
        warn(f"{common} already exists. skipping.")

    uploads = list(to_upload.difference(existing_files))
    if dryrun:
        for up in uploads:
            name = os.path.basename(up)
            parent = os.path.dirname(up)
            info(f"would upload {name} to {parent}")
    else:
        with click.progressbar(uploads, label="uploading",
                               item_show_func=lambda i: i if i else "") as ups:
            for up in ups:
                name = os.path.basename(up)
                parent = os.path.dirname(up)
                course.upload(os.path.join(target, up), parent_folder_path=parent, name=name)


def upload_announcements(course, target, dryrun):
    pass


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.option('--dryrun/--no-dryrun', default=True, show_default=True, help="show what would happen, but don't do it.")
@click.option('--modules', default=False, show_default=True,
              help=f"upload modules to the {click.style('modules', underline=True, italic=True)} subdirectory.")
@click.option('--discussions', default=False, show_default=True,
              help=f"upload discussions to the {click.style('discussions', underline=True, italic=True)} subdirectory.")
@click.option('--assignments', default=False, show_default=True,
              help=f"upload assignments to the {click.style('assignments', underline=True, italic=True)} subdirectory.")
@click.option('--pages', default=False, show_default=True,
              help=f"upload pages to the {click.style('pages', underline=True, italic=True)} subdirectory.")
@click.option('--files', default=False, show_default=True,
              help=f"upload files to the {click.style('files', underline=True, italic=True)} subdirectory.")
@click.option('--announcements', default=False, show_default=True,
              help=f"upload announcements to the {click.style('announcements', underline=True, italic=True)} subdirectory.")
@click.option('--all/--no-all', default=False, show_default=True,
              help="upload all content to corresponding directories")
@click.option("--target", default='.', show_default=True, help="upload content parent directory.")
def upload_course_content(course_name, dryrun, modules, discussions, assignments, pages, files, announcements, all,
                          target):
    canvas = get_canvas_object()
    course = get_course(canvas, course_name, is_active=False)
    output(f"found {course.name}")

    if all:
        modules = discussions = assignments = pages = files = announcements = True

    if not (modules or discussions or assignments or pages or files or announcements):
        error("nothing selected to upload")
        exit(1)

    if modules:
        upload_modules(course, os.path.join(target, 'modules'), dryrun)
    if discussions:
        upload_discussions(course, os.path.join(target, 'discussions'), dryrun)
    if assignments:
        upload_assignments(course, os.path.join(target, 'assignments'), dryrun)
    if pages:
        upload_pages(course, os.path.join(target, 'pages'), dryrun)
    if files:
        upload_files(course, os.path.join(target, 'files'), dryrun)
    if announcements:
        upload_announcements(course, os.path.join(target, 'announcements'), dryrun)


@canvas_tool.command()
def help_me_setup():
    """provide guidance through the setup process"""
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
