import click

from core import *

# from https://stackoverflow.com/a/925630
from io import StringIO
from html.parser import HTMLParser

class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs= True
        self.text = StringIO()
    def handle_data(self, d):
        self.text.write(d)
    def get_data(self):
        return self.text.getvalue()

def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()

def dehtml(s):
    if type(s) is not str:
        return s
    return strip_tags(s.replace("&nbsp;", ""))


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('quiz_name', metavar='quiz', default='')
@click.option('--show-question/--no-show-question', default=False)
@click.option('--for-student', metavar='students', default=[], multiple=True,
              help='students to get quiz logs for')
@click.option('--summarize/--no-summarize', default=True, show_default=True,
              help='show only completed answers. skip answers that are a prefix of subsequent answers')
def quiz(course_name, quiz_name, show_question, for_student, summarize):
    '''
    get quiz logs for a student
    '''
    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    students = [s.lower() for s in for_student]

    users = {u.id : u.name for u in course.get_users() if len(students) == 0 or [s for s in students if s in u.name.lower()]}
    if len(users) == 0:
        error(f"no students matched {students}")
        exit(2)

    quiz = [q for q in course.get_quizzes() if quiz_name in q.title]
    if len(quiz) == 0:
        error(f"no quizzes matched {quiz_name}")
        exit(2)
    if len(quiz) > 1:
        error(f"multiple matches for {quiz_name}")
        for q in quiz:
            error(f"    {q.title}")
        exit(2)

    quiz = quiz[0]

    answers = []

    questions = {q.id: q for q in quiz.get_questions()}
    for s in quiz.get_submissions():
        if s.user_id not in users:
            continue
        prev = None
        for es in s.get_submission_events():
            if es.event_type != 'question_answered':
                continue
            event_data = es.event_data
            if not type(event_data) is list:
                event_data = [event_data]
            for e in event_data:
                if e['answer']:
                    question = questions[int(e['quiz_question_id'])]
                    data = (users[s.user_id], question.position, es.created_at, dehtml(e['answer']), question.question_text)
                    answers.append(data)

    if summarize:
        answers.sort(reverse=True)
        prev=None
        new_answers = []
        for a in answers:
            if prev == None or prev[0] != a[0] or prev[1] != a[1] or type(a[3]) is not str or type(prev[3]) is not str or not prev[3].startswith(a[3]):
                new_answers.append(a)
            prev = a
        answers = new_answers

    answers.sort(key=lambda x: x[2])
    for a in answers:
        print(f"{a[2]} {a[1]} {a[0]} {a[3]} {a[4] if show_question else ''}")
