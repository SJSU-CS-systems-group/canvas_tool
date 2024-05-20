from core import *


@canvas_tool.command()
@click.argument('course_name', metavar='course')
@click.argument('quiz_name', metavar='quiz', default='')
@click.argument('student_name', metavar='student', default='')
def quiz(course_name, quiz_name, student_name):
    '''
    get quiz logs for a student
    '''
    canvas = get_canvas_object()

    course = get_course(canvas, course_name)

    users = [u for u in course.get_users() if student_name.lower() in u.name.lower()]
    if len(users) == 0:
        error(f"no students matched {student_name}")
        exit(2)
    if len(users) > 1:
        error(f"multiple matches for {student_name}")
        for u in users:
            error(f"    {u.name}")
        exit(2)
    user = users[0]

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

    questions = {q.id: q for q in quiz.get_questions()}
    submission = [s for s in quiz.get_submissions() if s.user_id == user.id]
    for s in submission:
        prev = None
        for e in [(es.created_at, questions[int(e['quiz_question_id'])].position) for es in s.get_submission_events() if es.event_type == 'question_answered' for e in es.event_data]:
            if e[1] != prev:
                print(e)
                prev = e[1]
