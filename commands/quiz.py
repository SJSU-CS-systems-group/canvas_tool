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
    return strip_tags(s.replace("&nbsp;", "").strip().replace("\n", " ").replace("\r",""))


def evolves(base, change):
    if type(base) is not str or type(change) is not str:
        return True
    base_words = set(base.split())
    change_words = set(change.split())
    added = change_words - base_words
    removed = base_words - change_words
    rc = True
    if len(added) == 0:
        rc = False
    if len(added) == 1 and len(removed) >= 1:
        a = added.pop()
        for r in removed:
            if r.startswith(a):
                rc = False
                break
    return rc


def get_question_group(quiz, question_groups, group_id):
    if group_id not in question_groups:
        question_groups[group_id] = quiz.get_quiz_group(group_id)
    return question_groups[group_id]


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('quiz_name', metavar='quiz', default='')
@click.option('--show-question/--no-show-question', default=False, show_default=True)
@click.option('--for-student', metavar='students', default=[], multiple=True,
              help='students to get quiz logs for')
@click.option('--summarize/--no-summarize', default=True, show_default=True,
              help='show only completed answers. skip answers that are a prefix of subsequent answers')
@click.option('--final-answer/--no-final-answer', default=True, show_default=True,
              help='show the final answer, if --no-final-answer, the final answers will be skipped')
def quiz(course_name, quiz_name, show_question, for_student, summarize, final_answer):
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
    question_groups = {}
    for s in quiz.get_submissions():
        if s.user_id not in users:
            continue
        prev = None
        for es in s.get_submission_events():
            time_spent = int(s.time_spent)
            if es.event_type != 'question_answered':
                continue
            event_data = es.event_data
            if not type(event_data) is list:
                event_data = [event_data]
            for e in event_data:
                if e['answer']:
                    question = questions[int(e['quiz_question_id'])]
                    if question.quiz_group_id:
                        position = f"{get_question_group(quiz, question_groups, question.quiz_group_id).position:2}.{question.position:2}"
                    else:
                        position = f"{question.position:5}"
                    data = (users[s.user_id], position, f"{time_spent//60:02}:{time_spent%60:02}", dehtml(e['answer']), question.question_text)
                    answers.append(data)

    if summarize or final_answer:
        answers.sort(reverse=True)
        prev=None
        new_answers = []
        final_answers = {}
        for a in answers:
            skip_answer = False
            if summarize and prev != None and prev[0] == a[0] and prev[1] == a[1] and not evolves(prev[3], a[3]):
                skip_answer = True
            if final_answer and not skip_answer:
                final_key = (a[0], a[1])
                if final_key not in final_answers:
                    final_answers[final_key] = a
                    skip_answer = True
            if not skip_answer:
                new_answers.append(a)
            prev = a
        answers = new_answers

    answers.sort(key=lambda x: x[2])
    for a in answers:
        print(f"{a[1]} {a[2]} {a[0]} {a[3]} {a[4] if show_question else ''}")
