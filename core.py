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
        # sometimes there are prefix matches for an assignment name that is
        # fully given: "Assignment 1" and "Assignment 1 Extended"
        # if there are multiple matches but one exact match, use the exact match
        exact_match = [a for a in filtered_assignments if title == a['title']]
        if len(exact_match) == 1:
            filtered_assignments = exact_match
        else:
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


ResourceRecord = namedtuple("ResourceRecord", ["id", "url", "type", "name", "stub"])

# rr4name and rr4id will have the ResourceRecord type prepended
rr4name = {}
rr4id = {}
rr4url = {}
course_modules = {}


def process_resource_record(rr):
    rr4name[rr.type + rr.name] = rr
    rr4id[rr.type + str(rr.id)] = rr
    rr4url[rr.url] = rr


# strip any query params off (in different places the same url will have different params
def base_url(url):
    return url.split("?")[0]


def map_course_resource_records(course):
    with click.progressbar(length=6, label="mapping existing resources") as bar:
        for folder in course.get_folders():
            for file in folder.get_files():
                process_resource_record(
                    ResourceRecord(file.id, base_url(file.url), "File", os.path.join(str(folder), str(file)).replace("\\", "/"), file.size == 0))
        bar.update(1)
        for assignment in course.get_assignments():
            process_resource_record(
                ResourceRecord(assignment.id, base_url(assignment.html_url), "Assignment", assignment.name, not assignment.description))
        bar.update(1)
        for discussion in course.get_discussion_topics():
            process_resource_record(
                ResourceRecord(discussion.id, base_url(discussion.html_url), "Discussion", discussion.title, not discussion.message))
        bar.update(1)
        for page in course.get_pages(include=["body"]):
            process_resource_record(ResourceRecord(page.page_id, base_url(page.url), "Page", page.title, not page.body))
        bar.update(1)
        for quiz in course.get_quizzes():
            process_resource_record(ResourceRecord(quiz.id, base_url(quiz.html_url), "Quiz", quiz.title, not quiz.description))
        bar.update(1)
        for mod in course.get_modules():
            course_modules[mod.name] = mod
        bar.update(1)

letter_grades = [(98, "A+"), (92, "A"), (90, "A-"), (88, "B+"), (82, "B"), (80, "B-"), (78, "C+"), (72, "C"),
                 (70, "C-"), (68, "D+"), (62, "D"), (60, "D-"), (0, "F")]

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

def points_to_letter(points, round):
    if not points:
        return 'WU'
    points += round
    for letter in letter_grades:
        if points >= letter[0]:
            return letter[1]
